"""External ETF signal file adapters."""

from __future__ import annotations

from ftplib import FTP
import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import resolve_ftp_config
from .data_provider import normalize_etf_symbol


ETF_CODE_RE = re.compile(r"(\d{6})(?!.*\d{6})")
def parse_rank_target(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    match = ETF_CODE_RE.search(raw)
    symbol = normalize_etf_symbol(match.group(1)) if match else ""
    name = raw
    if match:
        name = raw[: match.start()].replace("[海]", "").strip(" []")
    status_match = re.search(r"(上涨趋势|上涨趋缓|下跌趋势|由涨转跌|震荡|横盘)", raw)
    status = status_match.group(1) if status_match else ""
    return {"raw": raw, "name": name, "symbol": symbol, "status": status}


def parse_rank_change(value: Any) -> int:
    text = str(value or "").strip()
    if text.startswith("↑"):
        return int(re.sub(r"\D", "", text) or 0)
    if text.startswith("↓"):
        return -int(re.sub(r"\D", "", text) or 0)
    return 0


class ExternalSignalProvider:
    """Read or refresh externally produced ETF red/green and ranking files."""

    def __init__(self, config: dict[str, Any], ftp_factory: Callable[[], FTP] | None = None):
        section = config.get("etf_strategy", {})
        data_config = config.get("data", {}) or {}
        self.signal_dir = Path(section.get("external_signal_dir") or Path(data_config.get("meta_dir", "data/meta")) / "etf_external_signals")
        self.red_green_path = _configured_signal_path(section.get("red_green_path"), self.signal_dir, "指数通行红绿灯.csv")
        self.rank_emotion_path = _configured_signal_path(section.get("rank_emotion_path"), self.signal_dir, "指数通行红绿灯带排名和情绪.csv")
        self.ftp_config = resolve_ftp_config(section.get("ftp", {}) or {})
        self.ftp_factory = ftp_factory or FTP
        self._downloaded: set[str] = set()
        self._red_green_cache: pd.DataFrame | None = None
        self._rank_emotion_cache: pd.DataFrame | None = None
        self.download_errors: list[str] = []

    def load_red_green_signal(self) -> pd.DataFrame:
        if self._red_green_cache is None:
            self._maybe_download("red_green")
            self._red_green_cache = _read_optional_csv(_resolve_signal_path(self.red_green_path, "指数通行红绿灯"))
        return self._red_green_cache.copy()

    def load_rank_emotion_signal(self) -> pd.DataFrame:
        if self._rank_emotion_cache is None:
            self._maybe_download("rank_emotion")
            self._rank_emotion_cache = _read_optional_csv(_resolve_signal_path(self.rank_emotion_path, "指数通行红绿灯带排名和情绪"))
        return self._rank_emotion_cache.copy()

    def refresh(self) -> dict[str, Any]:
        """Download both external signal directories once and return local paths."""
        self._downloaded.clear()
        self.download_errors.clear()
        self._red_green_cache = None
        self._rank_emotion_cache = None
        self._maybe_download("red_green", force=True)
        self._maybe_download("rank_emotion", force=True)
        return {"red_green_path": self.red_green_path, "rank_emotion_path": self.rank_emotion_path}

    def _maybe_download(self, kind: str, force: bool = False) -> None:
        if not _truthy(self.ftp_config.get("enabled")) or not _truthy(self.ftp_config.get("auto_download")):
            return
        if kind in self._downloaded and not force:
            return
        remote_leaf = str(self.ftp_config.get(f"{kind}_remote_dir") or "").strip()
        if not remote_leaf:
            return
        remote_root = str(self.ftp_config.get("remote_root") or "").rstrip("/")
        remote_dir = f"{remote_root}/{remote_leaf}"
        self.signal_dir.mkdir(parents=True, exist_ok=True)
        downloader = FtpSignalDownloader(self.ftp_config, ftp_factory=self.ftp_factory)
        try:
            downloader.download_dir(remote_dir=remote_dir, local_dir=self.signal_dir)
        except Exception as exc:
            self.download_errors.append(f"{remote_leaf}: {exc}")
            return
        self._downloaded.add(kind)


class FtpSignalDownloader:
    """Small FTP directory downloader compatible with QTYX_352 signal folders."""

    def __init__(self, ftp_config: dict[str, Any], ftp_factory: Callable[[], FTP] | None = None):
        self.config = ftp_config
        self.ftp_factory = ftp_factory or FTP

    def download_dir(self, remote_dir: str, local_dir: str | Path) -> None:
        server = str(self.config.get("server") or "").strip()
        username = str(self.config.get("username") or "").strip()
        password = str(self.config.get("password") or "").strip()
        if not server or not username or not password:
            raise ValueError(
                "ETF FTP 凭据未配置；请在本机设置 QUANTYB_ETF_FTP_PASSWORD，"
                "或仅使用本地 external_signal_dir 文件"
            )
        ftp = self.ftp_factory()
        try:
            ftp.connect(
                server,
                int(self.config.get("port") or 21),
                timeout=int(self.config.get("timeout") or 30),
            )
            ftp.login(username, password)
            ftp.encoding = str(self.config.get("encoding") or "GB2312")
            ftp.cwd(remote_dir)
            self._download_current_dir(ftp, Path(local_dir))
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    def _download_current_dir(self, ftp: FTP, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        for name in ftp.nlst():
            if not name or name in {".", ".."}:
                continue
            local = local_dir / Path(str(name)).name
            if _ftp_is_dir(ftp, name):
                ftp.cwd(name)
                self._download_current_dir(ftp, local)
                ftp.cwd("..")
            else:
                with local.open("wb") as handle:
                    ftp.retrbinary(f"RETR {name}", handle.write)


def parse_rank_emotion_frame(frame: pd.DataFrame, top_n: int = 10) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"ranking": [], "new_entries": [], "exits": [], "smash_signals": [], "trend_status": [], "log": "暂无外部排名文件"}
    rows: list[dict[str, Any]] = []
    previous_top: list[dict[str, Any]] = []
    current_rank = 1
    for idx, row in frame.iterrows():
        target = parse_rank_target(str(idx if not isinstance(idx, int) else row.iloc[0]))
        if not target["symbol"]:
            target = parse_rank_target(" ".join(str(item) for item in row.tolist()))
        if not target["symbol"]:
            continue
        change = parse_rank_change(_rank_change_value(row))
        item = {**target, "rank": current_rank, "rank_change": change}
        if current_rank <= top_n:
            rows.append(item)
        previous_rank = current_rank
        if change > 0:
            previous_rank = current_rank + change
        elif change < 0:
            previous_rank = current_rank + change
        if 1 <= previous_rank <= top_n:
            previous_top.append({**item, "previous_rank": previous_rank})
        if current_rank >= top_n and len(previous_top) >= top_n:
            break
        current_rank += 1

    current_keys = {_target_key(row) for row in rows}
    previous_keys = {_target_key(row) for row in previous_top}
    new_entries = [row for row in rows if _target_key(row) not in previous_keys]
    exits = [row for row in previous_top if _target_key(row) not in current_keys]
    ranking = [f"{row['name']}:{row['symbol']}" for row in rows]
    weak_statuses = {"上涨趋缓", "下跌趋势", "由涨转跌"}
    return {
        "ranking": ranking,
        "ranking_rows": rows,
        "new_entries": new_entries,
        "exits": exits,
        "smash_signals": [row for row in rows if "砸" in row["raw"] and _target_key(row) not in {_target_key(item) for item in new_entries}],
        "trend_status": [{"target": f"{row['name']}:{row['symbol']}", "status": row["status"]} for row in rows],
        "trend_reduced_entries": [row for row in new_entries if row.get("status") in weak_statuses],
        "log": f"解析外部排名 {len(rows)} 条；新入 {len(new_entries)}；退出 {len(exits)}；抢砸 {sum(1 for row in rows if '砸' in row['raw'])}",
    }


def red_green_decision(frame: pd.DataFrame, symbol: str, up_threshold: float = 0.25, down_threshold: float = 0.85) -> dict[str, Any]:
    normalized = normalize_etf_symbol(symbol)
    if frame is None or frame.empty:
        return {"symbol": normalized, "action": "hold", "reasons": ["暂无红绿灯文件"], "raw_row": {}}
    work = frame.copy()
    symbol_cols = [col for col in work.columns if str(col).lower() in {"symbol", "ts_code", "代码", "证券代码"}]
    if symbol_cols:
        matched = work.loc[work[symbol_cols[0]].astype(str).map(normalize_etf_symbol) == normalized]
        return _red_green_from_long_rows(matched, normalized, up_threshold, down_threshold)
    matched_rows = _match_wide_red_green_rows(work, normalized)
    if matched_rows.empty:
        return {"symbol": normalized, "action": "hold", "reasons": ["红绿灯文件无对应 ETF"], "raw_row": {}}
    row = matched_rows.iloc[-1]
    values = _numeric_values_from_row(row)
    if values.empty:
        return {"symbol": normalized, "action": "hold", "reasons": ["红绿灯值不可解析"], "raw_row": _raw_row(row)}
    current = float(values.iloc[0])
    prev = float(values.iloc[1]) if len(values) >= 2 else current
    prev2 = float(values.iloc[2]) if len(values) >= 3 else prev
    text = _row_text(row)
    return _red_green_action(normalized, current, prev, prev2, text, _raw_row(row), up_threshold, down_threshold)


def _red_green_from_long_rows(
    work: pd.DataFrame,
    normalized: str,
    up_threshold: float,
    down_threshold: float,
) -> dict[str, Any]:
    if work.empty:
        return {"symbol": normalized, "action": "hold", "reasons": ["红绿灯文件无对应 ETF"], "raw_row": {}}
    value_col = next((col for col in work.columns if str(col) in {"红绿灯", "红绿灯值", "signal", "value"}), work.columns[-1])
    values = pd.Series([_numeric_head(value) for value in work[value_col].tolist()]).dropna()
    if values.empty:
        return {"symbol": normalized, "action": "hold", "reasons": ["红绿灯值不可解析"], "raw_row": work.iloc[-1].to_dict()}
    current = float(values.iloc[-1])
    prev = float(values.iloc[-2]) if len(values) >= 2 else current
    prev2 = float(values.iloc[-3]) if len(values) >= 3 else prev
    text = _row_text(work.iloc[-1])
    return _red_green_action(normalized, current, prev, prev2, text, work.iloc[-1].to_dict(), up_threshold, down_threshold)


def _red_green_action(
    normalized: str,
    current: float,
    prev: float,
    prev2: float,
    text: str,
    raw_row: dict[str, Any],
    up_threshold: float,
    down_threshold: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    action = "hold"
    if prev <= up_threshold < current:
        action = "buy"
        reasons.append("红绿灯上穿通行阈值")
    if "抄" in text:
        action = "buy"
        reasons.append("文本包含抄")
    if current > 0.5 and up_threshold < prev <= 0.30 and up_threshold < prev2 <= 0.30:
        action = "buy"
        reasons.append("前两日低位蓄势后站上 0.5")
    if current > down_threshold and prev <= down_threshold:
        action = "buy"
        reasons.append("上穿高位阈值，提示补买")
    if prev >= down_threshold > current:
        action = "sell"
        reasons.append("红绿灯跌破高位阈值")
    if "砸" in text:
        action = "sell"
        reasons.append("文本包含砸")
    if current < 0.5 and 0.80 < prev <= down_threshold and 0.80 < prev2 <= down_threshold:
        action = "sell"
        reasons.append("前两日高位转弱后跌破 0.5")
    if current < up_threshold and prev >= up_threshold:
        action = "sell"
        reasons.append("跌破通行阈值")
    raw = dict(raw_row)
    raw.update({"current": current, "previous": prev, "previous_2": prev2})
    return {"symbol": normalized, "action": action, "reasons": reasons or ["无触发"], "raw_row": raw}


def _read_optional_csv(path: Path) -> pd.DataFrame:
    if not path or str(path) == "." or not path.exists():
        return pd.DataFrame()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding, index_col=0)
        except UnicodeDecodeError:
            continue
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _configured_signal_path(value: Any, base_dir: Path, default_name: str) -> Path:
    text = str(value or "").strip()
    return Path(text) if text else base_dir / default_name


def _rank_change_value(row: pd.Series) -> Any:
    for column in ("排名变化", "rank_change", "change"):
        if column in row.index:
            return row.get(column)
    return row.iloc[0] if len(row) else ""


def _resolve_signal_path(path: Path, stem: str) -> Path:
    if path.exists():
        return path
    parent = path.parent
    if not parent.exists():
        return path
    candidates = sorted(
        [item for item in parent.glob("*.csv") if stem in item.stem],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else path


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "是", "启用"}


def _match_wide_red_green_rows(frame: pd.DataFrame, normalized: str) -> pd.DataFrame:
    code = normalized[:6]
    symbol_texts = {normalized, code}
    mask = []
    for idx, row in frame.iterrows():
        text = f"{idx} " + " ".join(str(item) for item in row.tolist())
        mask.append(any(token and token in text for token in symbol_texts))
    return frame.loc[mask]


def _numeric_head(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split("|", 1)[0].strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _numeric_values_from_row(row: pd.Series) -> pd.Series:
    values = [_numeric_head(value) for value in row.tolist()]
    return pd.Series([value for value in values if value is not None])


def _row_text(row: pd.Series) -> str:
    return f"{row.name} " + " ".join(str(item) for item in row.tolist())


def _raw_row(row: pd.Series) -> dict[str, Any]:
    raw = row.to_dict()
    raw["__index__"] = row.name
    return raw


def _ftp_is_dir(ftp: FTP, name: str) -> bool:
    try:
        current = ftp.pwd()
    except Exception:
        current = ""
    try:
        ftp.cwd(name)
        if current:
            ftp.cwd(current)
        else:
            ftp.cwd("..")
        return True
    except Exception:
        try:
            if current:
                ftp.cwd(current)
        except Exception:
            pass
        return False


def _target_key(row: dict[str, Any]) -> str:
    return normalize_etf_symbol(str(row.get("symbol") or ""))
