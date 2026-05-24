"""DatabaseManager 测试"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from tuv_tools.config.database import DatabaseManager, _extract_standard_number
from tuv_tools.core.chapter.models import ApiConfig


class TestStandardExtraction:
    """标准号提取测试"""

    def test_iec_with_space(self):
        assert _extract_standard_number("IEC 60335-1_2016.docx") == "60335-1"

    def test_iec_with_underscore(self):
        assert _extract_standard_number("IEC_60335-1_test.docx") == "60335-1"

    def test_en_standard(self):
        assert _extract_standard_number("EN_55014-1.docx") == "55014-1"

    def test_ul_standard(self):
        assert _extract_standard_number("UL 1598.docx") == "1598"

    def test_iso_standard(self):
        assert _extract_standard_number("ISO_9001_doc.docx") == "9001"

    def test_gb_standard(self):
        assert _extract_standard_number("GB 4943.1-2022.doc") == "4943.1-2022"

    def test_no_standard(self):
        assert _extract_standard_number("random_document.docx") is None

    def test_empty_filename(self):
        assert _extract_standard_number("") is None


class TestDatabaseManager:
    """DatabaseManager CRUD 测试"""

    @staticmethod
    def _new_db():
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "test.db"
        return DatabaseManager(db_path), db_path

    def test_config_set_get(self):
        db, _ = self._new_db()
        db.set_config("key1", "value1")
        assert db.get_config("key1") == "value1"

    def test_config_missing_default(self):
        db, _ = self._new_db()
        assert db.get_config("nonexistent", "default") == "default"
        assert db.get_config("nonexistent") is None

    def test_config_overwrite(self):
        db, _ = self._new_db()
        db.set_config("key1", "v1")
        db.set_config("key1", "v2")
        assert db.get_config("key1") == "v2"

    def test_clean_rules_save_and_load(self):
        db, _ = self._new_db()
        rules = [
            {"name": "rule_a", "pattern": r"\d+", "sort_order": 0},
            {"name": "rule_b", "pattern": r"[a-z]+", "sort_order": 1},
        ]
        db.save_clean_rules(rules)
        loaded = db.load_clean_rules()
        assert len(loaded) == 2
        assert loaded[0]["name"] == "rule_a"
        assert loaded[0]["sort_order"] == 0

    def test_clean_patterns_compiled(self):
        db, _ = self._new_db()
        db.save_clean_rules([{"name": "digits", "pattern": r"\d+", "sort_order": 0}])
        patterns = db.load_clean_patterns()
        assert len(patterns) == 1
        assert patterns[0].search("abc 123 xyz") is not None

    def test_clean_patterns_empty_pattern_skipped(self):
        db, _ = self._new_db()
        db.save_clean_rules([
            {"name": "empty", "pattern": "", "sort_order": 0},
            {"name": "valid", "pattern": r"\d+", "sort_order": 1},
        ])
        patterns = db.load_clean_patterns()
        assert len(patterns) == 1

    def test_save_clean_rules_rejects_invalid_regex(self):
        db, _ = self._new_db()
        try:
            db.save_clean_rules([{"name": "broken", "pattern": "(", "sort_order": 0}])
        except ValueError as exc:
            assert "Invalid clean rule regex" in str(exc)
        else:
            raise AssertionError("invalid regex should be rejected")

    def test_clean_rules_replace_all(self):
        db, _ = self._new_db()
        db.save_clean_rules([{"name": "r1", "pattern": r"\d+", "sort_order": 0}])
        db.save_clean_rules([{"name": "r2", "pattern": r"[a-z]+", "sort_order": 0}])
        loaded = db.load_clean_rules()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "r2"

    def test_document_add_and_list(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "test.docx")
        doc_id = db.add_document(file_path)
        assert doc_id > 0
        docs = db.get_documents()
        assert len(docs) == 1
        assert docs[0]["file_name"] == "test.docx"
        assert docs[0]["status"] == "pending"

    def test_document_dedup(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "test.docx")
        id1 = db.add_document(file_path)
        id2 = db.add_document(file_path)
        assert id1 == id2
        assert len(db.get_documents()) == 1

    def test_document_update_status(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "test.docx")
        doc_id = db.add_document(file_path)
        db.update_document_status(doc_id, "completed", section_count=42)
        doc = db.get_document(doc_id)
        assert doc["status"] == "completed"
        assert doc["last_section_count"] == 42
        assert doc["last_split_at"] is not None

    def test_document_update_error(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "test.docx")
        doc_id = db.add_document(file_path)
        db.update_document_status(doc_id, "failed", error="File corrupted")
        doc = db.get_document(doc_id)
        assert doc["status"] == "failed"
        assert doc["error_message"] == "File corrupted"

    def test_processing_status_preserves_previous_success_result(self):
        db, _ = self._new_db()
        doc_id = db.add_document(str(Path(__file__).resolve()))
        db.update_document_status(doc_id, "completed", section_count=12)
        completed = db.get_document(doc_id)

        db.update_document_status(doc_id, "processing")
        processing = db.get_document(doc_id)

        assert processing["status"] == "processing"
        assert processing["last_section_count"] == 12
        assert processing["last_split_at"] == completed["last_split_at"]

    def test_pending_status_after_cancel_preserves_previous_success_result_and_clears_error(self):
        db, _ = self._new_db()
        doc_id = db.add_document(str(Path(__file__).resolve()))
        db.update_document_status(doc_id, "completed", section_count=9)
        completed = db.get_document(doc_id)
        db.update_document_status(doc_id, "failed", error="old error")

        db.update_document_status(doc_id, "pending")
        pending = db.get_document(doc_id)

        assert pending["status"] == "pending"
        assert pending["last_section_count"] == 9
        assert pending["last_split_at"] == completed["last_split_at"]
        assert pending["error_message"] is None

    def test_get_preparing_documents_filters_by_status(self):
        db, _ = self._new_db()
        first = db.add_document(str(Path(tempfile.mkdtemp()) / "a.docx"))
        second = db.add_document(str(Path(tempfile.mkdtemp()) / "b.docx"))
        db.update_document_status(first, "preparing")
        db.update_document_status(second, "failed", error="x")

        docs = db.get_preparing_documents()

        assert [doc["id"] for doc in docs] == [first]

    def test_update_documents_status_applies_same_transition_to_many_rows(self):
        db, _ = self._new_db()
        first = db.add_document(str(Path(tempfile.mkdtemp()) / "a.docx"))
        second = db.add_document(str(Path(tempfile.mkdtemp()) / "b.docx"))

        db.update_documents_status([first, second], "prepare_paused")

        first_doc = db.get_document(first)
        second_doc = db.get_document(second)
        assert first_doc["status"] == "prepare_paused"
        assert second_doc["status"] == "prepare_paused"

    def test_document_delete(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "test.docx")
        doc_id = db.add_document(file_path)
        db.delete_document(doc_id)
        assert len(db.get_documents()) == 0

    def test_document_standard_number(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "IEC_60335-1.docx")
        doc_id = db.add_document(file_path)
        doc = db.get_document(doc_id)
        assert doc["standard_number"] == "60335-1"

    def test_rsa_key_save_and_load(self):
        db, _ = self._new_db()
        assert db.load_rsa_private_key() is None
        db.save_rsa_private_key("PRIVATE_KEY_DATA")
        assert db.load_rsa_private_key() == "PRIVATE_KEY_DATA"
        db.save_rsa_private_key("NEW_KEY")
        assert db.load_rsa_private_key() == "NEW_KEY"

    def test_api_config_can_clear_saved_rsa_key(self):
        db, _ = self._new_db()
        db.save_api_config(ApiConfig(username="admin", rsa_private_key="KEY123"))
        assert db.load_rsa_private_key() == "KEY123"

        db.save_api_config(ApiConfig(username="admin", rsa_private_key=""))

        loaded = db.load_api_config()
        assert loaded is not None
        assert loaded.rsa_private_key == ""
        assert db.load_rsa_private_key() is None

    def test_api_config_roundtrip(self):
        db, _ = self._new_db()
        cfg = ApiConfig(
            base_url="http://localhost:8080",
            username="admin",
            password="secret",
            rsa_private_key="KEY123",
            token_idle_timeout=3600,
        )
        db.save_api_config(cfg)
        loaded = db.load_api_config()
        assert loaded is not None
        assert loaded.base_url == "http://localhost:8080"
        assert loaded.username == "admin"
        assert loaded.password == "secret"
        assert loaded.rsa_private_key == "KEY123"
        assert loaded.token_idle_timeout == 3600

    def test_api_config_no_key_returns_none(self):
        db, _ = self._new_db()
        assert db.load_api_config() is None

    def test_close_and_reopen(self):
        """测试关闭后重新打开，数据持久化"""
        db, db_path = self._new_db()
        db.set_config("persist", "yes")
        db.save_clean_rules([{"name": "r", "pattern": r"\d+", "sort_order": 0}])
        db.close()

        db2 = DatabaseManager(db_path)
        assert db2.get_config("persist") == "yes"
        assert len(db2.load_clean_rules()) == 1
        db2.close()

    def test_migration_retries_when_any_legacy_source_fails(self, tmp_path):
        project_root = tmp_path
        rules_path = project_root / "resources" / "inline_clean_rules.json"
        rules_path.parent.mkdir()
        rules_path.write_text(
            json.dumps({"inline_clean_rules": [{"name": "digits", "pattern": r"\d+"}]}),
            encoding="utf-8",
        )
        api_path = project_root / "api_config.json"
        api_path.write_text("{bad json", encoding="utf-8")
        key_path = project_root / "rsa_private.key"
        db_path = tmp_path / "test.db"

        with patch("tuv_tools.config.settings.PROJECT_ROOT", project_root), \
             patch("tuv_tools.config.settings.API_CONFIG_FILE", api_path), \
             patch("tuv_tools.config.settings.RSA_KEY_FILE", key_path):
            db = DatabaseManager(db_path)

        assert db.get_config("migrated_from_legacy") is None
        assert api_path.exists()

        api_path.write_text(json.dumps({"username": "admin"}), encoding="utf-8")
        with patch("tuv_tools.config.settings.PROJECT_ROOT", project_root), \
             patch("tuv_tools.config.settings.API_CONFIG_FILE", api_path), \
             patch("tuv_tools.config.settings.RSA_KEY_FILE", key_path):
            db._migrate_old_files()

        assert db.get_config("migrated_from_legacy") == "1"
        assert db.get_config("api.username") == "admin"
