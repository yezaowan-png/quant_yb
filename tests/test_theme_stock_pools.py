import json
import tempfile
import unittest
from pathlib import Path

from analysis.theme_stock_pools import (
    ThemeStockPoolError,
    add_pending_assignment,
    add_manual_core_stock,
    confirm_assignment,
    generate_classification_batches,
    import_classification_result,
    list_pending,
    load_theme_stock_pools,
    reject_assignment,
    revise_pending_assignment,
    set_assignment_pool_role,
    validate_theme_stock_pools,
)


def _document() -> dict:
    return {
        "version": 1,
        "updated_at": "2026-09-02T00:00:00+08:00",
        "themes": {
            "ai_power": {"name": "AI电源", "enabled": True, "definition": "数据中心电源"},
            "energy_storage": {"name": "储能", "enabled": True, "definition": "储能系统"},
        },
        "stocks": {},
        "batches": {},
    }


def _import_result(batch_id: str, code: str = "000001.SZ", theme_id: str = "ai_power") -> dict:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "as_of_date": "20260902",
        "classifier": "chatgpt_manual_handoff",
        "classified_at": "2026-09-02T20:00:00+08:00",
        "stocks": [{
            "ts_code": code,
            "stock_name": "甲",
            "classification_status": "classified",
            "assignments": [{
                "theme_id": theme_id,
                "industry_relation": "direct",
                "market_theme_relation": "active",
                "confidence": "medium",
                "reason": "公司披露数据中心电源产品。",
                "evidence": [{"evidence_type": "company_disclosure", "title": "公告", "source_name": "公司", "url": None, "published_date": "2026-08-20", "supports": "支持数据中心电源业务"}],
            }],
        }],
    }


class ThemeStockPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pool = self.root / "theme_stock_pools.json"
        self.pool.write_text(json.dumps(_document(), ensure_ascii=False), encoding="utf-8")
        self.batch_dir = self.root / "batches"
        self.candidates = [{
            "ts_code": "000001.SZ", "stock_name": "甲", "industry": "电气设备", "eligible_for_chatgpt_classification": True,
            "latest_limit_up_date": "20260901", "limit_up_count_20d": 1, "limit_up_count_60d": 2, "limit_up_count_120d": 3,
        }]

    def tearDown(self):
        self.tmp.cleanup()

    def test_batch_is_non_empty_and_registers_known_stock(self):
        paths = generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        self.assertEqual(len(paths), 1)
        batch = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual(batch["stocks"][0]["ts_code"], "000001.SZ")
        self.assertIn("theme-20260902-001", load_theme_stock_pools(self.pool)["batches"])
        self.assertEqual(generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool), [])

    def test_import_dry_run_does_not_write_and_real_import_keeps_raw_sidecar(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        before = self.pool.read_text(encoding="utf-8")
        dry = import_classification_result(response, self.pool, dry_run=True)
        self.assertEqual(len(dry["add"]), 1)
        self.assertEqual(dry["summary"]["pending_rs_member"], 1)
        self.assertEqual(dry["summary"]["pending_watch_only"], 0)
        self.assertEqual(self.pool.read_text(encoding="utf-8"), before)
        result = import_classification_result(response, self.pool)
        self.assertTrue(Path(result["raw_import_path"]).exists())
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertEqual(len(list_pending(self.pool)), 1)
        self.assertEqual(import_classification_result(response, self.pool)["add"], [])

    def test_legacy_import_role_derivation_prefers_watch_only(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        payload = _import_result("theme-20260902-001")
        payload["stocks"][0]["assignments"][0]["industry_relation"] = "indirect"
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        preview = import_classification_result(response, self.pool, dry_run=True)
        self.assertEqual(preview["add"][0]["assignment"]["pool_role"], "watch_only")
        self.assertEqual(preview["summary"]["pending_watch_only"], 1)

        payload["stocks"][0]["assignments"][0]["industry_relation"] = "direct"
        payload["stocks"][0]["assignments"][0]["market_theme_relation"] = "catalyst"
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        preview = import_classification_result(response, self.pool, dry_run=True)
        self.assertEqual(preview["add"][0]["assignment"]["pool_role"], "watch_only")

    def test_manual_locked_role_is_not_overwritten_by_reimport(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        confirm_assignment("000001.SZ", "ai_power", self.pool, pool_role="watch_only")
        preview = import_classification_result(response, self.pool, dry_run=True)
        self.assertEqual(preview["manual_locked"], [{"ts_code": "000001.SZ", "theme_id": "ai_power"}])
        assignment = load_theme_stock_pools(self.pool)["stocks"]["000001.SZ"]["assignments"]["ai_power"]
        self.assertEqual(assignment["pool_role"], "watch_only")
        self.assertTrue(assignment["manual_locked"])

    def test_confirmed_role_can_be_manually_promoted_or_demoted(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        confirm_assignment("000001.SZ", "ai_power", self.pool, pool_role="watch_only")
        set_assignment_pool_role("000001.SZ", "ai_power", "rs_member", self.pool)
        assignment = load_theme_stock_pools(self.pool)["stocks"]["000001.SZ"]["assignments"]["ai_power"]
        self.assertEqual(assignment["status"], "confirmed")
        self.assertEqual(assignment["pool_role"], "rs_member")
        self.assertTrue(assignment["manual_locked"])

    def test_revise_pending_updates_all_reviewed_fields_and_locks_history(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        revise_pending_assignment(
            "000001.SZ", "ai_power", "watch_only", "indirect", "catalyst", "low", "二次审计：仅观察", self.pool
        )
        assignment = load_theme_stock_pools(self.pool)["stocks"]["000001.SZ"]["assignments"]["ai_power"]
        self.assertEqual(assignment["status"], "confirmed")
        self.assertTrue(assignment["manual_locked"])
        self.assertEqual(assignment["pool_role"], "watch_only")
        self.assertEqual(assignment["industry_relation"], "indirect")
        self.assertEqual(assignment["market_theme_relation"], "catalyst")
        self.assertEqual(assignment["confidence"], "low")
        self.assertEqual(assignment["review_history"][0]["action"], "revise_and_confirm")
        with self.assertRaises(ThemeStockPoolError):
            revise_pending_assignment(
                "000001.SZ", "ai_power", "rs_member", "core", "core", "high", "不应覆盖", self.pool
            )

    def test_add_pending_assignment_keeps_relation_reviewable_and_rejects_duplicate(self):
        add_pending_assignment(
            "600001.SH", "候选", "ai_power", "rs_member", "core", "core", "high", "待人工确认", "https://example.com", self.pool
        )
        assignment = load_theme_stock_pools(self.pool)["stocks"]["600001.SH"]["assignments"]["ai_power"]
        self.assertEqual(assignment["status"], "pending")
        self.assertFalse(assignment["manual_locked"])
        self.assertEqual(assignment["evidence"][0]["url"], "https://example.com")
        with self.assertRaises(ThemeStockPoolError):
            add_pending_assignment(
                "600001.SH", "候选", "ai_power", "rs_member", "core", "core", "high", "重复", pool_path=self.pool
            )

    def test_pending_manual_lock_blocks_confirm_reject_and_revise(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        document = load_theme_stock_pools(self.pool)
        document["stocks"]["000001.SZ"]["assignments"]["ai_power"]["manual_locked"] = True
        self.pool.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ThemeStockPoolError):
            confirm_assignment("000001.SZ", "ai_power", self.pool)
        with self.assertRaises(ThemeStockPoolError):
            reject_assignment("000001.SZ", "ai_power", self.pool)
        with self.assertRaises(ThemeStockPoolError):
            revise_pending_assignment(
                "000001.SZ", "ai_power", "rs_member", "core", "core", "high", "不应覆盖", self.pool
            )

    def test_multi_theme_confirm_and_manual_lock_protect_import(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        payload = _import_result("theme-20260902-001")
        payload["stocks"][0]["assignments"].append({**payload["stocks"][0]["assignments"][0], "theme_id": "energy_storage", "reason": "储能电源系统业务。"})
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        confirm_assignment("000001.SZ", "ai_power", self.pool)
        doc = load_theme_stock_pools(self.pool)
        self.assertEqual(doc["stocks"]["000001.SZ"]["assignments"]["ai_power"]["status"], "confirmed")
        self.assertTrue(doc["stocks"]["000001.SZ"]["assignments"]["ai_power"]["manual_locked"])
        preview = import_classification_result(response, self.pool, dry_run=True)
        self.assertEqual(preview["manual_locked"], [{"ts_code": "000001.SZ", "theme_id": "ai_power"}])
        self.assertEqual(len(doc["stocks"]["000001.SZ"]["assignments"]), 2)

    def test_reject_blocks_writeback_and_manual_core_can_be_multi_theme(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        response.write_text(json.dumps(_import_result("theme-20260902-001"), ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        reject_assignment("000001.SZ", "ai_power", self.pool, "人工拒绝")
        self.assertEqual(import_classification_result(response, self.pool, dry_run=True)["manual_locked"][0]["theme_id"], "ai_power")
        add_manual_core_stock("600001.SH", "核心", "ai_power", "人工确认核心业务", self.pool)
        add_manual_core_stock("600001.SH", "核心", "energy_storage", "人工确认储能业务", self.pool)
        doc = load_theme_stock_pools(self.pool)
        self.assertEqual(set(doc["stocks"]["600001.SH"]["assignments"]), {"ai_power", "energy_storage"})
        self.assertEqual(validate_theme_stock_pools(self.pool)["confirmed"], 2)

    def test_invalid_import_is_rejected_without_writing(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "bad.json"
        payload = _import_result("theme-20260902-001", theme_id="unknown_theme")
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = import_classification_result(response, self.pool)
        self.assertEqual(len(result["invalid"]), 1)
        self.assertFalse((self.root / "theme_stock_pools_imports").exists())
        self.assertEqual(load_theme_stock_pools(self.pool)["stocks"], {})

    def test_import_rejects_wrong_batch_date_and_non_pending_confirmation(self):
        generate_classification_batches(self.candidates, "20260902", self.batch_dir, self.pool)
        response = self.root / "response.json"
        payload = _import_result("theme-20260902-001")
        payload["as_of_date"] = "20260901"
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ThemeStockPoolError):
            import_classification_result(response, self.pool, dry_run=True)
        payload["as_of_date"] = "20260902"
        response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_classification_result(response, self.pool)
        confirm_assignment("000001.SZ", "ai_power", self.pool)
        with self.assertRaises(ThemeStockPoolError):
            confirm_assignment("000001.SZ", "ai_power", self.pool)

    def test_invalid_document_rejects_missing_confirmed_reason(self):
        bad = _document()
        bad["stocks"] = {"000001.SZ": {"assignments": {"ai_power": {"classification_source": "manual", "reason": "", "industry_relation": "core", "market_theme_relation": "core", "confidence": "high", "status": "confirmed", "manual_locked": True}}}}
        self.pool.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ThemeStockPoolError):
            load_theme_stock_pools(self.pool)
