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
    assert view._subtitle_opacity.opacity() == 0.0
    assert view._login_opacity.opacity() == 1.0
    assert view.transition_progress == 1.0
    assert view.login_slide_progress == 1.0
    assert view._skip_btn.isHidden() is False
    assert not hasattr(view, "_settings_btn")


def test_startup_view_show_loading_resets_login_state(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "error")
    view._finalize_login_state()

    view.show_loading()

    assert view._login_wrap.isHidden()
    assert not view._loading_wrap.isHidden()
    assert view._loading_opacity.opacity() == 1.0
    assert view._subtitle_opacity.opacity() == 1.0
    assert view.transition_progress == 0.0
    assert view.login_slide_progress == 0.0
    assert view._skip_btn.isHidden() is True


def test_startup_view_transition_to_loading_from_login_preserves_loading_scene(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "")
    view._finalize_login_state()

    view.transition_to_loading("正在连接...")
    view._finalize_loading_state()

    assert view._loading_wrap.isHidden() is False
    assert view._login_wrap.isHidden() is True
    assert view._subtitle.isHidden() is False
    assert view._subtitle.text() == "正在连接..."
    assert view.transition_progress == 0.0
    assert view.login_slide_progress == 0.0


def test_startup_view_transition_to_loading_disables_login_inputs(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "")
    view._finalize_login_state()

    view.transition_to_loading("正在连接...")

    assert view._url_edit.isEnabled() is False
    assert view._user_edit.isEnabled() is False
    assert view._password_edit.isEnabled() is False
    assert view._login_btn.isEnabled() is False
    assert view._skip_btn.isEnabled() is False


def test_startup_view_transition_back_to_login_reenables_inputs(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.transition_to_login(None, "")
    view._finalize_login_state()

    view.transition_to_loading("\u6b63\u5728\u8fde\u63a5...")
    view._finalize_loading_state()
    view.transition_to_login(None, "")
    view._finalize_login_state()

    assert view._url_edit.isEnabled() is True
    assert view._user_edit.isEnabled() is True
    assert view._password_edit.isEnabled() is True
    assert view._login_btn.isEnabled() is True
    assert view._skip_btn.isEnabled() is True


def test_startup_view_loading_spinner_runs_and_stops(qapp):
    from tuv_tools.ui.views.startup_view import StartupView

    view = StartupView()
    view.show_loading()

    assert view._spinner.is_spinning() is True

    view.transition_to_login(None, "")
    view._finalize_login_state()

    assert view._spinner.is_spinning() is False
