"""测试独立启动页控制器。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _FakeSessionManager(QObject):
    status_changed = Signal(str)

    def __init__(self, status, *, last_error: str = "", config=None):
        super().__init__()
        self.status = status
        self.last_error = last_error
        self.config = config
        self.initialize_calls = 0
        self.skip_calls = 0
        self.login_calls = []

    def initialize_on_startup(self) -> None:
        self.initialize_calls += 1
        self.status_changed.emit(self.status.value)

    def login_with_credentials(self, base_url: str, username: str, password: str) -> None:
        self.login_calls.append((base_url, username, password))

    def skip_login(self) -> None:
        from tuv_tools.core.chapter.session import ChapterConnectionStatus

        self.skip_calls += 1
        self.status = ChapterConnectionStatus.DISCONNECTED
        self.status_changed.emit(self.status.value)


class _FakeStartupView(QWidget):
    login_submitted = Signal(str, str, str)
    skip_requested = Signal()
    settings_requested = Signal()

    def __init__(self):
        super().__init__()
        self.loading_calls = 0
        self.login_transition_calls: list[tuple[object, str]] = []
        self.closed = False

    def show_loading(self) -> None:
        self.loading_calls += 1

    def transition_to_login(self, config, error_message: str = "") -> None:
        self.login_transition_calls.append((config, error_message))

    def close(self) -> None:
        self.closed = True
        super().close()


class _FakeMainWindow:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.shown = False

    def show(self):
        self.shown = True


def test_controller_waits_for_minimum_loading_before_showing_main(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.CONNECTED)
    created = {}

    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: created.setdefault("window", _FakeMainWindow(**kwargs)),
        minimum_loading_ms=3000,
    )

    controller.start()

    assert session.initialize_calls == 1
    assert "window" not in created

    controller._on_minimum_loading_elapsed()

    assert created["window"].shown is True
    assert controller._startup_view.closed is True


def test_controller_switches_to_login_view_after_loading_on_login_required(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED, last_error="")
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: _FakeMainWindow(**kwargs),
        minimum_loading_ms=3000,
    )

    controller.start()
    controller._on_minimum_loading_elapsed()

    assert controller._startup_view.login_transition_calls == [(None, "")]
    assert controller._main_window is None


def test_controller_skip_login_enters_main_window_offline(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED)
    created = {}
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: created.setdefault("window", _FakeMainWindow(**kwargs)),
        minimum_loading_ms=3000,
    )

    controller.start()
    controller._on_minimum_loading_elapsed()
    controller._startup_view.skip_requested.emit()

    assert session.skip_calls == 1
    assert created["window"].shown is True
