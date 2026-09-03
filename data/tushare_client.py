"""Small Tushare API client with token rotation, rate limiting, and retries."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import click
import tushare as ts


class RateLimiter:
    """Sliding-window limiter shared by one Tushare token."""

    def __init__(self, calls_per_minute: int = 200, safety_ratio: float = 0.9):
        effective_calls = max(1, int(calls_per_minute * safety_ratio))
        self.calls_per_minute = effective_calls
        self._min_interval = 60.0 / effective_calls
        self._last_call = 0.0
        self._cooldown_until = 0.0
        self._lock = threading.Lock()

    def wait(self, cancel_event: Optional[threading.Event] = None):
        with self._lock:
            now = time.monotonic()
            wait = max(
                self._last_call + self._min_interval - now,
                self._cooldown_until - now,
            )
            if wait > 0:
                if cancel_event is not None and cancel_event.wait(wait):
                    raise KeyboardInterrupt
                if cancel_event is None:
                    time.sleep(wait)
            self._last_call = time.monotonic()

    def cooldown(self, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock:
            self._cooldown_until = max(
                self._cooldown_until,
                time.monotonic() + seconds,
            )

    def delay_seconds(self) -> float:
        with self._lock:
            now = time.monotonic()
            return max(
                self._last_call + self._min_interval - now,
                self._cooldown_until - now,
                0.0,
            )


class TushareClient:
    """Token-aware Tushare wrapper used by DataDownloader."""

    def __init__(
        self,
        tokens: list[str],
        calls_per_minute: int = 200,
        safety_ratio: float = 0.9,
        retries: int = 2,
        backoff_seconds: float = 75,
        cancel_event: Optional[threading.Event] = None,
        pro_factory: Callable[[str], object] = ts.pro_api,
    ):
        if not tokens:
            raise ValueError("缺少 Tushare token，请配置 tushare.token 或 tushare.tokens")
        self._retries = int(retries)
        self._backoff_seconds = float(backoff_seconds)
        self._cancel_event = cancel_event
        self._api_slot_index = 0
        self._api_slot_lock = threading.Lock()
        self._api_slots = [
            {
                "name": f"token#{idx}",
                "pro": pro_factory(token),
                "limiter": RateLimiter(calls_per_minute, safety_ratio),
            }
            for idx, token in enumerate(tokens, start=1)
        ]

    @classmethod
    def from_config(
        cls,
        config: dict,
        cancel_event: Optional[threading.Event] = None,
        pro_factory: Callable[[str], object] = ts.pro_api,
    ) -> "TushareClient":
        rate_cfg = config.get("rate_limit", {})
        return cls(
            tokens=configured_tokens(config),
            calls_per_minute=rate_cfg.get("calls_per_minute", 200),
            safety_ratio=rate_cfg.get("safety_ratio", 0.9),
            retries=rate_cfg.get("retries", 2),
            backoff_seconds=rate_cfg.get("backoff_seconds", 75),
            cancel_event=cancel_event,
            pro_factory=pro_factory,
        )

    @property
    def primary_api(self):
        return self._api_slots[0]["pro"]

    @property
    def effective_calls_per_minute(self) -> int:
        return sum(slot["limiter"].calls_per_minute for slot in self._api_slots)

    def cooldown_all(self, seconds: float) -> None:
        for slot in self._api_slots:
            slot["limiter"].cooldown(seconds)

    def wait_once(self) -> None:
        self._next_api_slot()["limiter"].wait(self._cancel_event)

    def call(self, symbol: str, api_name: str, call: Callable[[object], object]):
        attempts = max(0, self._retries) + 1
        for attempt in range(attempts):
            if self._cancel_event is not None and self._cancel_event.is_set():
                raise KeyboardInterrupt
            slot = self._next_api_slot()
            limiter = slot["limiter"]
            limiter.wait(self._cancel_event)
            try:
                return call(slot["pro"])
            except Exception as e:
                if is_rate_limit_error(e) and attempt < attempts - 1:
                    wait_seconds = self._backoff_seconds * (2 ** attempt)
                    limiter.cooldown(wait_seconds)
                    click.echo(
                        f"  [{symbol}] {api_name} {slot['name']} 触发频率限制，"
                        f"该账号冷却 {wait_seconds:.0f}s 后重试...",
                        err=True,
                    )
                    continue
                click.echo(f"  [{symbol}] {api_name} API 调用失败: {e}", err=True)
                raise

    def call_primary(self, symbol: str, api_name: str, call: Callable[[object], object]):
        """Call with the configured primary token for permission-sensitive APIs."""
        attempts = max(0, self._retries) + 1
        slot = self._api_slots[0]
        limiter = slot["limiter"]
        for attempt in range(attempts):
            if self._cancel_event is not None and self._cancel_event.is_set():
                raise KeyboardInterrupt
            limiter.wait(self._cancel_event)
            try:
                return call(slot["pro"])
            except Exception as e:
                if is_rate_limit_error(e) and attempt < attempts - 1:
                    wait_seconds = self._backoff_seconds * (2 ** attempt)
                    limiter.cooldown(wait_seconds)
                    click.echo(
                        f"  [{symbol}] {api_name} {slot['name']} 触发频率限制，"
                        f"该账号冷却 {wait_seconds:.0f}s 后重试...",
                        err=True,
                    )
                    continue
                click.echo(f"  [{symbol}] {api_name} API 调用失败: {e}", err=True)
                raise

    def _next_api_slot(self) -> dict:
        with self._api_slot_lock:
            count = len(self._api_slots)
            for offset in range(count):
                idx = (self._api_slot_index + offset) % count
                slot = self._api_slots[idx]
                if slot["limiter"].delay_seconds() <= 0:
                    self._api_slot_index = (idx + 1) % count
                    return slot
            delays = [slot["limiter"].delay_seconds() for slot in self._api_slots]
            idx = min(range(count), key=lambda i: delays[i])
            self._api_slot_index = (idx + 1) % count
            return self._api_slots[idx]


def configured_tokens(config: dict) -> list[str]:
    tushare_cfg = config.get("tushare", {})
    tokens: list[str] = []
    primary = tushare_cfg.get("token")
    if primary:
        tokens.append(str(primary).strip())
    for token in tushare_cfg.get("tokens", []) or []:
        if token:
            tokens.append(str(token).strip())

    seen = set()
    unique_tokens = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    if not unique_tokens:
        raise ValueError("缺少 Tushare token，请配置 tushare.token 或 tushare.tokens")
    return unique_tokens


def is_rate_limit_error(error: Exception) -> bool:
    text = str(error)
    return "频率超限" in text or ("访问接口" in text and "频率" in text)
