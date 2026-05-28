"""测试条款管理视图的连接态降级。"""

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


def test_chapter_view_is_disabled_when_session_not_connected(qapp):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.views.chapter_view import ChapterView

    session = ChapterSessionManager()
    view = ChapterView(session)

    assert view._content_root.isEnabled() is False
    assert view._offline_hint.isHidden() is False
    assert "设置" in view._offline_hint.text()


def test_chapter_view_enables_content_when_session_connected(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus, ChapterSessionManager
    from tuv_tools.ui.views.chapter_view import ChapterView

    session = ChapterSessionManager()
    view = ChapterView(session)
    session._client = object()
    session._set_status(ChapterConnectionStatus.CONNECTED)

    assert view._content_root.isEnabled() is True
    assert view._offline_hint.isHidden() is True
