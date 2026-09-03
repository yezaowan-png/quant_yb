"""ETF strategy configuration helpers."""

from __future__ import annotations

import os
from typing import Any


DEFAULT_FTP_CONFIG = {
    "enabled": False,
    "auto_download": False,
    "server": "101.132.65.156",
    "port": 21,
    "username": "QuantTraderYX",
    "password": "",
    "encoding": "GB2312",
    "timeout": 30,
    "remote_root": "/每日选股结果分享",
    "red_green_remote_dir": "ETF红绿灯信号",
    "rank_emotion_remote_dir": "红绿灯排名与情绪",
}

FTP_ENV_KEYS = {
    "server": "QUANTYB_ETF_FTP_SERVER",
    "username": "QUANTYB_ETF_FTP_USERNAME",
    "password": "QUANTYB_ETF_FTP_PASSWORD",
}


def resolve_ftp_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve FTP settings with local environment variables taking precedence."""
    ftp = dict(DEFAULT_FTP_CONFIG)
    ftp.update(overrides or {})
    for key, env_name in FTP_ENV_KEYS.items():
        value = os.getenv(env_name, "").strip()
        if value:
            ftp[key] = value
    return ftp


def etf_strategy_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return ETF strategy section with safe defaults."""
    section = dict(config.get("etf_strategy", {}) or {})
    data_config = config.get("data", {}) or {}
    section.setdefault("rank_top_n", 10)
    section.setdefault("timing", {})
    section.setdefault("rotation", {})
    section.setdefault("red_green_path", "")
    section.setdefault("rank_emotion_path", "")
    section.setdefault("external_signal_dir", f"{data_config.get('meta_dir', 'data/meta')}/etf_external_signals")
    section["ftp"] = resolve_ftp_config(section.get("ftp", {}) or {})
    section.setdefault("buy_amount", 1_000_000)
    section.setdefault("smash_sell_pct", 10)
    section.setdefault("blacklist_amounts", {"[海]标普油气ETF": 1000, "[海]中韩半导体ETF": 1000, "酒ETF[贵州茅台]": 1000})
    section.setdefault("trend_position_pct", {"上涨趋缓": 20, "下跌趋势": 30, "由涨转跌": 30})
    return section
