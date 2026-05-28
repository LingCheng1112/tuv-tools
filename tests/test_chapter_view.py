"""测试条款管理视图的连接态和表格布局。"""

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


def test_chapter_view_uses_dark_table_style_contract(qapp):
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.views.chapter_view import ChapterView

    view = ChapterView(ChapterSessionManager())

    assert view._table.alternatingRowColors() is True
    assert view._table.showGrid() is False
    assert view._table.verticalHeader().isVisible() is False
    assert "alternate-background-color" in view._table.styleSheet()
    assert "QHeaderView::section" in view._table.styleSheet()


def test_chapter_view_operation_column_reserves_button_space(qapp):
    from PySide6.QtWidgets import QHeaderView
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.views.chapter_view import ChapterView

    view = ChapterView(ChapterSessionManager())
    header = view._table.horizontalHeader()

    assert header.sectionResizeMode(6) == QHeaderView.ResizeMode.Fixed
    assert view._table.columnWidth(6) >= 150
    assert view._table.verticalHeader().defaultSectionSize() >= 42


def test_chapter_view_operation_widget_has_enough_height(qapp):
    from tuv_tools.core.chapter.models import Chapter, ChapterStatus
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.views.chapter_view import ChapterView

    view = ChapterView(ChapterSessionManager())
    chapter = Chapter(
        id=1,
        term="10.1",
        standard="60335-2-30",
        version=1,
        test_content="Heating",
        status=ChapterStatus.DRAFT,
        quote_cnt=0,
    )

    view._populate_table([chapter])

    ops = view._table.cellWidget(0, 6)
    assert ops is not None
    assert ops.minimumHeight() >= 34
