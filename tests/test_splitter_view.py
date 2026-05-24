"""SplitterView 的最小视图级回归测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from tuv_tools.ui.views.splitter_view import SplitterView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSplitterView:
    def test_dropped_files_reuse_add_paths_flow(self, qapp, monkeypatch):
        captured: list[list[str]] = []

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: None)
        monkeypatch.setattr(SplitterView, "_add_paths", lambda self, paths: captured.append(paths))

        view = SplitterView()
        view._table.files_dropped.emit(["a.docx", "b.docx"])

        assert captured == [["a.docx", "b.docx"]]

    def test_has_resume_check_hook_after_initial_load(self, qapp, monkeypatch):
        calls = []

        monkeypatch.setattr(SplitterView, "_load_documents", lambda self: calls.append("load"))

        view = SplitterView()

        assert hasattr(view, "_resume_preparing_if_needed")

    def test_prepare_paused_is_excluded_from_normal_batch_selection(self, qapp, monkeypatch, tmp_path):
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
        assert view._table.checked_ids() == []

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
