#!/usr/bin/env python3
"""Verify the nightly deterministic market-structure archive postconditions.

This script is intentionally read-only.  It derives the archive date from the
latest market-structure JSON (the trading-data date, not the calendar run date)
and exits non-zero unless the deterministic report and fact archive are valid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config


V2_SCHEMA = "market_structure_v2"
REQUIRED_ARTIFACT_KEYS = (
    "report",
    "json",
)
SUCCESS_ARTIFACT_STATUSES = {"written", "preserved", "preserved_links_updated"}


class DailyArchiveVerificationError(RuntimeError):
    """Raised when a nightly archive is incomplete or internally inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise DailyArchiveVerificationError(f"{label}不存在: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DailyArchiveVerificationError(f"{label}无法读取: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DailyArchiveVerificationError(f"{label}顶层必须是对象: {path}")
    return value


def _artifact_path(raw_path: object, archive_dir: Path) -> Path:
    path = Path(str(raw_path or ""))
    return path if path.is_absolute() else archive_dir / path


def _archive_date_token(report_date: str) -> str:
    value = str(report_date or "").strip()
    for candidate, format_string in (
        (value[:10], "%Y-%m-%d"),
        (value[:8], "%Y%m%d"),
    ):
        try:
            return datetime.strptime(candidate, format_string).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value.replace("/", "-")


def verify_daily_market_structure_archive(
    config: dict[str, Any],
    *,
    symbol: str = "000001.SH",
    horizon: int = 5,
) -> dict[str, Any]:
    """Validate the latest data-dated deterministic archive without writing."""
    symbol = symbol.upper()
    output = config.get("output") or {}
    statistics_dir = Path(output.get("statistics_dir", "output/statistics"))
    reports_dir = Path(output.get("reports_dir", "output/reports"))
    structure_path = statistics_dir / "index_forecast" / f"market_structure_{symbol}.json"
    structure = _load_json(structure_path, "市场结构JSON")

    raw_report_date = str(structure.get("date") or "").strip()
    if not raw_report_date:
        raise DailyArchiveVerificationError(f"市场结构JSON缺少数据日期: {structure_path}")
    report_date = _archive_date_token(raw_report_date)
    schema_version = str(structure.get("schema_version") or "")
    archive_root = reports_dir / "index_forecast" / "archive"
    if schema_version == V2_SCHEMA:
        archive_root = archive_root / V2_SCHEMA
    archive_dir = archive_root / raw_report_date.replace("/", "-")
    prefix = f"{symbol}_h{int(horizon)}"
    if schema_version == V2_SCHEMA:
        prefix = f"{prefix}_{report_date}"
    manifest_path = archive_dir / f"{prefix}_archive_manifest.json"
    manifest = _load_json(manifest_path, "市场结构归档清单")

    errors: list[str] = []
    if _archive_date_token(str(manifest.get("report_date") or "")) != report_date:
        errors.append(
            f"清单日期{manifest.get('report_date')!r}与市场数据日期{report_date!r}不一致"
        )
    if str(manifest.get("symbol") or "").upper() != symbol:
        errors.append(f"清单标的不是{symbol}")
    try:
        manifest_horizon = int(manifest.get("horizon"))
    except (TypeError, ValueError):
        manifest_horizon = None
    if manifest_horizon != int(horizon):
        errors.append(f"清单周期不是h{int(horizon)}")

    artifact_rows = manifest.get("artifacts") or []
    records = {
        str(item.get("key")): item
        for item in artifact_rows
        if isinstance(item, dict) and item.get("key")
    }
    expected_names = {
        "report": f"{prefix}_market_structure.html",
        "json": f"{prefix}_market_structure.json",
    }
    verified_paths: dict[str, str] = {}
    for key in REQUIRED_ARTIFACT_KEYS:
        record = records.get(key)
        if record is None:
            errors.append(f"清单缺少归档项: {key}")
            continue
        status = str(record.get("status") or "")
        if status not in SUCCESS_ARTIFACT_STATUSES:
            errors.append(f"归档项{key}状态异常: {status or 'missing'}")
            continue
        path = _artifact_path(record.get("path"), archive_dir)
        if path.parent.resolve() != archive_dir.resolve():
            errors.append(f"归档项{key}不在当日归档目录内: {path}")
            continue
        if path.name != expected_names[key]:
            errors.append(
                f"归档项{key}未使用数据日期前缀，期望{expected_names[key]}，实际{path.name}"
            )
            continue
        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"归档项{key}不存在或为空: {path}")
            continue
        expected_hash = str(record.get("sha256") or "")
        actual_hash = _sha256(path)
        if not expected_hash or actual_hash != expected_hash:
            errors.append(f"归档项{key}的SHA256与清单不一致: {path}")
            continue
        verified_paths[key] = str(path)

    if errors:
        detail = "；".join(errors)
        raise DailyArchiveVerificationError(
            f"每日市场结构归档验收失败（数据日期 {report_date}）: {detail}"
        )
    return {
        "report_date": report_date,
        "schema_version": schema_version or None,
        "manifest": str(manifest_path),
        "artifacts": verified_paths,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验收每日市场结构确定性归档")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--symbol", default="000001.SH")
    parser.add_argument("--horizon", type=int, default=5)
    return parser


def main() -> int:
    args = _parser().parse_args()
    config_path = Path(args.config)
    if not config_path.is_file():
        raise DailyArchiveVerificationError(f"配置文件不存在: {config_path}")
    config = load_project_config(config_path)
    result = verify_daily_market_structure_archive(
        config,
        symbol=args.symbol,
        horizon=args.horizon,
    )
    print(
        "每日市场结构归档验收通过: "
        f"数据日期={result['report_date']}；清单={result['manifest']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DailyArchiveVerificationError as exc:
        print(str(exc))
        raise SystemExit(1) from None
