"""测试主窗口的全局连接状态展示。"""

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


def test_main_window_shows_connection_button(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.main_window import MainWindow

    monkeypatch.setattr(ChapterSessionManager, "initialize_on_startup", lambda self: None)

    window = MainWindow()

    assert window._connection_btn.text() == "● 未连接"


def test_main_window_updates_connection_button_text_from_session(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus, ChapterSessionManager
    from tuv_tools.ui.main_window import MainWindow

    monkeypatch.setattr(ChapterSessionManager, "initialize_on_startup", lambda self: None)

    window = MainWindow()
    window._chapter_session._set_status(ChapterConnectionStatus.CONNECTED)

    assert window._connection_btn.text() == "● 已连接"


def test_main_window_opens_settings_with_shared_settings(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.main_window import MainWindow

    monkeypatch.setattr(ChapterSessionManager, "initialize_on_startup", lambda self: None)
    captured = {}

    class DummyDialog:
        def __init__(self, parent=None, settings=None):
            captured["parent"] = parent
            captured["settings"] = settings

        def exec(self):
            return 0

    monkeypatch.setattr("tuv_tools.ui.main_window.SettingsDialog", DummyDialog)

    window = MainWindow()
    window._open_settings()

    assert captured["parent"] is window
    assert captured["settings"] is window._settings
