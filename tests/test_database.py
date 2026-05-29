"""DatabaseManager 测试"""

from __future__ import annotations

import json
import codecs
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.config.database import DatabaseManager, _extract_standard_number
from tuv_tools.config.settings import AppSettings
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

    def test_non_gb_prefix_does_not_truncate_generic_standard(self):
        assert _extract_standard_number("QMF-OR-31057 NGB 60335-2-35.doc.docx") == "60335-2-35"

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

    def test_api_config_persists_ca_certificate_path(self):
        db, _ = self._new_db()
        config = ApiConfig(
            base_url="https://example.com",
            username="admin",
            password="secret",
            rsa_private_key="rsa",
            ca_cert_file="C:/certs/root.pem",
        )

        db.save_api_config(config)
        loaded = db.load_api_config()

        assert loaded is not None
        assert loaded.ca_cert_file == "C:/certs/root.pem"

    def test_app_settings_copy_ca_cert_to_app_data_stores_relative_path(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        settings.ensure_app_data_root_ready()
        source_cert = tmp_path / "root.pem"
        source_cert.write_text("pem-data", encoding="utf-8")

        stored = settings.copy_ca_cert_to_app_data(source_cert)

        assert stored == "certs/root.pem"
        assert (settings.get_app_data_root() / "certs" / "root.pem").read_text(encoding="utf-8") == "pem-data"

    def test_app_settings_default_checkbox_bas_falls_back_to_repo_resources(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)

        default_bas_path = settings.get_default_checkbox_bas_path()

        assert default_bas_path.exists()
        assert default_bas_path.name == "unify_checkboxes.bas"
        assert default_bas_path.parent == settings.get_app_data_preparing_root()

    def test_app_settings_copy_checkbox_bas_to_app_data_stores_relative_path(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        settings.ensure_app_data_root_ready()
        source_bas = tmp_path / "custom.bas"
        source_bas.write_text("Attribute VB_Name = \"Module1\"", encoding="utf-8")

        stored = settings.copy_checkbox_bas_to_app_data(source_bas)

        assert stored == "preparing/custom.bas"
        assert (settings.get_app_data_root() / "preparing" / "custom.bas").read_text(encoding="utf-8") == source_bas.read_text(encoding="utf-8")

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

    def test_document_batch_delete(self):
        db, _ = self._new_db()
        first = db.add_document(str(Path(tempfile.mkdtemp()) / "first.docx"))
        second = db.add_document(str(Path(tempfile.mkdtemp()) / "second.docx"))
        third = db.add_document(str(Path(tempfile.mkdtemp()) / "third.docx"))

        db.delete_documents([first, third])

        assert db.get_document(first) is None
        assert db.get_document(third) is None
        assert db.get_document(second) is not None

    def test_document_standard_number(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "IEC_60335-1.docx")
        doc_id = db.add_document(file_path)
        doc = db.get_document(doc_id)
        assert doc["standard_number"] == "60335-1"

    def test_add_document_prefers_explicit_standard_number(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "unknown.docx")

        doc_id = db.add_document(file_path, standard_number="60335-2-35")

        doc = db.get_document(doc_id)
        assert doc is not None
        assert doc["standard_number"] == "60335-2-35"

    def test_update_document_standard_number(self):
        db, _ = self._new_db()
        file_path = str(Path(tempfile.mkdtemp()) / "unknown.docx")
        doc_id = db.add_document(file_path)

        db.update_document_standard_number(doc_id, "60335-2-35")

        doc = db.get_document(doc_id)
        assert doc is not None
        assert doc["standard_number"] == "60335-2-35"

    def test_batch_import_schema_created_with_required_indexes(self):
        db, _ = self._new_db()

        table_rows = db._conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'batch_import_%'
            ORDER BY name
            """
        ).fetchall()
        index_rows = db._conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index' AND tbl_name LIKE 'batch_import_%'
            ORDER BY name
            """
        ).fetchall()

        assert [row["name"] for row in table_rows] == [
            "batch_import_clauses",
            "batch_import_documents",
            "batch_import_events",
        ]
        assert {
            row["name"] for row in index_rows
        } >= {
            "idx_batch_import_clauses_document_id",
            "idx_batch_import_clauses_status",
            "idx_batch_import_documents_status",
            "idx_batch_import_documents_updated_at",
            "idx_batch_import_events_document_id",
            "idx_batch_import_events_occurred_at",
        }

    def test_batch_import_document_table_contains_workspace_fields(self):
        db, _ = self._new_db()

        cols = {
            row["name"]
            for row in db._conn.execute("PRAGMA table_info(batch_import_documents)").fetchall()
        }

        assert {
            "file_path",
            "file_name",
            "file_fingerprint",
            "document_status",
            "split_mode",
            "standard",
            "folder_id",
            "folder_name",
            "product_type",
            "plan_sr",
            "standard_version",
            "chapter_version",
            "specific_product",
            "total_clause_count",
            "success_clause_count",
            "failed_clause_count",
            "skipped_clause_count",
            "is_queued",
            "queue_order",
            "last_error",
        }.issubset(cols)

    def test_batch_import_clause_table_contains_clause_fields(self):
        db, _ = self._new_db()

        cols = {
            row["name"]
            for row in db._conn.execute("PRAGMA table_info(batch_import_clauses)").fetchall()
        }

        assert {
            "document_id",
            "sort_index",
            "term",
            "test_content",
            "clause_status",
            "chapter_id",
            "backend_chapter_status",
            "source_docx_path",
            "duplicate_flag",
            "duplicate_reason",
            "user_decision",
            "create_error",
            "upload_error",
            "last_action",
        }.issubset(cols)

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

    def test_app_settings_defaults_app_data_root_to_project_dot_dir(self):
        settings = AppSettings()

        assert settings.get_app_data_root() == settings.project_root / ".tuv-tools"
        assert settings.get_database_path() == settings.project_root / ".tuv-tools" / "tuv-tools.db"
        assert settings.get_chapter_batch_root() == settings.project_root / ".tuv-tools" / "chapter-batch"

    def test_app_settings_defaults_splitter_output_root_to_project_doc_output(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)

        assert settings.get_default_splitter_output_root() == project_root / "doc_output"
        assert settings.get_splitter_output_root("") == project_root / "doc_output"

    def test_app_settings_normalizes_splitter_output_root_relative_to_project(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)

        assert settings.normalize_splitter_output_path(project_root / "doc_output") == "doc_output"
        assert settings.normalize_splitter_output_path(project_root / "nested" / "out") == "nested/out"

    def test_app_settings_does_not_persist_bootstrap_for_default_app_data_root(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)

        settings.set_app_data_root(project_root / ".tuv-tools")

        assert not (project_root / ".tuv-tools-config.json").exists()

    def test_resolve_resources_dir_prefers_meipass_when_frozen(self, tmp_path):
        runtime_root = tmp_path / "dist"
        runtime_root.mkdir(parents=True)
        bundled_root = tmp_path / "bundle"
        (bundled_root / "resources").mkdir(parents=True)

        with patch("tuv_tools.config.settings.sys.frozen", True, create=True), \
             patch("tuv_tools.config.settings.sys.executable", str(runtime_root / "TUV项目文档工具.exe")), \
             patch("tuv_tools.config.settings.sys._MEIPASS", str(bundled_root), create=True):
            from tuv_tools.config import settings as settings_module

            assert settings_module._find_project_root() == runtime_root.resolve()
            assert settings_module._resolve_resources_dir(runtime_root) == (bundled_root / "resources").resolve()

    def test_app_settings_reads_explicit_app_data_root_from_bootstrap_file(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        bootstrap_path = project_root / ".tuv-tools-config.json"
        data_root = tmp_path / "custom-root"
        bootstrap_path.write_text(
            json.dumps({"appDataRoot": str(data_root)}, ensure_ascii=False),
            encoding="utf-8",
        )

        settings = AppSettings(project_root=project_root)

        assert settings.get_app_data_root() == data_root
        assert settings.get_database_path() == data_root / "tuv-tools.db"
        assert settings.get_chapter_batch_root() == data_root / "chapter-batch"

    def test_app_settings_reads_explicit_splitter_output_root_from_bootstrap_file(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        bootstrap_path = project_root / ".tuv-tools-config.json"
        output_root = tmp_path / "custom-output"
        bootstrap_path.write_text(
            json.dumps({"splitterOutputRoot": str(output_root)}, ensure_ascii=False),
            encoding="utf-8",
        )

        settings = AppSettings(project_root=project_root)

        assert settings.get_default_splitter_output_root() == output_root

    def test_app_settings_reads_utf8_bom_bootstrap_file(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        bootstrap_path = project_root / ".tuv-tools-config.json"
        output_root = tmp_path / "custom-output"
        bootstrap_path.write_bytes(
            codecs.BOM_UTF8 + json.dumps(
                {"splitterOutputRoot": str(output_root)},
                ensure_ascii=False,
            ).encode("utf-8")
        )

        settings = AppSettings(project_root=project_root)

        assert settings.get_default_splitter_output_root() == output_root

    def test_app_settings_persists_explicit_app_data_root_to_bootstrap_file(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        target_root = tmp_path / "workspace-data"

        settings.set_app_data_root(target_root)

        bootstrap = json.loads((project_root / ".tuv-tools-config.json").read_text(encoding="utf-8"))
        assert bootstrap == {"appDataRoot": str(target_root)}
        assert settings.get_app_data_root() == target_root

    def test_app_settings_preserves_splitter_output_root_when_app_data_root_changes(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        bootstrap_path = project_root / ".tuv-tools-config.json"
        output_root = tmp_path / "custom-output"
        bootstrap_path.write_text(
            json.dumps(
                {
                    "appDataRoot": str(tmp_path / "initial-data"),
                    "splitterOutputRoot": str(output_root),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        settings = AppSettings(project_root=project_root)

        target_root = tmp_path / "workspace-data"
        settings.set_app_data_root(target_root)

        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        assert bootstrap == {
            "appDataRoot": str(target_root),
            "splitterOutputRoot": str(output_root),
        }
        assert settings.get_default_splitter_output_root() == output_root

    def test_app_settings_seeds_packaging_defaults_into_fresh_app_data_root(self, tmp_path):
        project_root = tmp_path / "repo"
        defaults_dir = project_root / "resources" / "defaults"
        defaults_dir.mkdir(parents=True)
        (defaults_dir / "api_config.json").write_text(
            json.dumps(
                {
                    "base_url": "https://seed.example.com",
                    "username": "",
                    "password": "",
                    "ca_cert_file": "default-ca.pem",
                    "token_cache_file": ".token_cache",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (defaults_dir / "inline_clean_rules.json").write_text(
            json.dumps(
                {
                    "inline_clean_rules": [
                        {"name": "Rule A", "pattern": "foo", "sort_order": 0},
                        {"name": "Rule B", "pattern": "bar", "sort_order": 1},
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (defaults_dir / "rsa_private.key").write_text("KEY123", encoding="utf-8")
        (defaults_dir / "default-ca.pem").write_text("fake-ca", encoding="utf-8")

        settings = AppSettings(project_root=project_root)

        app_data_root = settings.ensure_app_data_root_ready()
        loaded = settings.load_api_config()
        db = DatabaseManager(settings.get_database_path())

        assert app_data_root == project_root / ".tuv-tools"
        assert loaded is not None
        assert loaded.base_url == "https://seed.example.com"
        assert loaded.ca_cert_file == str(app_data_root / "certs" / "default-ca.pem")
        assert db.load_rsa_private_key() == "KEY123"
        assert len(db.load_clean_rules()) == 2
        assert (app_data_root / "certs" / "default-ca.pem").read_text(encoding="utf-8") == "fake-ca"

    def test_app_settings_save_api_config_uses_project_database(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        settings.ensure_app_data_root_ready()

        settings.save_api_config(
            ApiConfig(
                base_url="http://localhost:8080",
                username="admin",
                password="secret",
                rsa_private_key="KEY123",
                token_cache_file=str(tmp_path / "pytest-temp" / ".token_cache"),
            )
        )

        db = DatabaseManager(settings.get_database_path())
        loaded = db.load_api_config()

        assert settings.get_database_path().exists()
        assert loaded is not None
        assert loaded.base_url == "http://localhost:8080"
        assert loaded.username == "admin"
        assert loaded.password == "secret"
        assert loaded.rsa_private_key == "KEY123"
        assert loaded.token_cache_file == ".token_cache"

    def test_app_settings_rebases_legacy_absolute_token_cache_to_current_data_root(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        settings.ensure_app_data_root_ready()
        legacy_cache = tmp_path / "pytest-temp" / ".token_cache"

        db = DatabaseManager(settings.get_database_path())
        db.save_api_config(
            ApiConfig(
                base_url="http://localhost:8080",
                username="admin",
                password="secret",
                rsa_private_key="KEY123",
                token_cache_file=str(legacy_cache),
            )
        )

        loaded = settings.load_api_config()

        assert loaded is not None
        assert loaded.token_cache_file == str(settings.get_app_data_root() / ".token_cache")

    def test_migrate_user_home_data_root_copies_required_data_and_removes_old_root(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        old_root = tmp_path / "old-home" / ".tuv-tools"
        new_root = project_root / ".tuv-tools"
        old_root.mkdir(parents=True)
        (old_root / "certs").mkdir(parents=True)
        (old_root / "preparing").mkdir(parents=True)
        (old_root / "chapter-batch" / "42").mkdir(parents=True)
        (old_root / "chapter-batch" / "42" / "clauses_docx").mkdir(parents=True)
        (old_root / "chapter-batch" / "42" / "clauses_docx" / "10_1.docx").write_text("docx", encoding="utf-8")
        (old_root / "certs" / "ca.pem").write_text("pem", encoding="utf-8")
        (old_root / "preparing" / "unify_checkboxes.bas").write_text("Attribute VB_Name = \"Module1\"", encoding="utf-8")
        (old_root / ".token_cache").write_text(json.dumps({"token": "abc"}), encoding="utf-8")
        shutil.copyfile(tmp_path / "seed.db", tmp_path / "seed.db") if False else None
        (old_root / "tuv-tools.db").write_text("db-bytes", encoding="utf-8")

        settings = AppSettings(project_root=project_root)

        migrated = settings.migrate_legacy_app_data_root(legacy_root=old_root)

        assert migrated is True
        assert (new_root / "tuv-tools.db").exists()
        assert (new_root / ".token_cache").exists()
        assert (new_root / "certs" / "ca.pem").exists()
        assert (new_root / "preparing" / "unify_checkboxes.bas").exists()
        assert (new_root / "chapter-batch" / "42" / "clauses_docx" / "10_1.docx").exists()
        assert not old_root.exists()

    def test_migrate_user_home_data_root_keeps_old_root_when_validation_fails(self, tmp_path):
        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        old_root = tmp_path / "old-home" / ".tuv-tools"
        old_root.mkdir(parents=True)
        (old_root / ".token_cache").write_text(json.dumps({"token": "abc"}), encoding="utf-8")

        settings = AppSettings(project_root=project_root)

        migrated = settings.migrate_legacy_app_data_root(
            legacy_root=old_root,
            required_files=("tuv-tools.db",),
        )

        assert migrated is False
        assert old_root.exists()

    def test_pyinstaller_spec_uses_specpath_without_dunder_file(self):
        spec_path = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "tuv-tools.spec"
        calls: dict[str, object] = {}
        collected_packages: list[str] = []
        preferred_runtime_binaries = {
            "libssl-3-x64.dll": (
                "libssl-3-x64.dll",
                "C:/fake/build_env/Library/bin/libssl-3-x64.dll",
                "BINARY",
            ),
            "libcrypto-3-x64.dll": (
                "libcrypto-3-x64.dll",
                "C:/fake/build_env/Library/bin/libcrypto-3-x64.dll",
                "BINARY",
            ),
        }

        def fake_analysis(*args, **kwargs):
            calls["analysis"] = {"args": args, "kwargs": kwargs}
            return SimpleNamespace(
                pure="pure",
                scripts="scripts",
                binaries=[
                    ("icuuc.dll", "C:/fake/icuuc.dll", "BINARY"),
                    ("Qt6Core.dll", "C:/fake/Qt6Core.dll", "BINARY"),
                    ("icudt73.dll", "C:/fake/icudt73.dll", "BINARY"),
                    ("libssl-3-x64.dll", "C:/fake/base/libssl-3-x64.dll", "BINARY"),
                    ("libcrypto-3-x64.dll", "C:/fake/base/libcrypto-3-x64.dll", "BINARY"),
                ],
                datas="datas",
            )

        def fake_pyz(*args, **kwargs):
            calls["pyz"] = {"args": args, "kwargs": kwargs}
            return "pyz"

        def fake_exe(*args, **kwargs):
            calls["exe"] = {"args": args, "kwargs": kwargs}
            return "exe"

        def fake_collect(*args, **kwargs):
            calls["collect"] = {"args": args, "kwargs": kwargs}
            return "collect"

        def fake_collect_dynamic_libs(package: str):
            collected_packages.append(package)
            return [(f"C:/fake/{package}.dll", package)]

        namespace = {
            "__name__": "__main__",
            "SPEC": str(spec_path),
            "SPECPATH": str(spec_path.parent),
            "Analysis": fake_analysis,
            "PYZ": fake_pyz,
            "EXE": fake_exe,
            "COLLECT": fake_collect,
            "TOC": list,
            "collect_dynamic_libs": fake_collect_dynamic_libs,
            "_collect_preferred_runtime_binaries": lambda: preferred_runtime_binaries,
        }

        exec(compile(spec_path.read_bytes(), str(spec_path), "exec"), namespace)

        repo_root = spec_path.parents[2]
        analysis_call = calls["analysis"]
        assert collected_packages == ["PySide6", "shiboken6"]
        assert analysis_call["args"][0] == [str(repo_root / "main.py")]
        assert analysis_call["kwargs"]["pathex"] == [str(repo_root), str(repo_root / "src")]
        assert analysis_call["kwargs"]["binaries"] == [
            ("C:/fake/PySide6.dll", "PySide6"),
            ("C:/fake/shiboken6.dll", "shiboken6"),
        ]
        assert analysis_call["kwargs"]["datas"] == [(str(repo_root / "resources"), "resources")]
        assert calls["exe"]["kwargs"]["name"] == "TUV项目文档工具"
        assert calls["collect"]["kwargs"]["name"] == "TUV-Project-Document-Tool"
        assert calls["collect"]["args"][1] == [
            ("Qt6Core.dll", "C:/fake/Qt6Core.dll", "BINARY"),
            preferred_runtime_binaries["libssl-3-x64.dll"],
            preferred_runtime_binaries["libcrypto-3-x64.dll"],
        ]
