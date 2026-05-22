"""DatabaseManager 测试"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

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
