"""Index overview commands."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Optional

import click
import pandas as pd

from analysis.market_breadth import (
    breadth_indicator_payload,
    build_market_breadth,
    load_latest_index_member_symbols,
    load_stock_basic_symbols_by_market,
)
from analysis.index_forecast import (
    add_forecast_labels,
    build_index_forecast_indicators,
    build_rule_forecast,
    evaluate_forecast,
    forecast_paths,
    save_forecast_outputs,
)
from analysis.index_forecast_diagnostics import (
    _ensure_forecast_files,
    build_diagnostics,
    diagnostic_paths,
    load_diagnostic_frames,
    save_diagnostics,
)
from analysis.index_market_structure import (
    ALL_A_INDEX_NAME,
    ALL_A_INDEX_SYMBOL,
    DEFAULT_THS_STYLE_PROXIES,
    attach_market_structure_columns,
    build_market_structure,
    load_required_index_frames,
    load_stock_market_panels,
    save_market_structure_outputs,
)
from analysis.index_market_llm import llm_summary_paths, write_llm_summary_artifacts
from analysis.market_structure_v2 import load_index_member_frames
from analysis.market_environment_labels import (
    ENVIRONMENT_HORIZONS,
    build_current_cross_section_features,
    build_market_environment_targets,
    load_strategy_daily_returns,
)
from cli.common import load_config as _load_config
from data.downloader import DataDownloader, default_start, today_str
from visual.index_forecast_report import generate_index_forecast_report
from visual.market_structure_brief import generate_market_structure_brief
from visual.components import relative_href
from visual.index_report import generate_index_report
from visual.market_report import generate_market_report


DEFAULT_INDEX_SYMBOL = "000001.SH"
DEFAULT_INDEX_NAME = "上证指数"
DEFAULT_MEMBER_INDEX_CODES = {
    "上证50": "000016.SH",
    "沪深300": "399300.SZ",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
    "中证2000": "932000.CSI",
    "创业板": "399006.SZ",
    "科创50": "000688.SH",
    "深证成指": "399001.SZ",
}
OPTIONAL_MEMBER_INDEX_CODES = {
    "创业板指": "399006.SZ",
}


MARKET_STRUCTURE_V2_SCHEMA = "market_structure_v2"
FROZEN_MARKET_STRUCTURE_HISTORY_DIR = "_history_400_2026-07-14"

def _configured_indexes(config: dict) -> list[dict]:
    indexes = config.get("index_overview", {}).get("indexes", [])
    if indexes:
        return indexes
    return [{"symbol": DEFAULT_INDEX_SYMBOL, "name": DEFAULT_INDEX_NAME, "market": "SH"}]


def _index_name(config: dict, symbol: str) -> str:
    for item in _configured_indexes(config):
        if item.get("symbol", "").upper() == symbol.upper():
            return item.get("name") or symbol
    if symbol.upper() == DEFAULT_INDEX_SYMBOL:
        return DEFAULT_INDEX_NAME
    return symbol


def _default_symbol(config: dict) -> str:
    return config.get("index_overview", {}).get("default_symbol", DEFAULT_INDEX_SYMBOL)


def _ths_config(config: dict) -> dict:
    return config.get("ths_indices", {}) or {}


def _ths_section_file_path(config: dict, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    return meta_dir / path


def _read_ths_symbol_file(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return set()
    if frame.empty:
        return set()
    symbol_column = next((column for column in ("ts_code", "symbol", "代码") if column in frame.columns), frame.columns[0])
    return {
        str(value).strip().upper()
        for value in frame[symbol_column].tolist()
        if str(value).strip().upper().endswith(".TI")
    }


def _apply_ths_section_symbol_files(symbols: list[str], config: dict, section_cfg: dict) -> list[str]:
    include_symbols = _read_ths_symbol_file(_ths_section_file_path(config, section_cfg.get("include_path")))
    exclude_symbols = _read_ths_symbol_file(_ths_section_file_path(config, section_cfg.get("exclude_path")))
    selected = [symbol for symbol in symbols if not include_symbols or symbol in include_symbols]
    if exclude_symbols:
        selected = [symbol for symbol in selected if symbol not in exclude_symbols]
    return selected


def _style_proxy_config(config: dict) -> dict:
    return (_ths_config(config).get("style_proxies") or {})


def _style_proxy_symbols(config: dict) -> list[str]:
    symbols: list[str] = []
    proxy_config = _style_proxy_config(config)
    for name, default in DEFAULT_THS_STYLE_PROXIES.items():
        item = dict(default)
        override = proxy_config.get(name) or proxy_config.get(default["key"]) or {}
        if isinstance(override, dict):
            item.update({key: value for key, value in override.items() if value is not None})
        symbols.extend(str(symbol).upper() for symbol in item.get("symbols") or ())
    return list(dict.fromkeys(symbol for symbol in symbols if symbol.endswith(".TI")))


def _select_ths_industry_symbols(index_list: pd.DataFrame, config: dict) -> list[str]:
    return _select_ths_symbols(index_list, config, "industries", default_type="I")


def _select_ths_concept_symbols(index_list: pd.DataFrame, config: dict) -> list[str]:
    return _select_ths_symbols(index_list, config, "concepts", default_type="N")


def _select_ths_symbols(index_list: pd.DataFrame, config: dict, section: str, *, default_type: str) -> list[str]:
    if index_list is None or index_list.empty:
        return []
    ths_cfg = _ths_config(config)
    section_cfg = ths_cfg.get(section) or {}
    exchange = str(section_cfg.get("exchange", "A"))
    index_type = str(section_cfg.get("type", default_type))
    min_count = section_cfg.get("min_count", 1)
    frame = index_list.copy()
    mask = pd.Series(True, index=frame.index)
    if "exchange" in frame.columns:
        mask &= frame["exchange"].astype(str).str.upper() == exchange.upper()
    if "type" in frame.columns:
        mask &= frame["type"].astype(str).str.upper() == index_type.upper()
    if "count" in frame.columns and min_count is not None:
        mask &= pd.to_numeric(frame["count"], errors="coerce").fillna(0) >= float(min_count)
    selected = frame.loc[mask, "ts_code"].astype(str).str.upper().tolist() if "ts_code" in frame.columns else []
    selected = _apply_ths_section_symbol_files(selected, config, section_cfg)
    limit = section_cfg.get("limit")
    if limit:
        selected = selected[: int(limit)]
    return list(dict.fromkeys(symbol for symbol in selected if symbol.endswith(".TI")))


def _ths_index_names(index_list: pd.DataFrame | None) -> dict[str, str]:
    if index_list is None or index_list.empty or not {"ts_code", "name"}.issubset(index_list.columns):
        return {}
    return {
        str(row["ts_code"]).upper(): str(row["name"])
        for _, row in index_list.dropna(subset=["ts_code"]).iterrows()
    }


def _load_ths_frames_for_structure(config: dict) -> tuple[dict[str, pd.DataFrame], dict[str, str], set[str]]:
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache")) / "index"
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    index_list_path = meta_dir / "ths_indices.csv"
    index_list = pd.read_csv(index_list_path, dtype={"ts_code": str}) if index_list_path.exists() else None
    names = _ths_index_names(index_list)
    industry_symbols = set(_select_ths_industry_symbols(index_list, config))
    symbols = set(_style_proxy_symbols(config)) | industry_symbols
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        path = cache_dir / f"{symbol}.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"date": str, "ts_code": str})
        except Exception:
            continue
        if frame.empty:
            continue
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frames[symbol] = frame
    return frames, names, industry_symbols


def _selected_indexes(config: dict, symbol: Optional[str], all_indexes: bool) -> list[dict]:
    if all_indexes:
        return _configured_indexes(config)
    selected_symbol = (symbol or _default_symbol(config)).upper()
    return [{"symbol": selected_symbol, "name": _index_name(config, selected_symbol)}]


def _download_index_frames(
    dl: DataDownloader,
    config: dict,
    indexes: list[dict],
    start: str,
    end: str,
    force: bool,
    skip_failures: bool = False,
) -> list[tuple[str, str, pd.DataFrame]]:
    frames: list[tuple[str, str, pd.DataFrame]] = []
    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        click.echo(f"\n指数: {sym} ({name})")
        try:
            df = dl.download_index(symbol=sym, start=start, end=end, force=force)
        except Exception as exc:
            if not skip_failures:
                raise
            click.secho(f"  警告: 跳过指数 {sym} ({name}): {exc}", fg="yellow")
            continue
        frames.append((sym, name, df))

    if not frames:
        raise click.ClickException("没有可用指数数据")
    return frames


def _output_path(config: dict, symbol: str, output: Optional[str], all_indexes: bool = False) -> Path:
    if output:
        path = Path(output)
        return path / f"{symbol}_overview.html" if all_indexes else path
    reports_dir = Path(config["output"]["reports_dir"]) / "index"
    return reports_dir / f"{symbol}_overview.html"


def _market_output_path(config: dict, output: Optional[str]) -> Path:
    return Path(output) if output else Path(config["output"]["reports_dir"]) / "market_overview.html"


def _forecast_output_path(config: dict, symbol: str, horizon: int, output: Optional[str], model: str = "rule_v1") -> Path:
    if output:
        return Path(output)
    reports_dir = Path(config["output"]["reports_dir"]) / "index_forecast"
    suffix = "" if (model or "rule_v1").lower() == "rule_v1" else f"_{(model or '').lower()}"
    return reports_dir / f"{symbol.upper()}_h{int(horizon)}{suffix}.html"


def _market_structure_alias_path(config: dict, symbol: str) -> Path:
    return Path(config["output"]["reports_dir"]) / "index_forecast" / f"{symbol.upper()}_market_structure.html"


def _market_structure_brief_path(config: dict, symbol: str) -> Path:
    return Path(config["output"]["reports_dir"]) / "index_forecast" / f"{symbol.upper()}_market_structure_brief.html"


def _market_structure_json_path(config: dict, symbol: str) -> Path:
    return (
        Path(config["output"].get("statistics_dir", "output/statistics"))
        / "index_forecast"
        / f"market_structure_{symbol.upper()}.json"
    )


def _assert_market_structure_archive_target(path: Path) -> None:
    """Protect the completed 400-day audit tree from every daily write path."""
    resolved = path.expanduser().resolve()
    if FROZEN_MARKET_STRUCTURE_HISTORY_DIR in resolved.parts:
        raise RuntimeError(
            f"已冻结的400日市场结构审计目录禁止写入: {resolved}"
        )


def _market_structure_archive_dir(
    config: dict,
    report_date: str,
    schema_version: object | None = None,
) -> Path:
    safe_date = str(report_date or "unknown").replace("/", "-")
    root = Path(config["output"]["reports_dir"]) / "index_forecast" / "archive"
    if str(schema_version or "") == MARKET_STRUCTURE_V2_SCHEMA:
        root = root / MARKET_STRUCTURE_V2_SCHEMA
    path = root / safe_date
    _assert_market_structure_archive_target(path)
    return path


def _market_structure_archive_date_token(report_date: str) -> str:
    parsed = pd.to_datetime(report_date, errors="coerce")
    if pd.notna(parsed):
        return pd.Timestamp(parsed).strftime("%Y-%m-%d")
    return str(report_date or "unknown").replace("/", "-")


def _market_structure_archive_prefix(
    symbol: str,
    horizon: int,
    report_date: str,
    schema_version: object | None,
) -> str:
    prefix = f"{symbol.upper()}_h{int(horizon)}"
    if str(schema_version or "") == MARKET_STRUCTURE_V2_SCHEMA:
        prefix = f"{prefix}_{_market_structure_archive_date_token(report_date)}"
    return prefix


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_if_exists(src: Path, dst: Path) -> tuple[Path | None, str]:
    """Copy once and preserve an existing dated artifact."""
    _assert_market_structure_archive_target(dst)
    if dst.exists():
        return dst, "preserved"
    if not src.exists():
        return None, "source_missing"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst, "written"


def _archive_artifact_record(
    *,
    key: str,
    source: Path | None,
    destination: Path,
    status: str,
) -> dict[str, object]:
    sha256: str | None = None
    size: int | None = None
    if destination.exists():
        sha256, size = _file_digest(destination)
    return {
        "key": key,
        "source": str(source) if source is not None else None,
        "path": str(destination),
        "sha256": sha256,
        "bytes": size,
        "status": status,
    }


def _write_archive_manifest(
    archive_dir: Path,
    *,
    prefix: str,
    report_date: str,
    symbol: str,
    horizon: int,
    artifacts: list[dict[str, object]],
    llm_call_status: str,
    llm_error_type: str | None,
    structure_metadata: dict[str, object] | None = None,
) -> Path:
    """Append the latest archive attempt while retaining prior attempt records."""
    _assert_market_structure_archive_target(archive_dir)
    manifest_path = archive_dir / f"{prefix}_archive_manifest.json"
    previous: dict[str, object] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}
    attempts = previous.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    metadata = structure_metadata or {}
    is_v2 = str(metadata.get("schema_version") or "") == MARKET_STRUCTURE_V2_SCHEMA
    snapshot_metadata = {
        "algorithm_version": metadata.get("algorithm_version"),
        "config_hash": metadata.get("config_hash"),
        "data_hash": metadata.get("data_hash"),
        "source_freshness": metadata.get("source_freshness") or {},
        "point_in_time": metadata.get("point_in_time") or {},
    }
    attempt = {
        "archived_at_utc": datetime.now(timezone.utc).isoformat(),
        "llm_call": {
            "status": llm_call_status,
            "succeeded": llm_call_status == "succeeded",
            "error_type": llm_error_type,
        },
        "artifacts": artifacts,
    }
    if is_v2:
        attempt["structure_metadata"] = snapshot_metadata
    attempts.append(attempt)
    manifest = {
        "schema_version": MARKET_STRUCTURE_V2_SCHEMA if is_v2 else 1,
        "report_date": str(report_date),
        "symbol": symbol.upper(),
        "horizon": int(horizon),
        "archive_policy": "preserve",
        "llm_call": attempt["llm_call"],
        "artifacts": artifacts,
        "attempts": attempts,
    }
    if is_v2:
        manifest.update(
            {
                key: previous.get(key, value)
                for key, value in snapshot_metadata.items()
            }
        )
    archive_dir.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest_path


def _rewrite_archived_report_links(
    link_source_report: Path,
    archived_report: Path,
    link_targets: list[tuple[Path, Path]],
) -> bool:
    """Make a copied report resolve LLM links inside its dated archive.

    ``link_source_report`` remains the original generated report when patching
    the copied alias.  Alias HTML is copied byte for byte, so its href values
    were calculated relative to that original report even when ``--output``
    places it outside the configured report directory.

    On a same-day retry, an earlier LLM failure may have left the preserved
    report without action links.  Only the current ``top-actions`` link block
    is then added; the archived market snapshot body remains untouched.
    """
    if not archived_report.exists() or not link_targets:
        return False
    try:
        source_html = link_source_report.read_text(encoding="utf-8")
    except OSError:
        source_html = ""
    html = archived_report.read_text(encoding="utf-8")
    updated = html
    source_actions = source_html
    for live_source, archive_destination in link_targets:
        local_href = archive_destination.name
        old_hrefs = {
            relative_href(link_source_report, live_source),
            relative_href(link_source_report, archive_destination),
        }
        for old_href in old_hrefs:
            updated = updated.replace(
                f"href='{old_href}'",
                f"href='{local_href}'",
            )
            updated = updated.replace(
                f'href="{old_href}"',
                f'href="{local_href}"',
            )
            source_actions = source_actions.replace(
                f"href='{old_href}'",
                f"href='{local_href}'",
            )
            source_actions = source_actions.replace(
                f'href="{old_href}"',
                f'href="{local_href}"',
            )

    action_pattern = re.compile(
        r"<div\s+class=(?P<quote>['\"])top-actions(?P=quote)>.*?</div>",
        flags=re.DOTALL,
    )
    source_match = action_pattern.search(source_actions)
    archived_match = action_pattern.search(updated)
    if source_match is not None:
        source_block = source_match.group(0)
        if archived_match is not None:
            updated = (
                updated[:archived_match.start()]
                + source_block
                + updated[archived_match.end():]
            )
        else:
            sub_match = re.search(
                r"<div\s+class=(?P<quote>['\"])sub(?P=quote)>.*?</div>",
                updated,
                flags=re.DOTALL,
            )
            if sub_match is not None:
                updated = (
                    updated[:sub_match.end()]
                    + "\n          "
                    + source_block
                    + updated[sub_match.end():]
                )
    if updated != html:
        archived_report.write_text(updated, encoding="utf-8")
        return True
    return False


def _rewrite_latest_report_links(
    link_source_report: Path,
    target_report: Path,
    link_targets: list[tuple[Path, Path]],
) -> bool:
    """Point a latest/main report at immutable dated archive artifacts.

    A failed same-day LLM retry regenerates the report without ``top-actions``.
    If that date already has a successful archived summary, rebuild only the
    action block from the archive destinations.  No live/root summary content
    is read or copied by this helper.
    """
    if not target_report.exists() or not link_targets:
        return False
    html = target_report.read_text(encoding="utf-8")
    updated = html
    for live_source, archive_destination in link_targets:
        destination_href = relative_href(target_report, archive_destination)
        old_hrefs = {
            relative_href(link_source_report, live_source),
            relative_href(link_source_report, archive_destination),
        }
        for old_href in old_hrefs:
            updated = updated.replace(
                f"href='{old_href}'",
                f"href='{destination_href}'",
            )
            updated = updated.replace(
                f'href="{old_href}"',
                f'href="{destination_href}"',
            )

    available_links = {
        "summary": relative_href(target_report, archive_destination)
        for _live_source, archive_destination in link_targets
        if archive_destination.exists()
        and archive_destination.name.endswith("_llm_summary.html")
    }
    available_links.update(
        {
            "facts": relative_href(target_report, archive_destination)
            for _live_source, archive_destination in link_targets
            if archive_destination.exists()
            and archive_destination.name.endswith("_llm_input.md")
        }
    )
    if available_links.get("summary"):
        action_links = [
            (
                "primary",
                available_links["summary"],
                "查看大模型复盘总结",
            )
        ]
        if available_links.get("facts"):
            action_links.append(("", available_links["facts"], "LLM事实包"))
        action_block = '<div class="top-actions">' + "".join(
            f"<a class='{css_class}' href='{href}' target='_blank'>{label}</a>"
            for css_class, href, label in action_links
        ) + "</div>"
        action_pattern = re.compile(
            r"<div\s+class=(?P<quote>['\"])top-actions(?P=quote)>.*?</div>",
            flags=re.DOTALL,
        )
        action_match = action_pattern.search(updated)
        if action_match is not None:
            updated = (
                updated[:action_match.start()]
                + action_block
                + updated[action_match.end():]
            )
        else:
            sub_match = re.search(
                r"<div\s+class=(?P<quote>['\"])sub(?P=quote)>.*?</div>",
                updated,
                flags=re.DOTALL,
            )
            if sub_match is not None:
                updated = (
                    updated[:sub_match.end()]
                    + "\n          "
                    + action_block
                    + updated[sub_match.end():]
                )
    if updated != html:
        target_report.write_text(updated, encoding="utf-8")
        return True
    return False


def _archive_market_structure_outputs(
    config: dict,
    symbol: str,
    horizon: int,
    report_date: str,
    report_path: Path,
    alias_path: Path,
    structure_paths: dict[str, Path],
    llm_paths: object | None,
    *,
    llm_call_status: str = "not_called",
    llm_error_type: str | None = None,
    structure_metadata: dict[str, object] | None = None,
) -> dict[str, Path]:
    """Archive one trading day without overwriting an existing dated snapshot.

    Facts and prompts are deterministic outputs and remain archivable when an API
    call is skipped or fails.  Summary artifacts are admitted only when this run's
    DeepSeek call actually succeeded, so stale root-level files cannot leak into a
    later trading date.
    """
    metadata = structure_metadata or {}
    schema_version = metadata.get("schema_version")
    is_v2 = str(schema_version or "") == MARKET_STRUCTURE_V2_SCHEMA
    archive_dir = _market_structure_archive_dir(config, report_date, schema_version)
    prefix = _market_structure_archive_prefix(
        symbol,
        horizon,
        report_date,
        schema_version,
    )
    alias_prefix = (
        f"{symbol.upper()}_{_market_structure_archive_date_token(report_date)}"
        if is_v2
        else symbol.upper()
    )
    archived: dict[str, Path] = {}
    candidates: list[tuple[str, Path | None, str, bool]] = [
        ("report", report_path, f"{prefix}_market_structure.html", False),
        ("alias", alias_path, f"{alias_prefix}_market_structure.html", False),
        ("json", structure_paths.get("json"), f"{prefix}_market_structure.json", False),
        ("indices", structure_paths.get("indices"), f"{prefix}_market_structure_indices.csv", False),
        ("breadth", structure_paths.get("breadth"), f"{prefix}_market_structure_breadth.csv", False),
        ("styles", structure_paths.get("styles"), f"{prefix}_market_structure_styles.csv", False),
        ("style_history", structure_paths.get("style_history"), f"{prefix}_market_structure_style_history.csv", False),
    ]
    if is_v2:
        known_structure_keys = {key for key, *_rest in candidates}
        for key, source_path in structure_paths.items():
            if key in known_structure_keys or source_path is None:
                continue
            source = Path(source_path)
            suffix = source.suffix if source.suffix else ".csv"
            safe_key = "".join(
                character if character.isalnum() else "_"
                for character in str(key)
            ).strip("_") or "artifact"
            candidates.append(
                (
                    str(key),
                    source,
                    f"{prefix}_market_structure_{safe_key}{suffix}",
                    False,
                )
            )
    if llm_paths is not None:
        candidates.extend(
            [
                ("llm_facts", getattr(llm_paths, "facts", None), f"{prefix}_llm_input.md", False),
                ("llm_prompt", getattr(llm_paths, "prompt", None), f"{prefix}_llm_prompt.md", False),
                ("llm_summary", getattr(llm_paths, "summary", None), f"{prefix}_llm_summary.md", True),
                ("llm_summary_html", getattr(llm_paths, "html", None), f"{prefix}_llm_summary.html", True),
            ]
        )
    archived_report_link_targets = [
        (Path(source), archive_dir / filename)
        for key, source, filename, requires_success in candidates
        if (
            key in {"llm_facts", "llm_summary_html"}
            and source is not None
            and (
                not requires_success
                or llm_call_status == "succeeded"
                or (archive_dir / filename).exists()
            )
        )
    ]
    artifact_records: list[dict[str, object]] = []
    for key, src, filename, requires_llm_success in candidates:
        destination = archive_dir / filename
        _assert_market_structure_archive_target(destination)
        source = Path(src) if src is not None else None
        if requires_llm_success and llm_call_status != "succeeded":
            status = "preserved_previous" if destination.exists() else "skipped_llm_not_succeeded"
            artifact_records.append(
                _archive_artifact_record(
                    key=key,
                    source=source,
                    destination=destination,
                    status=status,
                )
            )
            if destination.exists():
                archived[key] = destination
            continue
        if source is None:
            artifact_records.append(
                _archive_artifact_record(
                    key=key,
                    source=None,
                    destination=destination,
                    status="source_missing",
                )
            )
            continue
        copied, status = _copy_if_exists(source, destination)
        if (
            is_v2
            and copied is not None
            and key in {"report", "alias"}
        ):
            links_updated = _rewrite_archived_report_links(
                report_path,
                copied,
                archived_report_link_targets,
            )
            if links_updated and status == "preserved":
                status = "preserved_links_updated"
        artifact_records.append(
            _archive_artifact_record(
                key=key,
                source=source,
                destination=destination,
                status=status,
            )
        )
        if copied is not None:
            archived[key] = copied
    if is_v2:
        _rewrite_latest_report_links(
            report_path,
            report_path,
            archived_report_link_targets,
        )
        if alias_path.resolve() != report_path.resolve():
            _rewrite_latest_report_links(
                report_path,
                alias_path,
                archived_report_link_targets,
            )
    manifest_path = _write_archive_manifest(
        archive_dir,
        prefix=prefix,
        report_date=report_date,
        symbol=symbol,
        horizon=horizon,
        artifacts=artifact_records,
        llm_call_status=llm_call_status,
        llm_error_type=llm_error_type,
        structure_metadata=metadata,
    )
    archived["manifest"] = manifest_path
    return archived


def _cached_index_close(cache_dir: str | Path, symbol: str) -> pd.Series | None:
    path = Path(cache_dir) / "index" / f"{symbol.upper()}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str})
    except Exception:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    series = pd.Series(close.to_numpy(), index=dates).dropna().sort_index()
    return series if not series.empty else None


def _date_bounds(frames: list[object]) -> tuple[str | None, str | None]:
    dates = []
    for df in frames:
        if df is None or getattr(df, "empty", True) or "date" not in df.columns:
            continue
        values = pd.to_datetime(df["date"], errors="coerce").dropna()
        if values.empty:
            continue
        dates.append(values.min())
        dates.append(values.max())
    if not dates:
        return None, None
    return min(dates).strftime("%Y%m%d"), max(dates).strftime("%Y%m%d")


def _build_breadth_for_frames(config: dict, frames: list[object]) -> dict:
    cache_dir = config.get("data", {}).get("cache_dir")
    if not cache_dir:
        return {}
    start, end = _date_bounds(frames)
    return build_market_breadth(cache_dir, start=start, end=end)


def _frame_dates_for_symbol(
    frames: list[tuple[str, str, object]] | list[object],
    symbol: str = DEFAULT_INDEX_SYMBOL,
) -> list[str]:
    for item in frames:
        if isinstance(item, tuple):
            sym, _, df = item
            if str(sym).upper() != symbol.upper():
                continue
        else:
            df = item
        if df is None or getattr(df, "empty", True) or "date" not in df.columns:
            continue
        values = pd.to_datetime(df["date"], errors="coerce").dropna().sort_values()
        if values.empty:
            continue
        return values.dt.strftime("%Y-%m-%d").tolist()
    return []


def _build_breadth_groups_for_frames(
    config: dict,
    frames: list[tuple[str, str, object]] | list[object],
    all_a_breadth: dict,
) -> dict:
    cache_dir = config.get("data", {}).get("cache_dir")
    meta_dir = config.get("data", {}).get("meta_dir")
    if not cache_dir or not meta_dir:
        return {}
    dates = _frame_dates_for_symbol(frames)
    if not dates:
        return {}
    start = min(dates).replace("-", "")
    end = max(dates).replace("-", "")
    groups = {"全A": breadth_indicator_payload(dates, all_a_breadth)}

    for label, member_code in DEFAULT_MEMBER_INDEX_CODES.items():
        symbols = load_latest_index_member_symbols(meta_dir, member_code, as_of=end)
        if not symbols:
            continue
        breadth = build_market_breadth(cache_dir, start=start, end=end, symbols=set(symbols))
        groups[label] = breadth_indicator_payload(dates, breadth)

    chinext_symbols = load_stock_basic_symbols_by_market(meta_dir, "创业板")
    if chinext_symbols:
        breadth = build_market_breadth(cache_dir, start=start, end=end, symbols=set(chinext_symbols))
        groups["创业板"] = breadth_indicator_payload(dates, breadth)

    return {
        label: payload
        for label, payload in groups.items()
        if payload.get("dates")
    }


def run_index_download(
    config: dict,
    symbol: Optional[str] = None,
    all_indexes: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
) -> list[tuple[str, object]]:
    """Download selected index data and return each symbol with its frame."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    indexes = _selected_indexes(config, symbol, all_indexes)
    results = []

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"指数数量: {len(indexes)}")
    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        click.echo(f"\n指数: {sym} ({name})")
        df = dl.download_index(symbol=sym, start=start, end=end, force=force)
        click.echo(f"完成: {len(df)} 条指数日线，缓存文件: {dl._index_cache_path(sym)}")
        results.append((sym, df))
    return results


