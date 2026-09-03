"""Versioned JSON handoff service for manually reviewed limit-up theme pools.

This module deliberately does not fetch market data or call an LLM.  It owns a
separate JSON document and the batch/import protocol used to hand candidates to
ChatGPT and back to a human reviewer.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PATH = Path("config/theme_stock_pools.json")
SCHEMA_VERSION = 1
CODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
THEME_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CLASSIFICATION_SOURCES = {"manual", "chatgpt_manual_handoff", "import"}
INDUSTRY_RELATIONS = {"core", "direct", "indirect", "unknown"}
MARKET_THEME_RELATIONS = {"core", "active", "catalyst", "mapping_only", "unknown"}
CONFIDENCES = {"high", "medium", "low", "unknown"}
STATUSES = {"pending", "confirmed", "rejected"}
CLASSIFICATION_STATUSES = {"classified", "unclassified", "needs_research", "conflict"}
POOL_ROLES = {"rs_member", "watch_only"}


class ThemeStockPoolError(ValueError):
    """Raised when the dedicated theme-stock-pool document is invalid."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _string(value: Any) -> str:
    return str(value or "").strip()


def normalize_symbol(value: Any) -> str:
    code = _string(value).upper()
    if CODE_RE.fullmatch(code):
        return code
    if re.fullmatch(r"\d{6}", code):
        return f"{code}.SH" if code.startswith("6") else f"{code}.BJ" if code.startswith(("8", "4")) else f"{code}.SZ"
    return ""


def theme_stock_pool_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else DEFAULT_PATH


