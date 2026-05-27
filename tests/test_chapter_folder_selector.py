"""测试条款目录树选择器。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_folder_selector_emits_selected_folder(qapp):
    from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector

    widget = ChapterFolderSelector()
    captured = []
    widget.folder_changed.connect(lambda fid, name: captured.append((fid, name)))

    widget.set_selected_folder(1061, "60335-2-3")
    widget._emit_folder_changed(1061, "60335-2-3")

    assert widget.selected_folder() == (1061, "60335-2-3")
    assert captured == [(1061, "60335-2-3")]


def test_folder_selector_can_apply_dialog_selection(qapp, monkeypatch):
    from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector

    widget = ChapterFolderSelector()

    class Dialog:
        def __init__(self, parent=None, session_manager=None):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def selected_folder(self):
            return 88, "60335-2-9"

    monkeypatch.setattr(
        "tuv_tools.ui.widgets.chapter_folder_selector.ChapterFolderDialog",
        Dialog,
    )

    widget._open_dialog()

    assert widget.selected_folder() == (88, "60335-2-9")


def test_folder_selector_button_disabled_when_session_not_connected(qapp):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector

    session = ChapterSessionManager()
    widget = ChapterFolderSelector(session_manager=session)

    assert widget._button.isEnabled() is False


def test_folder_selector_passes_session_manager_to_dialog(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector

    session = ChapterSessionManager()
    session._client = object()
    session._set_status(ChapterConnectionStatus.CONNECTED)
    captured = {}

    class Dialog:
        def __init__(self, parent=None, session_manager=None):
            captured["session_manager"] = session_manager

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "tuv_tools.ui.widgets.chapter_folder_selector.ChapterFolderDialog",
        Dialog,
    )

    widget = ChapterFolderSelector(session_manager=session)
    widget.set_connection_enabled(True)
    widget._open_dialog()

    assert captured["session_manager"] is session
