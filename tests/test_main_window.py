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
    assert window._connection_status.text().startswith("\u25cf ")


def test_main_window_connection_status_badge_uses_status_specific_text_and_style(
    qapp,
    monkeypatch,
):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_register_views", lambda self: None)

    window = MainWindow()
    seen_styles = {}

    for status_name, status_fragment, expected_color in (
        ("LOADING", "\u8fde\u63a5\u4e2d", "#4a9eff"),
        ("CONNECTED", "\u5df2\u8fde\u63a5", "#4caf50"),
        ("ERROR", "\u8fde\u63a5\u5931\u8d25", "#ff6b6b"),
    ):
        window._chapter_session._status = getattr(ChapterConnectionStatus, status_name)
        window._refresh_connection_status(window._chapter_session.status.value)

        text = window._connection_status.text()
        style = window._connection_status.styleSheet()

        assert text.startswith("\u25cf ")
        assert status_fragment in text
        assert f"color: {expected_color}" in style
        seen_styles[status_name] = style

    assert len(set(seen_styles.values())) == 3


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
