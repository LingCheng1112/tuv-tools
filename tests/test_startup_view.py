"""测试启动页视图的关键状态切换。"""

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


def test_startup_view_transition_to_login_shows_form(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "")
    view._finalize_login_state()

    assert not view._login_wrap.isHidden()
    assert view._loading_wrap.isHidden()
    assert view._login_heading.text() == "登录"
    assert view._subtitle_opacity.opacity() == 0.0
    assert view._login_opacity.opacity() == 1.0
    assert view.transition_progress == 1.0
    assert view.login_slide_progress == 1.0


def test_startup_view_show_loading_resets_login_state(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "error")
    view._finalize_login_state()

    view.show_loading()

    assert view._login_wrap.isHidden()
    assert not view._loading_wrap.isHidden()
    assert view._subtitle.text() == "正在加载"
    assert view._loading_opacity.opacity() == 1.0
    assert view._subtitle_opacity.opacity() == 1.0
    assert view.transition_progress == 0.0
    assert view.login_slide_progress == 0.0
