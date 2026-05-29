"""SplitterView 的最小视图级回归测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from tuv_tools.config import database as db_module
from tuv_tools.ui.views.splitter_view import SplitterView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSplitterView:
    @staticmethod
    def _use_temp_db(monkeypatch, tmp_path):
        db_module.DatabaseManager._instance = None
        db_module.DatabaseManager._initialized = False
        monkeypatch.setattr(
            "tuv_tools.config.settings.AppSettings.get_database_path",
            lambda self: tmp_path / "test.db",
        )

    def test_dropped_files_reuse_add_paths_flow(self, qapp, monkeypatch):
        captured: list[list[str]] = []

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(SplitterView, "_add_paths", lambda self, paths: captured.append(paths))

        view = SplitterView()
        view._table.files_dropped.emit(["a.docx", "b.docx"])

        assert captured == [["a.docx", "b.docx"]]

    def test_add_paths_uses_preflight_standard_overrides_before_insert(self, qapp, monkeypatch, tmp_path):
        self._use_temp_db(monkeypatch, tmp_path)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)
        monkeypatch.setattr(
            "tuv_tools.ui.views.splitter_view.resolve_standard_number_overrides",
            lambda *args, **kwargs: {str((tmp_path / "unknown.docx").resolve()): "60335-2-35"},
            raising=False,
        )

        path = tmp_path / "unknown.docx"
        path.write_text("x", encoding="utf-8")

        queued = []
        view = SplitterView()
        monkeypatch.setattr(
            view,
            "_ensure_preparing_worker",
            lambda: setattr(
                view,
                "_preparing_worker",
                type("W", (), {"add_items": lambda self, items: queued.extend(items), "isRunning": lambda self: True})(),
            ),
        )

        view._add_paths([str(path)])

        doc = view._db.get_documents()[0]
        assert doc["standard_number"] == "60335-2-35"
        assert queued == [(doc["id"], str(path))]

    def test_add_paths_cancelled_standard_prompt_aborts_import(self, qapp, monkeypatch, tmp_path):
        self._use_temp_db(monkeypatch, tmp_path)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)
        monkeypatch.setattr(
            "tuv_tools.ui.views.splitter_view.resolve_standard_number_overrides",
            lambda *args, **kwargs: None,
            raising=False,
        )

        path = tmp_path / "unknown.docx"
        path.write_text("x", encoding="utf-8")

        view = SplitterView()
        view._add_paths([str(path)])

        assert view._db.get_documents() == []

    def test_save_document_standard_updates_database(self, qapp, monkeypatch, tmp_path):
        self._use_temp_db(monkeypatch, tmp_path)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)

        path = tmp_path / "sample.docx"
        path.write_text("x", encoding="utf-8")

        view = SplitterView()
        doc_id = view._db.add_document(str(path))
        view._load_documents()

        view._save_document_standard(doc_id, "60335-2-30")

        assert view._db.get_document(doc_id)["standard_number"] == "60335-2-30"

    def test_has_resume_check_hook_after_initial_load(self, qapp, monkeypatch):
        calls = []

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: calls.append("load"))

        view = SplitterView()

        assert hasattr(view, "_resume_preparing_if_needed")

    def test_global_checkbox_style_matches_batch_drawer_checkbox_style(self, qapp):
        from tuv_tools.ui.theme import ThemeManager
        from tuv_tools.ui.widgets import checkbox_style
        from tuv_tools.ui.widgets.chapter_batch_clause_table import chapter_batch_checkbox_style

        assert checkbox_style() == chapter_batch_checkbox_style()
        style = checkbox_style()
        assert f"color: {ThemeManager.instance().colors.text_primary};" in style
        assert "width: 18px;" in style
        assert "height: 18px;" in style
        assert "checkmark.png" in style

    def test_prepare_paused_can_be_batch_selected_for_delete(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "paused.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        view = SplitterView()
        view._table.load_documents([
            {
                "id": 1,
                "file_path": str(path),
                "file_name": path.name,
                "standard_number": None,
                "status": "prepare_paused",
                "last_section_count": None,
                "last_split_at": None,
            }
        ])

        view._table.set_all_checked(True)
        assert view._table.checked_ids() == [1]

    def test_split_button_disabled_when_checked_docs_include_prepare_paused(self, qapp, monkeypatch, tmp_path):
        pending = tmp_path / "pending.docx"
        paused = tmp_path / "paused.docx"
        pending.write_text("x", encoding="utf-8")
        paused.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)

        view = SplitterView()
        view._table.load_documents([
            {
                "id": 1,
                "file_path": str(pending),
                "file_name": pending.name,
                "standard_number": None,
                "status": "pending",
                "last_section_count": None,
                "last_split_at": None,
            },
            {
                "id": 2,
                "file_path": str(paused),
                "file_name": paused.name,
                "standard_number": None,
                "status": "prepare_paused",
                "last_section_count": None,
                "last_split_at": None,
            },
        ])

        view._table.set_all_checked(True)
        view._update_selected_label()

        assert set(view._table.checked_ids()) == {1, 2}
        assert view._delete_btn.isEnabled() is True
        assert view._split_btn.isEnabled() is False

    def test_split_button_disabled_when_checked_docs_include_prepare_failed(self, qapp, monkeypatch, tmp_path):
        pending = tmp_path / "pending.docx"
        failed = tmp_path / "failed.docx"
        pending.write_text("x", encoding="utf-8")
        failed.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)

        view = SplitterView()
        view._table.load_documents([
            {
                "id": 1,
                "file_path": str(pending),
                "file_name": pending.name,
                "standard_number": None,
                "status": "pending",
                "last_section_count": None,
                "last_split_at": None,
            },
            {
                "id": 2,
                "file_path": str(failed),
                "file_name": failed.name,
                "standard_number": None,
                "status": "prepare_failed",
                "last_section_count": None,
                "last_split_at": None,
            },
        ])

        view._table.set_all_checked(True)
        view._update_selected_label()

        assert set(view._table.checked_ids()) == {1, 2}
        assert view._delete_btn.isEnabled() is True
        assert view._split_btn.isEnabled() is False

    def test_delete_button_tracks_checked_selection(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "pending.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)

        view = SplitterView()
        view._table.load_documents([
            {
                "id": 1,
                "file_path": str(path),
                "file_name": path.name,
                "standard_number": None,
                "status": "pending",
                "last_section_count": None,
                "last_split_at": None,
            }
        ])

        view._update_selected_label()
        assert view._delete_btn.isEnabled() is False

        view._table.set_all_checked(True)
        view._update_selected_label()

        assert view._delete_btn.isEnabled() is True

    def test_delete_selected_removes_checked_docs_after_confirmation(self, qapp, monkeypatch, tmp_path):
        self._use_temp_db(monkeypatch, tmp_path)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        first = tmp_path / "first.docx"
        second = tmp_path / "second.docx"
        first.write_text("x", encoding="utf-8")
        second.write_text("x", encoding="utf-8")

        view = SplitterView()
        first_id = view._db.add_document(str(first))
        second_id = view._db.add_document(str(second))
        view._table.load_documents([
            view._db.get_document(first_id),
            view._db.get_document(second_id),
        ])
        view._table.set_all_checked(True)

        view._delete_selected()

        assert view._db.get_document(first_id) is None
        assert view._db.get_document(second_id) is None

    def test_delete_selected_keeps_docs_when_cancelled(self, qapp, monkeypatch, tmp_path):
        self._use_temp_db(monkeypatch, tmp_path)
        monkeypatch.setattr(SplitterView, "_resume_preparing_if_needed", lambda self: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

        path = tmp_path / "keep.docx"
        path.write_text("x", encoding="utf-8")

        view = SplitterView()
        doc_id = view._db.add_document(str(path))
        view._table.load_documents([view._db.get_document(doc_id)])
        view._table.set_all_checked(True)

        view._delete_selected()

        assert view._db.get_document(doc_id) is not None
        view._db.delete_document(doc_id)

    def test_resume_preparing_if_needed_accepts_and_queues_existing_docs(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "resume.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        view = SplitterView()
        queued = []
        view._db.add_document(str(path))
        doc_id = view._db.get_documents()[0]["id"]
        view._db.update_document_status(doc_id, "preparing")
        monkeypatch.setattr(view, "_ensure_preparing_worker", lambda: setattr(view, "_preparing_worker", type("W", (), {"add_items": lambda self, items: queued.extend(items)})()))

        view._resume_preparing_if_needed()

        assert queued == [(doc_id, str(path))]

    def test_resume_preparing_if_needed_rejects_and_pauses_docs(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "pause.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

        view = SplitterView()
        view._db.add_document(str(path))
        doc_id = view._db.get_documents()[0]["id"]
        view._db.update_document_status(doc_id, "preparing")

        view._resume_preparing_if_needed()

        assert view._db.get_document(doc_id)["status"] == "prepare_paused"

    def test_on_prepare_error_marks_prepare_failed(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "broken.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        view = SplitterView()
        doc_id = view._db.add_document(str(path))

        view._on_prepare_error(doc_id, "Word crash")

        doc = view._db.get_document(doc_id)
        assert doc is not None
        assert doc["status"] == "prepare_failed"
        assert doc["error_message"] == "Word crash"

    def test_prepare_error_shows_failure_toast_immediately(self, qapp, monkeypatch, tmp_path):
        path = tmp_path / "broken.docx"
        path.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        toasts = []
        monkeypatch.setattr("tuv_tools.ui.views.splitter_view.Toast", lambda parent, message, duration_ms=2000: toasts.append(message))

        view = SplitterView()
        doc_id = view._db.add_document(str(path))
        view._preparing_pending_ids = {doc_id}

        view._on_prepare_error(doc_id, "Word crash")

        assert any("预处理失败" in message for message in toasts)

    def test_all_preparing_done_shows_completion_toast_once(self, qapp, monkeypatch, tmp_path):
        first = tmp_path / "a.docx"
        second = tmp_path / "b.docx"
        first.write_text("x", encoding="utf-8")
        second.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        toasts = []
        monkeypatch.setattr("tuv_tools.ui.views.splitter_view.Toast", lambda parent, message, duration_ms=2000: toasts.append(message))

        view = SplitterView()
        first_id = view._db.add_document(str(first))
        second_id = view._db.add_document(str(second))
        view._preparing_pending_ids = {first_id, second_id}

        view._on_doc_prepared(first_id)
        assert not any("所有预处理已完成" in message for message in toasts)

        view._on_doc_prepared(second_id)

        done_toasts = [message for message in toasts if "所有预处理已完成" in message]
        assert len(done_toasts) == 1

    def test_failure_then_last_success_still_emits_final_completion_toast(self, qapp, monkeypatch, tmp_path):
        first = tmp_path / "a.docx"
        second = tmp_path / "b.docx"
        first.write_text("x", encoding="utf-8")
        second.write_text("x", encoding="utf-8")

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        toasts = []
        monkeypatch.setattr("tuv_tools.ui.views.splitter_view.Toast", lambda parent, message, duration_ms=2000: toasts.append(message))

        view = SplitterView()
        first_id = view._db.add_document(str(first))
        second_id = view._db.add_document(str(second))
        view._preparing_pending_ids = {first_id, second_id}

        view._on_prepare_error(first_id, "Word crash")
        view._on_doc_prepared(second_id)

        assert any("预处理失败" in message for message in toasts)
        assert any("所有预处理已完成" in message for message in toasts)