def empty_document() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "updated_at": now_iso(), "themes": {}, "stocks": {}, "batches": {}}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ThemeStockPoolError(f"主题股票池文件不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThemeStockPoolError(f"主题股票池 JSON 格式错误: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ThemeStockPoolError("主题股票池 JSON 顶层必须是对象")
    return payload


def _validate_evidence(items: Any, context: str) -> None:
    if items is None:
        return
    if not isinstance(items, list):
        raise ThemeStockPoolError(f"{context}.evidence 必须是列表")
    for index, evidence in enumerate(items):
        if not isinstance(evidence, dict):
            raise ThemeStockPoolError(f"{context}.evidence[{index}] 必须是对象")
        for field in ("evidence_type", "title", "source_name", "supports"):
            if not _string(evidence.get(field)):
                raise ThemeStockPoolError(f"{context}.evidence[{index}].{field} 不能为空")
        url = evidence.get("url")
        if url is not None and not isinstance(url, str):
            raise ThemeStockPoolError(f"{context}.evidence[{index}].url 必须是字符串或 null")


def _validate_assignment(theme_id: str, assignment: Any, context: str) -> None:
    if not isinstance(assignment, dict):
        raise ThemeStockPoolError(f"{context}.{theme_id} 必须是对象")
    for field, allowed in (
        ("classification_source", CLASSIFICATION_SOURCES),
        ("industry_relation", INDUSTRY_RELATIONS),
        ("market_theme_relation", MARKET_THEME_RELATIONS),
        ("confidence", CONFIDENCES),
        ("status", STATUSES),
    ):
        if assignment.get(field) not in allowed:
            raise ThemeStockPoolError(f"{context}.{theme_id}.{field} 非法: {assignment.get(field)!r}")
    if not isinstance(assignment.get("manual_locked"), bool):
        raise ThemeStockPoolError(f"{context}.{theme_id}.manual_locked 必须是布尔值")
    if "pool_role" in assignment and assignment["pool_role"] not in POOL_ROLES:
        raise ThemeStockPoolError(f"{context}.{theme_id}.pool_role 非法: {assignment.get('pool_role')!r}")
    if assignment.get("status") == "confirmed" and not _string(assignment.get("reason")):
        raise ThemeStockPoolError(f"{context}.{theme_id} 已确认关系必须包含 reason")
    _validate_evidence(assignment.get("evidence"), f"{context}.{theme_id}")


def assignment_pool_role(assignment: dict[str, Any]) -> str:
    """Return the compatible role for a persisted relationship.

    Confirmed records written before pool_role existed remain RS members.  The
    caller must still enforce status separately, so a missing pending role can
    never enter RS simply through this fallback.
    """
    role = assignment.get("pool_role")
    return role if role in POOL_ROLES else "rs_member"


def derive_pool_role(item: dict[str, Any]) -> str:
    """Use a conservative, transparent role when legacy handoff JSON omits it."""
    explicit = item.get("pool_role")
    if explicit is not None:
        if explicit not in POOL_ROLES:
            raise ThemeStockPoolError(f"分类结果 assignment.pool_role 非法: {explicit!r}")
        return explicit
    if item.get("industry_relation") == "indirect" or item.get("market_theme_relation") in {"catalyst", "mapping_only"}:
        return "watch_only"
    if item.get("industry_relation") in {"core", "direct"} and item.get("confidence") in {"high", "medium"}:
        return "rs_member"
    return "watch_only"


def validate_document(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") != SCHEMA_VERSION:
        raise ThemeStockPoolError(f"version 必须为 {SCHEMA_VERSION}")
    if not _string(payload.get("updated_at")):
        raise ThemeStockPoolError("updated_at 不能为空")
    for field in ("themes", "stocks"):
        if not isinstance(payload.get(field), dict):
            raise ThemeStockPoolError(f"{field} 必须是对象")
    if "batches" in payload and not isinstance(payload["batches"], dict):
        raise ThemeStockPoolError("batches 必须是对象")
    names: set[str] = set()
    for theme_id, theme in payload["themes"].items():
        if not THEME_ID_RE.fullmatch(str(theme_id)) or not isinstance(theme, dict):
            raise ThemeStockPoolError(f"非法主题: {theme_id!r}")
        name = _string(theme.get("name"))
        if not name or name in names:
            raise ThemeStockPoolError(f"主题名称为空或重复: {theme_id}")
        names.add(name)
        if not isinstance(theme.get("enabled"), bool) or not _string(theme.get("definition")):
            raise ThemeStockPoolError(f"主题 {theme_id} 必须包含 enabled 和 definition")
    for code, stock in payload["stocks"].items():
        if not CODE_RE.fullmatch(str(code)) or not isinstance(stock, dict):
            raise ThemeStockPoolError(f"非法股票记录: {code!r}")
        assignments = stock.get("assignments", {})
        if not isinstance(assignments, dict):
            raise ThemeStockPoolError(f"股票 {code} 的 assignments 必须是对象")
        for theme_id, assignment in assignments.items():
            if theme_id not in payload["themes"]:
                raise ThemeStockPoolError(f"股票 {code} 使用了未知主题 {theme_id}")
            _validate_assignment(theme_id, assignment, f"stocks.{code}.assignments")
    return payload


def load_theme_stock_pools(path: str | Path | None = None) -> dict[str, Any]:
    return validate_document(_read_json(theme_stock_pool_path(path)))


def _sidecar_dir(path: Path, kind: str) -> Path:
    return path.parent / f"{path.stem}_{kind}"


def _atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    directory = _sidecar_dir(path, "backups")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    backup = directory / f"{path.stem}_{stamp}.json"
    shutil.copy2(path, backup)
    return backup


def save_theme_stock_pools(payload: dict[str, Any], path: str | Path | None = None) -> tuple[Path, Path | None]:
    target = theme_stock_pool_path(path)
    payload["updated_at"] = now_iso()
    validate_document(payload)
    backup = _backup(target)
    _atomic_json_write(target, payload)
    return target, backup


def validate_theme_stock_pools(path: str | Path | None = None) -> dict[str, Any]:
    target = theme_stock_pool_path(path)
    payload = load_theme_stock_pools(target)
    pending = confirmed = rejected = locked = 0
    for stock in payload["stocks"].values():
        for assignment in stock.get("assignments", {}).values():
            status = assignment["status"]
            pending += status == "pending"
            confirmed += status == "confirmed"
            rejected += status == "rejected"
            locked += assignment["manual_locked"]
    return {"path": str(target), "theme_count": len(payload["themes"]), "stock_count": len(payload["stocks"]), "batch_count": len(payload.get("batches", {})), "pending": pending, "confirmed": confirmed, "rejected": rejected, "manual_locked": locked}


def read_candidates(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise ThemeStockPoolError(f"候选文件不存在: {source}")
    if source.suffix.lower() == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThemeStockPoolError(f"候选 JSON 格式错误: {source}: {exc}") from exc
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ThemeStockPoolError("候选文件必须是 CSV，或包含 stocks 列表的 JSON")
    return rows


def _truthy(value: Any) -> bool:
    return value is True or _string(value).lower() in {"1", "true", "yes", "y"}


def _candidate_context(row: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    code = normalize_symbol(row.get("ts_code"))
    if not code:
        raise ThemeStockPoolError(f"候选股票代码非法: {row.get('ts_code')!r}")
    current = document["stocks"].get(code, {})
    assignments = current.get("assignments", {})
    existing = [{"theme_id": theme_id, "status": item.get("status")} for theme_id, item in assignments.items()]
    locked = [theme_id for theme_id, item in assignments.items() if item.get("manual_locked")]
    missing = [field for field in ("industry", "latest_limit_up_date", "limit_up_count_120d") if row.get(field) in (None, "")]
    context = {
        "ts_code": code,
        "stock_name": row.get("stock_name") or row.get("name") or current.get("stock_name") or None,
        "industry": row.get("industry") or None,
        "market": row.get("market") or code.split(".")[1],
        "is_st": _truthy(row.get("is_st")),
        "business_summary": row.get("business_summary") or None,
        "company_profile_source": row.get("company_profile_source") or None,
        "latest_limit_up_date": row.get("latest_limit_up_date") or None,
        "limit_up_count_20d": row.get("limit_up_count_20d") or None,
        "limit_up_count_60d": row.get("limit_up_count_60d") or None,
        "limit_up_count_120d": row.get("limit_up_count_120d") or None,
        "recent_limit_up_events": row.get("recent_limit_up_events") if isinstance(row.get("recent_limit_up_events"), list) else [],
        "available_limit_up_reasons": row.get("available_limit_up_reasons") if isinstance(row.get("available_limit_up_reasons"), list) else [],
        "available_concept_tags": row.get("available_concept_tags") if isinstance(row.get("available_concept_tags"), list) else [],
        "existing_assignments": existing,
        "manual_locked_themes": locked,
        "missing_fields": missing,
    }
    return context


def _eligible_candidate(row: dict[str, Any], force: bool) -> bool:
    if force:
        return True
    return _truthy(row.get("eligible_for_chatgpt_classification", True))


def _batch_themes(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for theme_id, theme in document["themes"].items():
        if theme["enabled"]:
            rows.append({"theme_id": theme_id, "name": theme["name"], "definition": theme["definition"], "inclusion_boundary": theme.get("inclusion_boundary", theme["definition"]), "exclusion_boundary": theme.get("exclusion_boundary", "")})
    return rows


def generate_classification_batches(
    candidates: Iterable[dict[str, Any]],
    as_of_date: str,
    output_dir: str | Path,
    path: str | Path | None = None,
    batch_size: int = 25,
    force_symbols: Iterable[str] = (),
) -> list[Path]:
    """Create non-empty handoff batches and register their eligible symbols."""
    if batch_size < 1:
        raise ThemeStockPoolError("batch_size 必须大于 0")
    document = load_theme_stock_pools(path)
    forced = {normalize_symbol(symbol) for symbol in force_symbols}
    registered_codes = {
        code
        for batch in document.get("batches", {}).values()
        for code in batch.get("stock_codes", [])
    }
    selected: list[dict[str, Any]] = []
    for row in candidates:
        code = normalize_symbol(row.get("ts_code"))
        if not code:
            raise ThemeStockPoolError(f"候选股票代码非法: {row.get('ts_code')!r}")
        current = document["stocks"].get(code, {})
        has_open_assignment = any(item.get("status") in {"pending", "confirmed", "rejected"} for item in current.get("assignments", {}).values())
        if code not in forced and (not _eligible_candidate(row, False) or has_open_assignment or code in registered_codes):
            continue
        selected.append(_candidate_context(row, document))
    if not selected:
        return []
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    allowed = _batch_themes(document)
    paths: list[Path] = []
    for start in range(0, len(selected), batch_size):
        stocks = selected[start : start + batch_size]
        number = start // batch_size + 1
        batch_id = f"theme-{as_of_date}-{number:03d}"
        if batch_id in document.get("batches", {}):
            raise ThemeStockPoolError(f"批次已存在，拒绝覆盖: {batch_id}")
        payload = {"schema_version": SCHEMA_VERSION, "batch_id": batch_id, "as_of_date": as_of_date, "generated_at": now_iso(), "classification_purpose": "A股涨停候选主题分类", "allowed_themes": allowed, "stocks": stocks}
        output = target_dir / f"chatgpt_theme_classification_batch_{as_of_date}_{number:03d}.json"
        if output.exists():
            raise ThemeStockPoolError(f"批次文件已存在，拒绝覆盖: {output}")
        _atomic_json_write(output, payload)
        document.setdefault("batches", {})[batch_id] = {"as_of_date": as_of_date, "stock_codes": [row["ts_code"] for row in stocks], "allowed_theme_ids": [theme["theme_id"] for theme in allowed], "path": str(output), "generated_at": payload["generated_at"]}
        paths.append(output)
    save_theme_stock_pools(document, path)
    return paths


def _read_import(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeStockPoolError(f"分类结果 JSON 无法读取: {source}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("stocks"), list):
        raise ThemeStockPoolError("分类结果必须包含 schema_version=1 和 stocks 列表")
    if not _string(payload.get("batch_id")):
        raise ThemeStockPoolError("分类结果缺少 batch_id")
    if payload.get("classifier") != "chatgpt_manual_handoff":
        raise ThemeStockPoolError("分类结果 classifier 必须为 chatgpt_manual_handoff")
    if not _string(payload.get("as_of_date")):
        raise ThemeStockPoolError("分类结果缺少 as_of_date")
    return payload


def _assignment_from_import(item: dict[str, Any], batch_id: str) -> dict[str, Any]:
    reason = _string(item.get("reason"))
    if not reason:
        raise ThemeStockPoolError("分类结果 assignment.reason 不能为空")
    for field, allowed in (("industry_relation", INDUSTRY_RELATIONS), ("market_theme_relation", MARKET_THEME_RELATIONS), ("confidence", CONFIDENCES)):
        if item.get(field) not in allowed:
            raise ThemeStockPoolError(f"分类结果 assignment.{field} 非法: {item.get(field)!r}")
    _validate_evidence(item.get("evidence", []), "分类结果 assignment")
    return {"classification_source": "chatgpt_manual_handoff", "reason": reason, "industry_relation": item["industry_relation"], "market_theme_relation": item["market_theme_relation"], "confidence": item["confidence"], "pool_role": derive_pool_role(item), "status": "pending", "manual_locked": False, "updated_at": now_iso(), "evidence": item.get("evidence", []), "imported_batch_id": batch_id}


def _import_summary(document: dict[str, Any], preview: dict[str, Any]) -> dict[str, int]:
    counts = {f"{status}_{role}": 0 for status in STATUSES for role in POOL_ROLES}
    for stock in document["stocks"].values():
        for assignment in stock.get("assignments", {}).values():
            if not isinstance(assignment, dict) or assignment.get("status") not in STATUSES:
                continue
            counts[f"{assignment['status']}_{assignment_pool_role(assignment)}"] += 1
    for entry in preview["add"]:
        counts[f"pending_{entry['assignment']['pool_role']}"] += 1
    counts.update({
        "conflicts": len(preview["conflicts"]),
        "duplicates": len(preview["skip"]),
        "manual_locked_skipped": len(preview["manual_locked"]),
        "invalid": len(preview["invalid"]),
    })
    return counts


def preview_classification_import(import_path: str | Path, pool_path: str | Path | None = None) -> dict[str, Any]:
    """Validate an import without mutating files and return a complete preview."""
    document = load_theme_stock_pools(pool_path)
    payload = _read_import(import_path)
    batch = document.get("batches", {}).get(payload["batch_id"])
    if not batch:
        raise ThemeStockPoolError(f"未知 batch_id: {payload['batch_id']}")
    if payload["as_of_date"] != batch.get("as_of_date"):
        raise ThemeStockPoolError("分类结果 as_of_date 与批次不一致")
    allowed_codes = set(batch.get("stock_codes", []))
    allowed_themes = set(batch.get("allowed_theme_ids", []))
    preview: dict[str, Any] = {"batch_id": payload["batch_id"], "add": [], "skip": [], "conflicts": [], "manual_locked": [], "invalid": [], "needs_human_attention": []}
    seen_pairs: set[tuple[str, str]] = set()
    for stock in payload["stocks"]:
        if not isinstance(stock, dict):
            preview["invalid"].append({"error": "stocks 项必须是对象"})
            continue
        code = normalize_symbol(stock.get("ts_code"))
        status = stock.get("classification_status")
        if not code or code not in allowed_codes or status not in CLASSIFICATION_STATUSES:
            preview["invalid"].append({"ts_code": stock.get("ts_code"), "error": "股票不属于批次或 classification_status 非法"})
            continue
        if status != "classified":
            preview["needs_human_attention"].append({"ts_code": code, "classification_status": status, "reason": stock.get("attention_reason")})
            continue
        assignments = stock.get("assignments", [])
        if not isinstance(assignments, list) or not assignments:
            preview["invalid"].append({"ts_code": code, "error": "classified 股票必须包含 assignments"})
            continue
        for item in assignments:
            try:
                if not isinstance(item, dict) or item.get("theme_id") not in allowed_themes or item.get("theme_id") not in document["themes"]:
                    raise ThemeStockPoolError("theme_id 不属于批次允许主题")
                theme_id = item["theme_id"]
                if (code, theme_id) in seen_pairs:
                    raise ThemeStockPoolError("同一股票主题关系重复")
                seen_pairs.add((code, theme_id))
                proposed = _assignment_from_import(item, payload["batch_id"])
            except ThemeStockPoolError as exc:
                preview["invalid"].append({"ts_code": code, "theme_id": item.get("theme_id") if isinstance(item, dict) else None, "error": str(exc)})
                continue
            existing = document["stocks"].get(code, {}).get("assignments", {}).get(theme_id)
            if existing and existing.get("manual_locked"):
                preview["manual_locked"].append({"ts_code": code, "theme_id": theme_id})
            elif existing and existing.get("status") == "rejected":
                preview["conflicts"].append({"ts_code": code, "theme_id": theme_id, "error": "人工拒绝关系不可自动写回"})
            elif existing:
                comparable = {key: existing.get(key) for key in ("reason", "industry_relation", "market_theme_relation", "confidence", "status")}
                comparable["pool_role"] = assignment_pool_role(existing)
                wanted = {key: proposed.get(key) for key in comparable}
                bucket = "skip" if comparable == wanted else "conflicts"
                preview[bucket].append({"ts_code": code, "theme_id": theme_id, "error": "重复导入" if bucket == "skip" else "已有未锁定关系内容不同"})
            else:
                preview["add"].append({"ts_code": code, "stock_name": stock.get("stock_name"), "theme_id": theme_id, "assignment": proposed})
    preview["summary"] = _import_summary(document, preview)
    return preview


def _save_raw_import(payload: dict[str, Any], target: Path) -> Path:
    directory = _sidecar_dir(target, "imports")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    output = directory / f"{payload['batch_id']}_{stamp}.json"
    _atomic_json_write(output, payload)
    return output


def import_classification_result(import_path: str | Path, pool_path: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    target = theme_stock_pool_path(pool_path)
    payload = _read_import(import_path)
    preview = preview_classification_import(import_path, target)
    preview["dry_run"] = dry_run
    if dry_run or preview["invalid"]:
        return preview
    document = load_theme_stock_pools(target)
    raw_path = _save_raw_import(payload, target)
    for entry in preview["add"]:
        code = entry["ts_code"]
        stock = document["stocks"].setdefault(code, {"stock_name": entry["stock_name"] or "", "candidate_source": "limit_up", "assignments": {}})
        if entry["stock_name"]:
            stock["stock_name"] = entry["stock_name"]
        stock.setdefault("assignments", {})[entry["theme_id"]] = entry["assignment"]
    saved, backup = save_theme_stock_pools(document, target)
    preview.update({"path": str(saved), "backup_path": str(backup) if backup else None, "raw_import_path": str(raw_path)})
    return preview


def list_pending(pool_path: str | Path | None = None) -> list[dict[str, Any]]:
    document = load_theme_stock_pools(pool_path)
    rows = []
    for code, stock in document["stocks"].items():
        for theme_id, assignment in stock.get("assignments", {}).items():
            if assignment.get("status") == "pending":
                rows.append({"ts_code": code, "stock_name": stock.get("stock_name", ""), "theme_id": theme_id, "theme_name": document["themes"][theme_id]["name"], "reason": assignment.get("reason", ""), "confidence": assignment.get("confidence", "unknown"), "manual_locked": assignment.get("manual_locked", False)})
    return sorted(rows, key=lambda row: (row["theme_id"], row["ts_code"]))


def _change_status(code: str, theme_id: str, status: str, pool_path: str | Path | None = None, reason: str | None = None, pool_role: str | None = None) -> tuple[Path, Path | None]:
    document = load_theme_stock_pools(pool_path)
    code = normalize_symbol(code)
    assignment = document.get("stocks", {}).get(code, {}).get("assignments", {}).get(theme_id)
    if not assignment:
        raise ThemeStockPoolError(f"未找到关系: {code} / {theme_id}")
    if assignment.get("status") != "pending":
        raise ThemeStockPoolError(f"仅可处理 pending 关系: {code} / {theme_id}")
    if assignment.get("manual_locked"):
        raise ThemeStockPoolError(f"关系已被 manual_locked 保护: {code} / {theme_id}")
    if reason is not None:
        if not _string(reason):
            raise ThemeStockPoolError("reason 不能为空")
        assignment["reason"] = _string(reason)
    if pool_role is not None:
        if pool_role not in POOL_ROLES:
            raise ThemeStockPoolError(f"pool_role 非法: {pool_role!r}")
        assignment["pool_role"] = pool_role
    assignment["status"] = status
    assignment["manual_locked"] = True
    assignment["updated_at"] = now_iso()
    return save_theme_stock_pools(document, pool_path)


def confirm_assignment(code: str, theme_id: str, pool_path: str | Path | None = None, reason: str | None = None, pool_role: str | None = None) -> tuple[Path, Path | None]:
    return _change_status(code, theme_id, "confirmed", pool_path, reason, pool_role)


def reject_assignment(code: str, theme_id: str, pool_path: str | Path | None = None, reason: str | None = None) -> tuple[Path, Path | None]:
    return _change_status(code, theme_id, "rejected", pool_path, reason)


def set_assignment_pool_role(code: str, theme_id: str, pool_role: str, pool_path: str | Path | None = None) -> tuple[Path, Path | None]:
    """Manually promote or demote an already confirmed relationship."""
    document = load_theme_stock_pools(pool_path)
    code = normalize_symbol(code)
    assignment = document.get("stocks", {}).get(code, {}).get("assignments", {}).get(theme_id)
    if not assignment:
        raise ThemeStockPoolError(f"未找到关系: {code} / {theme_id}")
    if assignment.get("status") != "confirmed":
        raise ThemeStockPoolError("仅可调整 confirmed 关系的 pool_role")
    if pool_role not in POOL_ROLES:
        raise ThemeStockPoolError(f"pool_role 非法: {pool_role!r}")
    assignment["pool_role"] = pool_role
    assignment["manual_locked"] = True
    assignment["updated_at"] = now_iso()
    return save_theme_stock_pools(document, pool_path)


def revise_pending_assignment(
    code: str,
    theme_id: str,
    pool_role: str,
    industry_relation: str,
    market_theme_relation: str,
    confidence: str,
    reason: str,
    pool_path: str | Path | None = None,
) -> tuple[Path, Path | None]:
    """Apply a reviewed correction and confirm one pending relationship.

    The relation is locked after confirmation so later imports cannot overwrite
    the human-reviewed fields.  A compact immutable-in-practice history entry
    keeps the previous values alongside the applied correction.
    """
    document = load_theme_stock_pools(pool_path)
    code = normalize_symbol(code)
    assignment = document.get("stocks", {}).get(code, {}).get("assignments", {}).get(theme_id)
    if not assignment:
        raise ThemeStockPoolError(f"未找到关系: {code} / {theme_id}")
    if assignment.get("status") != "pending":
        raise ThemeStockPoolError(f"仅可修订 pending 关系: {code} / {theme_id}")
    if assignment.get("manual_locked"):
        raise ThemeStockPoolError(f"关系已被 manual_locked 保护: {code} / {theme_id}")
    for field, value, allowed in (
        ("pool_role", pool_role, POOL_ROLES),
        ("industry_relation", industry_relation, INDUSTRY_RELATIONS),
        ("market_theme_relation", market_theme_relation, MARKET_THEME_RELATIONS),
        ("confidence", confidence, CONFIDENCES),
    ):
        if value not in allowed:
            raise ThemeStockPoolError(f"{field} 非法: {value!r}")
    if not _string(reason):
        raise ThemeStockPoolError("reason 不能为空")

    previous = {
        "pool_role": assignment_pool_role(assignment),
        "industry_relation": assignment.get("industry_relation"),
        "market_theme_relation": assignment.get("market_theme_relation"),
        "confidence": assignment.get("confidence"),
        "reason": assignment.get("reason"),
        "status": assignment.get("status"),
    }
    assignment.update({
        "pool_role": pool_role,
        "industry_relation": industry_relation,
        "market_theme_relation": market_theme_relation,
        "confidence": confidence,
        "reason": _string(reason),
        "status": "confirmed",
        "manual_locked": True,
        "updated_at": now_iso(),
    })
    history = assignment.setdefault("review_history", [])
    if not isinstance(history, list):
        raise ThemeStockPoolError(f"review_history 必须是列表: {code} / {theme_id}")
    history.append({
        "action": "revise_and_confirm",
        "at": assignment["updated_at"],
        "source": "theme_pool_revise",
        "previous": previous,
        "applied": {
            "pool_role": pool_role,
            "industry_relation": industry_relation,
            "market_theme_relation": market_theme_relation,
            "confidence": confidence,
            "reason": assignment["reason"],
            "status": "confirmed",
        },
    })
    return save_theme_stock_pools(document, pool_path)


def add_pending_assignment(
    code: str,
    stock_name: str,
    theme_id: str,
    pool_role: str,
    industry_relation: str,
    market_theme_relation: str,
    confidence: str,
    reason: str,
    source_url: str = "",
    pool_path: str | Path | None = None,
) -> tuple[Path, Path | None]:
    """Create one reusable pending relation without granting confirmation."""
    document = load_theme_stock_pools(pool_path)
    code = normalize_symbol(code)
    if not code or theme_id not in document["themes"]:
        raise ThemeStockPoolError("股票代码或 theme_id 非法")
    if not _string(reason):
        raise ThemeStockPoolError("待审核关系必须提供 reason")
    for field, value, allowed in (
        ("pool_role", pool_role, POOL_ROLES),
        ("industry_relation", industry_relation, INDUSTRY_RELATIONS),
        ("market_theme_relation", market_theme_relation, MARKET_THEME_RELATIONS),
        ("confidence", confidence, CONFIDENCES),
    ):
        if value not in allowed:
            raise ThemeStockPoolError(f"{field} 非法: {value!r}")
    stock = document["stocks"].setdefault(code, {"stock_name": _string(stock_name), "candidate_source": "theme_reclassification", "assignments": {}})
    assignments = stock.setdefault("assignments", {})
    if theme_id in assignments:
        raise ThemeStockPoolError(f"关系已存在: {code} / {theme_id}")
    url = _string(source_url) or None
    assignment = {
        "classification_source": "import",
        "reason": _string(reason),
        "industry_relation": industry_relation,
        "market_theme_relation": market_theme_relation,
        "confidence": confidence,
        "pool_role": pool_role,
        "status": "pending",
        "manual_locked": False,
        "updated_at": now_iso(),
        "evidence": [{
            "evidence_type": "review_handoff",
            "title": "主题池二次审计交接",
            "source_name": "theme_reclassification_20260903",
            "url": url,
            "supports": _string(reason),
        }],
        "review_history": [{
            "action": "add_pending",
            "at": now_iso(),
            "source": "theme_reclassification_20260903",
        }],
    }
    _validate_assignment(theme_id, assignment, "pending")
    stock["stock_name"] = _string(stock_name) or stock.get("stock_name", "")
    assignments[theme_id] = assignment
    return save_theme_stock_pools(document, pool_path)


def add_manual_core_stock(
    code: str,
    stock_name: str,
    theme_id: str,
    reason: str,
    pool_path: str | Path | None = None,
    industry_relation: str = "core",
    market_theme_relation: str = "core",
    confidence: str = "high",
) -> tuple[Path, Path | None]:
    document = load_theme_stock_pools(pool_path)
    code = normalize_symbol(code)
    if not code or theme_id not in document["themes"]:
        raise ThemeStockPoolError("股票代码或 theme_id 非法")
    if not _string(reason):
        raise ThemeStockPoolError("人工核心股票必须提供 reason")
    assignment = {"classification_source": "manual", "reason": _string(reason), "industry_relation": industry_relation, "market_theme_relation": market_theme_relation, "confidence": confidence, "pool_role": "rs_member", "status": "confirmed", "manual_locked": True, "updated_at": now_iso(), "evidence": []}
    _validate_assignment(theme_id, assignment, "manual")
    stock = document["stocks"].setdefault(code, {"stock_name": _string(stock_name), "candidate_source": "manual_core", "assignments": {}})
    existing = stock.setdefault("assignments", {}).get(theme_id)
    if existing and existing.get("manual_locked"):
        raise ThemeStockPoolError(f"关系已被 manual_locked 保护: {code} / {theme_id}")
    stock["stock_name"] = _string(stock_name) or stock.get("stock_name", "")
    stock["candidate_source"] = "manual_core"
    stock["assignments"][theme_id] = assignment
    return save_theme_stock_pools(document, pool_path)