def run_index_ths(
    config: dict,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    refresh_list: bool = False,
    include_industries: bool = True,
    include_styles: bool = True,
    include_concepts: bool = False,
    skip_failures: bool = False,
) -> list[tuple[str, object]]:
    """Update configured 同花顺指数行情 caches."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    ths_cfg = _ths_config(config)
    exchange = str((ths_cfg.get("index_list") or {}).get("exchange", "A"))
    index_list = dl.download_ths_index_list(exchange=exchange, force=refresh_list)
    names = _ths_index_names(index_list)
    symbols: list[str] = []
    if include_industries:
        symbols.extend(_select_ths_industry_symbols(index_list, config))
    if include_concepts:
        symbols.extend(_select_ths_concept_symbols(index_list, config))
    if include_styles:
        symbols.extend(_style_proxy_symbols(config))
    extra_symbols = [str(symbol).upper() for symbol in (ths_cfg.get("extra_symbols") or [])]
    symbols.extend(extra_symbols)
    symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol.endswith(".TI")))

    click.echo(f"同花顺指数列表: {len(index_list)} 条，缓存文件: {dl._ths_index_list_path()}")
    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"同花顺指数数量: {len(symbols)}")
    results = []
    for idx, symbol in enumerate(symbols, start=1):
        name = names.get(symbol, symbol)
        click.echo(f"\n[{idx}/{len(symbols)}] 同花顺指数: {symbol} ({name})")
        try:
            df = dl.download_index(symbol=symbol, start=start, end=end, force=force)
        except Exception as exc:
            if not skip_failures:
                raise
            click.secho(f"  警告: 跳过同花顺指数 {symbol} ({name}): {exc}", fg="yellow")
            continue
        click.echo(f"完成: {len(df)} 条，缓存文件: {dl._index_cache_path(symbol)}")
        results.append((symbol, df))
    if not results:
        raise click.ClickException("没有可用同花顺指数数据")
    return results


def run_index_report(
    config: dict,
    symbol: Optional[str] = None,
    all_indexes: bool = False,
    output: Optional[str] = None,
) -> list[Path]:
    """Generate reports from locally cached index data."""
    dl = DataDownloader(config)
    indexes = _selected_indexes(config, symbol, all_indexes)
    output_paths = []
    frames = []

    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        df = dl.load_index_cache(sym)
        if df is None or df.empty:
            raise click.ClickException(
                f"指数缓存不存在: {sym}，请先执行 python main.py index download --symbol {sym}"
            )
        frames.append(df)

    breadth = _build_breadth_for_frames(config, frames)
    frame_items = [(item["symbol"].upper(), item.get("name") or _index_name(config, item["symbol"].upper()), df) for item, df in zip(indexes, frames)]
    breadth_groups = _build_breadth_groups_for_frames(config, frame_items, breadth)

    for item, df in zip(indexes, frames):
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)

        out_path = _output_path(config, sym, output, all_indexes)
        generate_index_report(
            df,
            symbol=sym,
            name=name,
            output_path=out_path,
            breadth_by_date=breadth,
            breadth_groups=breadth_groups,
            technical_structure_config={
                **(config.get("technical_structure", {}) or {}),
                "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
            },
        )
        click.echo(f"报告已生成: {out_path}")
        output_paths.append(out_path)
    return output_paths


def run_index_overview(
    config: dict,
    symbol: Optional[str] = None,
    all_indexes: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    output: Optional[str] = None,
) -> list[Path]:
    """Update selected index data and generate overview reports."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    indexes = _selected_indexes(config, symbol, all_indexes)
    output_paths = []

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"指数数量: {len(indexes)}")
    frame_items = _download_index_frames(
        dl,
        config,
        indexes,
        start,
        end,
        force,
        skip_failures=all_indexes,
    )

    breadth = _build_breadth_for_frames(config, [df for _, _, df in frame_items])
    breadth_groups = _build_breadth_groups_for_frames(config, frame_items, breadth)

    for sym, name, df in frame_items:
        out_path = _output_path(config, sym, output, all_indexes)
        generate_index_report(
            df,
            symbol=sym,
            name=name,
            output_path=out_path,
            breadth_by_date=breadth,
            breadth_groups=breadth_groups,
            technical_structure_config={
                **(config.get("technical_structure", {}) or {}),
                "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
            },
        )
        click.echo(f"完成: {len(df)} 条指数日线")
        click.echo(f"报告已生成: {out_path}")
        output_paths.append(out_path)
    return output_paths


