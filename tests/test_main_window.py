"""测试主窗口的启动接管与设置入口。"""

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


def test_main_window_does_not_auto_initialize_session(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.main_window import MainWindow

    calls: list[str] = []
    monkeypatch.setattr(
        ChapterSessionManager,
        "initialize_on_startup",
        lambda self: calls.append("initialize"),
    )

    MainWindow()

    assert calls == []


def test_main_window_has_display_only_connection_status_block(qapp):
    from tuv_tools.ui.main_window import MainWindow

    window = MainWindow()

    assert hasattr(window, "_connection_status")
    assert window._connection_status.text() == "未连接"


def test_main_window_opens_settings_with_shared_dependencies(qapp, monkeypatch):
    from tuv_tools.ui.main_window import MainWindow

    captured = {}

    class DummyDialog:
        def __init__(self, parent=None, settings=None, session_manager=None):
            captured["parent"] = parent
            captured["settings"] = settings
            captured["session_manager"] = session_manager

        def exec(self):
            return 0

    monkeypatch.setattr("tuv_tools.ui.main_window.SettingsDialog", DummyDialog)

    window = MainWindow()
    window._open_settings()

    assert captured["parent"] is window
    assert captured["settings"] is window._settings
    assert captured["session_manager"] is window._chapter_session
