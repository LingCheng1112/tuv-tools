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