def run_index_market(
    config: dict,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    output: Optional[str] = None,
) -> Path:
    """Update configured indexes and generate a broad-market environment report."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    indexes = _configured_indexes(config)

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"指数数量: {len(indexes)}")
    frames = _download_index_frames(
        dl,
        config,
        indexes,
        start,
        end,
        force,
        skip_failures=True,
    )

    breadth = _build_breadth_for_frames(config, [df for _, _, df in frames])
    breadth_groups = _build_breadth_groups_for_frames(config, frames, breadth)
    out_path = _market_output_path(config, output)
    generate_market_report(
        frames,
        out_path,
        breadth_by_date=breadth,
        breadth_groups=breadth_groups,
        technical_structure_config={
            **(config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
        },
    )
    click.echo(f"大盘环境看板已生成: {out_path}")
    return out_path


def run_index_members(
    config: dict,
    symbol: Optional[str] = None,
    all_indexes: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    include_chinext_index: bool = False,
) -> list[Path]:
    """Download and cache index member weights for breadth groups."""
    dl = DataDownloader(config)
    end = end or today_str()
    if start is None:
        end_ts = pd.to_datetime(end, format="%Y%m%d")
        start = end_ts.replace(day=1).strftime("%Y%m%d")
    if all_indexes:
        items = list(DEFAULT_MEMBER_INDEX_CODES.items())
        if include_chinext_index:
            configured_codes = {code.upper() for _, code in items}
            items.extend(
                (label, code)
                for label, code in OPTIONAL_MEMBER_INDEX_CODES.items()
                if code.upper() not in configured_codes
            )
    else:
        code = (symbol or "399300.SZ").upper()
        items = [(code, code)]

    paths = []
    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"成分指数数量: {len(items)}")
    if all_indexes:
        click.echo("说明: 创业板指成分已纳入默认分层广度成分快照。")
    for label, code in items:
        click.echo(f"\n指数成分: {code} ({label})")
        dl.download_index_members(code, start=start, end=end, force=force)
        path = dl._index_members_path(code)
        click.echo(f"缓存文件: {path}")
        paths.append(path)
    return paths


def run_index_forecast(
    config: dict,
    symbol: Optional[str] = None,
    horizon: int = 5,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    output: Optional[str] = None,
    model: str = "rule_v1",
) -> Path:
    """Build current market structure plus backward-compatible legacy forecast outputs."""
    dl = DataDownloader(config)
    symbol = (symbol or _default_symbol(config)).upper()
    name = _index_name(config, symbol)
    start = start or default_start()
    end = end or today_str()
    horizon = int(horizon)
    if horizon not in ENVIRONMENT_HORIZONS:
        raise click.ClickException("市场环境预测周期仅支持 1、5、10、20 个交易日。")
    model = (model or "rule_v1").lower()

    click.echo(f"大盘指数与市场结构分析: {symbol} ({name})")
    click.echo(f"日期范围: {start} ~ {end}；旧预测诊断周期: {horizon} 个交易日，模型: {model}")
    df = dl.download_index(symbol=symbol, start=start, end=end, force=force)
    if symbol != ALL_A_INDEX_SYMBOL:
        click.echo(f"同步平均股价基准: {ALL_A_INDEX_SYMBOL} ({ALL_A_INDEX_NAME})")
        try:
            dl.download_index(symbol=ALL_A_INDEX_SYMBOL, start=start, end=end, force=force)
        except Exception as exc:
            raise click.ClickException(
                f"无法生成 {ALL_A_INDEX_SYMBOL}（{ALL_A_INDEX_NAME}），市场结构分析缺少平均股价基准: {exc}"
            ) from exc
    breadth = _build_breadth_for_frames(config, [df])
    frame_items = [(symbol, name, df)]
    breadth_groups = _build_breadth_groups_for_frames(config, frame_items, breadth)
    cache_dir = config.get("data", {}).get("cache_dir")
    if not cache_dir:
        raise click.ClickException("缺少 data.cache_dir，无法构建个股横截面市场环境标签。")
    meta_dir = config.get("data", {}).get("meta_dir", "data/meta")
    index_member_frames = load_index_member_frames(meta_dir)
    panels = load_stock_market_panels(
        cache_dir,
        Path(meta_dir) / "stocks.csv",
        dates=df["date"],
    )
    close_matrix = panels.close
    if close_matrix.empty:
        raise click.ClickException("本地个股缓存为空，无法构建市场环境标签；请先下载股票日线。")
    index_close = pd.Series(
        pd.to_numeric(df["close"], errors="coerce").to_numpy(),
        index=pd.to_datetime(df["date"], errors="coerce"),
    )
    cross_section_features = build_current_cross_section_features(
        close_matrix,
        index_close=index_close,
        large_cap_index_close=_cached_index_close(cache_dir, "000300.SH"),
        small_cap_index_close=_cached_index_close(cache_dir, "000852.SH"),
    )
    indicators = build_index_forecast_indicators(
        df,
        symbol=symbol,
        breadth_by_date=breadth,
        breadth_groups=breadth_groups,
        cross_section_features=cross_section_features,
    )
    index_frames = load_required_index_frames(cache_dir, df, symbol)
    ths_frames, ths_names, ths_industry_symbols = _load_ths_frames_for_structure(config)
    market_structure = build_market_structure(
        symbol,
        index_frames,
        panels,
        ths_index_frames=ths_frames,
        ths_index_names=ths_names,
        ths_industry_symbols=ths_industry_symbols,
        ths_style_config=_style_proxy_config(config),
        ths_industry_min_available=int((_ths_config(config).get("industries") or {}).get("min_available", 20)),
        ths_style_min_history_bars=int((_ths_config(config).get("style_min_history_bars", 60))),
        index_member_frames=index_member_frames,
        market_structure_v2_config={
            **(config.get("market_structure_v2", {}) or {}),
            "index_lift_structure": config.get("index_lift_structure", {}) or {},
        },
    )
    forecast_config = config.get("index_forecast", {})
    environment_targets = build_market_environment_targets(
        df,
        close_matrix,
        horizons=ENVIRONMENT_HORIZONS,
        large_decline_threshold=float(forecast_config.get("large_decline_threshold", -0.05)),
        percentile_window=int(forecast_config.get("percentile_window", 756)),
        percentile_min_periods=int(forecast_config.get("percentile_min_periods", 60)),
    )
    legacy_features = add_forecast_labels(
        indicators,
        horizons=ENVIRONMENT_HORIZONS,
        environment_targets=environment_targets,
    )
    # Legacy predictions are deliberately computed before the new structure columns
    # are attached. The refactor must not change formal signal/strategy semantics.
    predictions = build_rule_forecast(legacy_features, horizon=horizon, model=model)
    indicators = attach_market_structure_columns(indicators, market_structure)
    features = attach_market_structure_columns(legacy_features, market_structure)
    market_structure["legacy_forecast"] = (
        predictions.iloc[-1][[
            column for column in (
                "trade_date", "model", "environment_signal", "market_score",
                "predicted_opportunity_score", "predicted_risk_score",
            ) if column in predictions.columns
        ]].to_dict()
        if not predictions.empty else {}
    )
    strategy_returns = load_strategy_daily_returns(
        config.get("output", {}).get("trades_dir", "output/trades")
    )
    evaluation = evaluate_forecast(
        predictions,
        horizon=horizon,
        strategy_returns=strategy_returns,
    )
    paths = save_forecast_outputs(config, symbol, horizon, indicators, features, predictions, model=model)
    structure_paths = save_market_structure_outputs(config, symbol, market_structure)
    out_path = _forecast_output_path(config, symbol, horizon, output, model=model)
    diagnostic_report = diagnostic_paths(config, symbol, horizon).html
    latest = predictions.iloc[-1].to_dict() if not predictions.empty else {}
    report_date = str(market_structure.get("date") or latest.get("trade_date") or end)
    llm_summary_links: dict[str, str] = {}
    llm_summary_path: Path | None = None
    # Resolve paths before the API call.  Fact/prompt files are written before
    # DeepSeek is contacted and must remain available for archival on failures.
    llm_paths = llm_summary_paths(config, symbol, horizon)
    llm_call_status = "not_called"
    llm_error_type: str | None = None
    try:
        llm_paths, llm_summary = write_llm_summary_artifacts(
            config,
            symbol=symbol,
            horizon=horizon,
            name=name,
            call_api=True,
            skip_if_no_key=True,
        )
        if llm_summary and llm_paths.html.exists():
            llm_call_status = "succeeded"
            llm_summary_path = llm_paths.summary
            llm_summary_links["summary"] = relative_href(
                out_path,
                llm_paths.html,
            )
            llm_summary_links["facts"] = relative_href(
                out_path,
                llm_paths.facts,
            )
        else:
            llm_call_status = "skipped_no_key"
            click.echo(f"大模型事实包: {llm_paths.facts}")
            click.echo("未检测到 DeepSeek API Key，已跳过复盘总结生成。")
    except Exception as exc:
        llm_call_status = "failed"
        llm_error_type = type(exc).__name__
        click.secho(f"大模型复盘总结生成失败，主报告继续生成: {exc}", fg="yellow")
    generate_index_forecast_report(
        features=features,
        predictions=predictions,
        output_path=out_path,
        symbol=symbol,
        name=name,
        horizon=horizon,
        evaluation=evaluation,
        market_structure=market_structure,
        legacy_links={
            "predictions": relative_href(out_path, paths.predictions),
            "diagnostics": relative_href(out_path, diagnostic_report),
        },
        llm_summary_links=llm_summary_links,
        technical_structure_config={
            **(config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
        },
        technical_index_frames=index_frames,
        technical_industry_frames=ths_frames,
    )
    alias_path = _market_structure_alias_path(config, symbol)
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    if alias_path.resolve() != out_path.resolve():
        shutil.copyfile(out_path, alias_path)
    brief_path = _market_structure_brief_path(config, symbol)
    generate_market_structure_brief(
        config,
        market_structure,
        brief_path,
        full_report_path=alias_path,
        features=features,
        symbol=symbol,
        name=name,
        technical_structure_config={
            **(config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
        },
        technical_index_frames=index_frames,
        technical_industry_frames=ths_frames,
    )
    archived_paths = _archive_market_structure_outputs(
        config,
        symbol=symbol,
        horizon=horizon,
        report_date=report_date,
        report_path=out_path,
        alias_path=alias_path,
        structure_paths=structure_paths,
        llm_paths=llm_paths,
        llm_call_status=llm_call_status,
        llm_error_type=llm_error_type,
        structure_metadata=market_structure,
    )

    click.echo(f"指标数据: {paths.indicators}")
    click.echo(f"训练特征: {paths.features}")
    click.echo(f"预测数据: {paths.predictions}")
    click.echo(f"市场结构数据: {structure_paths['json']}")
    if llm_summary_path:
        click.echo(f"大模型复盘总结: {llm_summary_path}")
    click.echo(f"市场结构规范别名: {alias_path}")
    click.echo(f"市场结构摘录版: {brief_path}")
    if archived_paths:
        manifest_path = archived_paths.get("manifest")
        click.echo(
            f"市场结构归档目录: "
            f"{_market_structure_archive_dir(config, report_date, market_structure.get('schema_version'))}；"
            f"策略=保留已有文件；LLM={llm_call_status}"
        )
        if manifest_path:
            click.echo(f"市场结构归档清单: {manifest_path}")
    click.echo(
        "旧实验预测（仅诊断）: "
        f"{latest.get('trade_date', '--')} "
        f"score={latest.get('market_score', '--')} "
        f"environment={latest.get('environment_signal', '--')} "
        f"opportunity={latest.get('predicted_opportunity_score', '--')} "
        f"risk={latest.get('predicted_risk_score', '--')}"
    )
    if evaluation.get("sample_count"):
        click.echo(
            f"历史验证: 样本 {evaluation['sample_count']}，"
            f"命中率 {evaluation['accuracy'] * 100:.1f}%"
        )
    click.echo(f"市场结构报告已生成: {out_path}")
    return out_path


def run_market_structure_brief(
    config: dict,
    symbol: Optional[str] = None,
    horizon: int = 5,
    model: str = "rule_v1",
    output: Optional[str] = None,
    structure_json: Optional[str] = None,
    full_report: Optional[str] = None,
) -> Path:
    """Generate only the market-structure excerpt page from saved facts and caches."""
    symbol = (symbol or _default_symbol(config)).upper()
    name = _index_name(config, symbol)
    structure_path = Path(structure_json) if structure_json else _market_structure_json_path(config, symbol)
    if not structure_path.exists():
        raise click.ClickException(
            f"市场结构 JSON 不存在: {structure_path}；请先运行 `python main.py index structure` 生成事实层，"
            "或用 --structure-json 指定已有 JSON。"
        )
    try:
        market_structure = json.loads(structure_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise click.ClickException(f"无法读取市场结构 JSON: {structure_path} ({exc})") from exc

    features: pd.DataFrame | None = None
    feature_path = forecast_paths(config, symbol, int(horizon), model=model).features
    if feature_path.exists():
        try:
            features = pd.read_csv(
                feature_path,
                dtype={"date": str, "trade_date": str, "ts_code": str},
                low_memory=False,
            )
        except Exception as exc:
            click.secho(f"特征 CSV 读取失败，摘录页将回退指数缓存: {feature_path} ({exc})", fg="yellow")

    ths_frames, _, _ = _load_ths_frames_for_structure(config)
    output_path = Path(output) if output else _market_structure_brief_path(config, symbol)
    alias_path = _market_structure_alias_path(config, symbol)
    if full_report:
        full_report_path: Path | None = Path(full_report)
    else:
        full_report_path = alias_path if alias_path.exists() else None
    generated = generate_market_structure_brief(
        config,
        market_structure,
        output_path,
        full_report_path=full_report_path,
        features=features,
        symbol=symbol,
        name=name,
        technical_structure_config={
            **(config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
        },
        technical_industry_frames=ths_frames,
    )
    click.echo(f"市场结构摘录版: {generated}")
    click.echo(f"市场结构事实层: {structure_path}")
    if feature_path.exists():
        click.echo(f"主指数特征: {feature_path}")
    return generated


def run_index_forecast_diagnose(
    config: dict,
    symbol: Optional[str] = None,
    horizon: int = 5,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    output: Optional[str] = None,
    label_mode: str = "environment",
) -> Path:
    """Generate diagnostics for existing or newly built index forecast outputs."""
    symbol = (symbol or _default_symbol(config)).upper()
    name = _index_name(config, symbol)
    start = start or default_start()
    end = end or today_str()
    horizon = int(horizon)
    label_mode = (label_mode or "environment").lower()

    def _build_forecast() -> Path:
        return run_index_forecast(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
            force=force,
            output=None,
        )

    paths = diagnostic_paths(config, symbol, horizon, output, label_mode=label_mode)
    forecast_file = Path(config["output"].get("statistics_dir", "output/statistics")) / "index_forecast" / f"predictions_{symbol}_h{horizon}.csv"

    click.echo(f"指数预测诊断: {symbol} ({name})")
    click.echo(f"日期范围: {start} ~ {end}，预测周期: {horizon} 个交易日，标签模式: {label_mode}")
    if force or not forecast_file.exists():
        click.echo("预测数据不存在或已选择强制刷新，先生成预测数据。")
    _ensure_forecast_files(
        config, symbol, horizon, start, end, force, build_forecast=_build_forecast
    )

    try:
        features, predictions = load_diagnostic_frames(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
        )
    except FileNotFoundError:
        click.echo("预测数据缺失，先生成预测数据。")
        _build_forecast()
        features, predictions = load_diagnostic_frames(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
        )

    label_column = f"environment_label_{horizon}d"
    if label_mode == "legacy":
        label_column = f"label_{horizon}d"
    elif label_mode == "abs":
        label_column = f"label_abs_{horizon}d"
    elif label_mode == "rank":
        label_column = f"label_rank_{horizon}d"
    if label_column not in features.columns and label_column not in predictions.columns:
        click.echo(f"预测数据缺少 {label_column}，先刷新预测数据。")
        _build_forecast()
        features, predictions = load_diagnostic_frames(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
        )

    if features.empty or predictions.empty:
        raise click.ClickException("诊断数据为空，请先生成指数预测数据。")

    strategy_returns = load_strategy_daily_returns(
        config.get("output", {}).get("trades_dir", "output/trades")
    )
    diagnostics = build_diagnostics(
        features, predictions, horizon=horizon, symbol=symbol, label_mode=label_mode,
        strategy_returns=strategy_returns,
    )
    saved = save_diagnostics(config, symbol, horizon, diagnostics, output=output)
    metrics = diagnostics.get("metrics", {})
    click.echo(f"诊断报告已生成: {saved.html}")
    click.echo(f"诊断指标: {saved.metrics}")
    click.echo(f"特征相关性: {saved.feature_correlations}")
    click.echo(f"关键条件汇总: {saved.condition_summary}")
    click.echo(f"年度稳定性: {saved.yearly_summary}")
    click.echo(f"概率校准: {saved.calibration}")
    click.echo(f"时间切分: {saved.split_summary}")
    click.echo(f"来源表现: {saved.reason_summary}")
    click.echo(f"P0 特征白名单: {saved.feature_whitelist}")
    click.echo(f"宽度水平×斜率: {saved.breadth_events}")
    click.echo(f"双目标滚动样本外: {saved.walk_forward}")
    click.echo(f"逐折简单基线: {saved.walk_forward_baselines}")
    click.echo(f"逐折模型系数: {saved.walk_forward_coefficients}")
    click.echo(f"透明标签稳定性: {saved.label_stability}")
    click.echo(f"特征十分位研究: {saved.feature_deciles}")
    click.echo(f"特征组消融: {saved.ablation}")
    click.echo(f"P0/P1 门槛汇总: {saved.research_summary}")
    click.echo(f"历史股票池覆盖审计: {saved.point_in_time_quality}")
    click.echo(f"年度/波动状态稳定性: {saved.regime_stability}")
    click.echo(f"环境切换事件: {saved.transition_study}")
    click.echo(f"策略 A-E 增量验证: {saved.strategy_policies}")
    click.echo(f"P2/P3 上线门槛审计: {saved.gate_audit}")
    click.echo(f"模型系数稳定性: {saved.coefficient_stability}")
    click.echo(
        "核心诊断: "
        f"样本 {metrics.get('sample_count', '--')}，"
        f"命中率 {float(metrics.get('accuracy') or 0) * 100:.1f}%，"
        f"平衡命中率 {float(metrics.get('balanced_accuracy') or 0) * 100:.1f}%，"
        f"多空收益差 {float(metrics.get('long_short_spread') or 0) * 100:+.2f}%"
    )
    return saved.html


def run_index_llm_summary(
    config: dict,
    symbol: Optional[str] = None,
    horizon: int = 5,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    model: str = "rule_v1",
    refresh: bool = False,
    no_api: bool = False,
    skip_if_no_key: bool = False,
) -> Path:
    """Generate LLM fact package and optionally ask DeepSeek for a written summary."""
    symbol = (symbol or _default_symbol(config)).upper()
    name = _index_name(config, symbol)
    horizon = int(horizon)
    if refresh:
        run_index_forecast(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
            force=force,
            output=None,
            model=model,
        )
    paths, summary = write_llm_summary_artifacts(
        config,
        symbol=symbol,
        horizon=horizon,
        name=name,
        call_api=not no_api,
        skip_if_no_key=skip_if_no_key,
    )
    click.echo(f"大模型事实包: {paths.facts}")
    click.echo(f"大模型提示词: {paths.prompt}")
    if no_api:
        click.echo("已跳过 DeepSeek API 调用；可复制提示词给大模型。")
        return paths.prompt
    if summary is None:
        click.echo("未检测到 DeepSeek API Key，已跳过总结生成。")
        return paths.prompt
    click.echo(f"DeepSeek 总结 Markdown: {paths.summary}")
    click.echo(f"DeepSeek 总结 HTML: {paths.html}")
    return paths.summary


@click.group(name="index")
def index_group():
    """指数数据与每日概览。"""
    pass


@index_group.command(name="download")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="下载配置中的第一阶段指数列表")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
def download(symbol: Optional[str], all_indexes: bool, start: Optional[str], end: Optional[str], force: bool):
    """下载指数日线并缓存到 data/cache/index。"""
    config = _load_config()
    run_index_download(config, symbol, all_indexes, start, end, force)


@index_group.command(name="ths")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
@click.option("--refresh-list", is_flag=True, help="强制刷新同花顺指数列表")
@click.option("--skip-industries", is_flag=True, help="不下载同花顺行业指数")
@click.option("--skip-styles", is_flag=True, help="不下载市场风格代理指数")
@click.option("--include-concepts", is_flag=True, help="额外下载同花顺概念指数（type=N，数量较多）")
@click.option("--skip-failures", is_flag=True, help="批量更新时跳过单个无数据或失败的同花顺指数")
def ths(
    start: Optional[str],
    end: Optional[str],
    force: bool,
    refresh_list: bool,
    skip_industries: bool,
    skip_styles: bool,
    include_concepts: bool,
    skip_failures: bool,
):
    """下载同花顺行业/风格/可选概念指数日线缓存，不生成单指数报告。"""
    config = _load_config()
    run_index_ths(
        config,
        start=start,
        end=end,
        force=force,
        refresh_list=refresh_list,
        include_industries=not skip_industries,
        include_styles=not skip_styles,
        include_concepts=include_concepts,
        skip_failures=skip_failures,
    )


@index_group.command(name="report")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="为配置中的第一阶段指数列表生成报告")
@click.option("--output", default=None, help="输出 HTML 路径；--all 时表示输出目录")
def report(symbol: Optional[str], all_indexes: bool, output: Optional[str]):
    """基于本地缓存生成指数概览 HTML。"""
    config = _load_config()
    run_index_report(config, symbol, all_indexes, output)


@index_group.command(name="overview")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="更新配置中的第一阶段指数列表并生成报告")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
@click.option("--output", default=None, help="输出 HTML 路径；--all 时表示输出目录")
def overview(
    symbol: Optional[str],
    all_indexes: bool,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    output: Optional[str],
):
    """更新指数日线并生成每日概览。"""
    config = _load_config()
    run_index_overview(config, symbol, all_indexes, start, end, force, output)


@index_group.command(name="market")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载指数并合并缓存")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/market_overview.html")
def market(start: Optional[str], end: Optional[str], force: bool, output: Optional[str]):
    """更新配置指数并生成大盘环境分析看板。"""
    config = _load_config()
    run_index_market(config, start, end, force, output)


@index_group.command(name="members")
@click.option("--symbol", default=None, help="指数成分代码，默认 399300.SZ（沪深300）")
@click.option("--all", "all_indexes", is_flag=True, help="下载默认分层广度所需指数成分")
@click.option("--include-chinext-index", is_flag=True, help="兼容参数；创业板指成分已纳入 --all 默认范围")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认结束日期所在月首日")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
def members(
    symbol: Optional[str],
    all_indexes: bool,
    include_chinext_index: bool,
    start: Optional[str],
    end: Optional[str],
    force: bool,
):
    """下载指数成分和权重，用于分层 A/D 广度分析。"""
    config = _load_config()
    run_index_members(config, symbol, all_indexes, start, end, force, include_chinext_index)


@index_group.command(name="forecast")
@click.option("--symbol", default=None, help="指数代码，默认读取 index_overview.default_symbol")
@click.option("--horizon", default=5, type=click.Choice([1, 5, 10, 20]), help="预测周期")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载指数并合并缓存")
@click.option(
    "--model",
    type=click.Choice(["rule_v1", "rule_h3_v2"]),
    default="rule_v1",
    show_default=True,
    help="预测模型",
)
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/index_forecast/{symbol}_h{horizon}.html")
def forecast(
    symbol: Optional[str],
    horizon: int,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    model: str,
    output: Optional[str],
):
    """生成大盘指数与市场结构报告（保留旧预测诊断）。"""
    config = _load_config()
    run_index_forecast(config, symbol, horizon, start, end, force, output, model)


@index_group.command(name="structure")
@click.option("--symbol", default=None, help="指数代码，默认读取 index_overview.default_symbol")
@click.option("--horizon", default=5, type=click.Choice([1, 5, 10, 20]), help="旧预测诊断周期")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载指数并合并缓存")
@click.option("--model", type=click.Choice(["rule_v1", "rule_h3_v2"]), default="rule_v1", show_default=True)
@click.option("--output", default=None, help="沿用 index_forecast 报告路径")
def structure(
    symbol: Optional[str], horizon: int, start: Optional[str], end: Optional[str],
    force: bool, model: str, output: Optional[str],
):
    """forecast 的市场结构语义别名，调用同一分析流程。"""
    config = _load_config()
    run_index_forecast(config, symbol, horizon, start, end, force, output, model)


@index_group.command(name="structure-brief")
@click.option("--symbol", default=None, help="指数代码，默认读取 index_overview.default_symbol")
@click.option("--horizon", default=5, type=click.Choice([1, 5, 10, 20]), help="读取 features CSV 时使用的旧诊断周期")
@click.option("--model", type=click.Choice(["rule_v1", "rule_h3_v2"]), default="rule_v1", show_default=True)
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/index_forecast/{symbol}_market_structure_brief.html")
@click.option("--structure-json", default=None, help="已有市场结构 JSON 路径，默认读取 output/statistics/index_forecast/market_structure_{symbol}.json")
@click.option("--full-report", default=None, help="可选完整报告 HTML 路径；不传且默认别名不存在时，摘录页不显示完整报告入口")
def structure_brief(
    symbol: Optional[str],
    horizon: int,
    model: str,
    output: Optional[str],
    structure_json: Optional[str],
    full_report: Optional[str],
):
    """只生成市场结构摘录页，不生成完整九屏报告。"""
    config = _load_config()
    run_market_structure_brief(config, symbol, horizon, model, output, structure_json, full_report)


@index_group.command(name="forecast-diagnose")
@click.option("--symbol", default=None, help="指数代码，默认读取 index_overview.default_symbol")
@click.option("--horizon", default=5, type=click.Choice([1, 5, 10, 20]), help="预测周期")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新生成预测数据后再诊断")
@click.option(
    "--label-mode",
    type=click.Choice(["environment", "legacy", "abs", "rank"]),
    default="environment",
    show_default=True,
    help="诊断标签口径：environment=个股横截面环境，其他为兼容的指数收益标签",
)
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/index_forecast/diagnostics_{symbol}_h{horizon}.html")
def forecast_diagnose(
    symbol: Optional[str],
    horizon: int,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    label_mode: str,
    output: Optional[str],
):
    """生成指数预测模型诊断报告。"""
    config = _load_config()
    run_index_forecast_diagnose(config, symbol, horizon, start, end, force, output, label_mode)


@index_group.command(name="llm-summary")
@click.option("--symbol", default=None, help="指数代码，默认读取 index_overview.default_symbol")
@click.option("--horizon", default=5, type=click.Choice([1, 5, 10, 20]), help="对应市场结构报告周期")
@click.option("--start", default=None, help="--refresh 时使用的起始日期 YYYYMMDD")
@click.option("--end", default=None, help="--refresh 时使用的结束日期 YYYYMMDD")
@click.option("--force", is_flag=True, help="--refresh 时强制重新下载指数并合并缓存")
@click.option("--model", type=click.Choice(["rule_v1", "rule_h3_v2"]), default="rule_v1", show_default=True)
@click.option("--refresh", is_flag=True, help="先重新生成 index forecast，再生成大模型总结")
@click.option("--no-api", is_flag=True, help="只生成事实包和提示词，不调用 DeepSeek API")
@click.option("--skip-if-no-key", is_flag=True, help="缺少 DEEPSEEK_API_KEY 时跳过 API，不让自动任务失败")
def llm_summary(
    symbol: Optional[str],
    horizon: int,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    model: str,
    refresh: bool,
    no_api: bool,
    skip_if_no_key: bool,
):
    """生成市场结构大模型事实包，并调用 DeepSeek 输出复盘总结。"""
    config = _load_config()
    run_index_llm_summary(
        config,
        symbol=symbol,
        horizon=horizon,
        start=start,
        end=end,
        force=force,
        model=model,
        refresh=refresh,
        no_api=no_api,
        skip_if_no_key=skip_if_no_key,
    )
