"""ETF OHLCV data adapters."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


STANDARD_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def normalize_etf_symbol(symbol: str) -> str:
    """Normalize ETF symbols to Tushare-like suffix form, e.g. 515880.SH."""
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    if text.startswith("SH") and len(text) == 8:
        return f"{text[2:]}.SH"
    if text.startswith("SZ") and len(text) == 8:
        return f"{text[2:]}.SZ"
    if "." in text:
        code, market = text.split(".", 1)
        return f"{code.zfill(6)}.{market[:2].upper()}"
    code = "".join(ch for ch in text if ch.isdigit())
    if len(code) != 6:
        return text
    market = "SH" if code.startswith(("51", "52", "58")) else "SZ"
    return f"{code}.{market}"


def sina_etf_symbol(symbol: str) -> str:
    normalized = normalize_etf_symbol(symbol)
    if normalized.endswith(".SH"):
        return "sh" + normalized[:6]
    if normalized.endswith(".SZ"):
        return "sz" + normalized[:6]
    raise ValueError(f"无法转换为新浪 ETF 代码: {symbol}")


def _standardize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    work = frame.copy()
    column_map = {
        "date": "Date",
        "trade_date": "Date",
        "day": "Date",
        "开盘价": "Open",
        "最高价": "High",
        "最低价": "Low",
        "收盘价": "Close",
        "成交量": "Volume",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "vol": "Volume",
        "成交额": "Amount",
        "amount": "Amount",
    }
    work = work.rename(columns={key: value for key, value in column_map.items() if key in work.columns})
    if "Date" in work.columns:
        dates = pd.to_datetime(work["Date"], errors="coerce")
    else:
        dates = pd.to_datetime(work.index, errors="coerce")
    work.index = dates
    work = work.loc[work.index.notna()].sort_index()
    for column in STANDARD_COLUMNS:
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce")
    columns = STANDARD_COLUMNS.copy()
    if "Amount" in work.columns:
        work["Amount"] = pd.to_numeric(work["Amount"], errors="coerce")
        columns.append("Amount")
    return work[columns].dropna(subset=["Open", "High", "Low", "Close"])


def _to_cache_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.reset_index()
    work = work.rename(columns={work.columns[0]: "date"})
    work["date"] = pd.to_datetime(work["date"]).dt.strftime("%Y%m%d")
    renamed = work.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume", "Amount": "amount"})
    columns = ["date", "open", "high", "low", "close", "volume"]
    if "amount" in renamed.columns:
        columns.append("amount")
    return renamed[columns]


class EtfDataProvider:
    """Load ETF daily bars from local cache first, then Sina daily K data."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        data_config = config.get("data", {})
        base_cache = Path(data_config.get("cache_dir", "data/cache"))
        etf_config = config.get("etf_strategy", {})
        self.cache_dir = Path(etf_config.get("cache_dir") or base_cache / "etf")
        self.legacy_cache_dir = base_cache
        self.daily_datalen = int(etf_config.get("daily_datalen", 1500) or 1500)
        self.min_history_bars = int(etf_config.get("min_history_bars", 0) or 0)
        self.adjust = str(etf_config.get("adjust") or "none").strip().lower()

    def cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{normalize_etf_symbol(symbol)}.csv"

    def _read_cache(self, symbol: str) -> pd.DataFrame:
        normalized = normalize_etf_symbol(symbol)
        candidates = [self.cache_path(normalized), self.legacy_cache_dir / f"{normalized}.csv"]
        for path in candidates:
            if not path.exists():
                continue
            frame = pd.read_csv(path, dtype={"date": str, "trade_date": str})
            standardized = _standardize_ohlcv(frame)
            if not standardized.empty:
                return standardized
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    def _fetch_sina_kline(self, symbol: str, scale: int = 240, datalen: int = 1500) -> pd.DataFrame:
        params = {
            "symbol": sina_etf_symbol(symbol),
            "scale": str(int(scale)),
            "ma": "no",
            "datalen": str(int(datalen)),
        }
        url = (
            "https://quotes.sina.cn/cn/api/jsonp.php/var%20_etf_k=/"
            "CN_MarketDataService.getKLineData?"
            + urlencode(params)
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urlopen(request, timeout=15).read().decode("utf-8", "ignore")
        start = raw.find("([")
        end = raw.rfind(")")
        if start < 0 or end <= start:
            raise ValueError("新浪 ETF 日线返回格式无法解析")
        data = json.loads(raw[start + 1 : end])
        if data is None:
            raise ValueError("新浪 ETF 日线返回空数据")
        return _standardize_ohlcv(pd.DataFrame(data))

    def _fetch_sina_daily(self, symbol: str, datalen: int = 1500) -> pd.DataFrame:
        return self._fetch_sina_kline(symbol, scale=240, datalen=datalen)

    def _fetch_tushare_daily(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        token = str((self.config.get("tushare") or {}).get("token") or "").strip()
        if not token:
            raise ValueError("缺少 tushare.token，无法拉取 ETF 日线")
        import tushare as ts

        pro = ts.pro_api(token)
        end_date = _compact_date(end) if end else datetime.now().strftime("%Y%m%d")
        start_date = _compact_date(start) if start else "19900101"
        frame = pro.query(
            "fund_daily",
            ts_code=normalize_etf_symbol(symbol),
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        if self.adjust in {"qfq", "front", "forward"}:
            frame = self._apply_tushare_qfq(pro, normalize_etf_symbol(symbol), frame, start_date=start_date, end_date=end_date)
        standardized = _standardize_ohlcv(frame)
        if "Amount" in standardized.columns:
            standardized["Amount"] = standardized["Amount"] * 1000
        return standardized

    def _apply_tushare_qfq(
        self,
        pro: Any,
        symbol: str,
        frame: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        if frame is None or frame.empty or "trade_date" not in frame.columns:
            return frame
        try:
            factors = pro.query(
                "fund_adj",
                ts_code=symbol,
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,adj_factor",
            )
        except Exception:
            return frame
        if factors is None or factors.empty or "adj_factor" not in factors.columns:
            return frame
        work = frame.copy()
        factors = factors[["trade_date", "adj_factor"]].copy()
        factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
        work = work.merge(factors, on="trade_date", how="left")
        latest_factor = work.sort_values("trade_date")["adj_factor"].dropna().iloc[-1] if work["adj_factor"].notna().any() else None
        if not latest_factor or pd.isna(latest_factor):
            return frame
        ratio = pd.to_numeric(work["adj_factor"], errors="coerce") / float(latest_factor)
        for column in ("open", "high", "low", "close"):
            if column in work.columns:
                work[column] = pd.to_numeric(work[column], errors="coerce") * ratio
        return work.drop(columns=["adj_factor"])

    def get_daily_bars(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        force: bool = False,
        save_cache: bool = True,
    ) -> pd.DataFrame:
        """Return standard OHLCV with DatetimeIndex and Open/High/Low/Close/Volume."""
        normalized = normalize_etf_symbol(symbol)
        frame = pd.DataFrame(columns=STANDARD_COLUMNS) if force else self._read_cache(normalized)
        needs_long_history = bool(self.min_history_bars and len(frame) < self.min_history_bars)
        if frame.empty or needs_long_history:
            try:
                frame = self._fetch_tushare_daily(normalized, start=None, end=end)
            except Exception:
                frame = self._fetch_sina_daily(normalized, datalen=self.daily_datalen)
            if save_cache and not frame.empty:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                _to_cache_frame(frame).to_csv(self.cache_path(normalized), index=False)
        if start:
            frame = frame.loc[frame.index >= pd.to_datetime(start)]
        if end:
            frame = frame.loc[frame.index <= pd.to_datetime(end)]
        return frame.copy()

    def get_minute_bars(
        self,
        symbol: str,
        period: str = "5m",
        datalen: int = 512,
    ) -> pd.DataFrame:
        """Return ETF minute OHLCV from Sina using standard Open/High/Low/Close/Volume.

        Supported periods: 1m, 5m, 15m, 30m, 60m.  Minute bars are not cached by
        default because they are used for live/research inspection rather than
        the daily dashboard summary.
        """
        scale_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
        scale = scale_map.get(str(period).lower())
        if scale is None:
            raise ValueError(f"不支持的 ETF 分钟周期: {period}")
        return self._fetch_sina_kline(symbol, scale=scale, datalen=datalen)


def _compact_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text.replace("-", "")[:8]
