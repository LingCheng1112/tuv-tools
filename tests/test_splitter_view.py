"""SplitterView 的最小视图级回归测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
