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
        self.transition_to_loading_calls: list[str] = []
        self.login_transition_calls: list[tuple[object, str]] = []
        self.closed = False

    def show_loading(self) -> None:
        self.loading_calls += 1

    def transition_to_loading(self, subtitle: str = "正在连接...") -> None:
        self.transition_to_loading_calls.append(subtitle)

    def transition_to_login(self, config, error_message: str = "") -> None:
        self.login_transition_calls.append((config, error_message))

    def close(self) -> None:
        self.closed = True
        super().close()


def test_controller_default_minimum_loading_ms_is_2500(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    controller = StartupController(
        session_manager=_FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED),
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: _FakeMainWindow(**kwargs),
    )

    assert controller._minimum_loading_ms == 2500


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
        minimum_loading_ms=2500,
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
        minimum_loading_ms=2500,
    )

    controller.start()
    controller._on_minimum_loading_elapsed()

    assert controller._startup_view.login_transition_calls == [(None, "")]
    assert controller._main_window is None


def test_controller_login_submit_uses_transition_to_loading_not_hard_reset(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED)
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: _FakeMainWindow(**kwargs),
        minimum_loading_ms=2500,
    )

    controller._startup_view.login_submitted.emit("http://127.0.0.1:8080", "admin", "secret")

    assert controller._startup_view.transition_to_loading_calls == ["正在连接..."]
    assert controller._startup_view.loading_calls == 0
    assert session.login_calls == [("http://127.0.0.1:8080", "admin", "secret")]


def test_controller_keeps_loading_view_while_session_is_loading(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOADING)
    created = {}
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: created.setdefault("window", _FakeMainWindow(**kwargs)),
        minimum_loading_ms=2500,
    )

    controller.start()
    controller._on_minimum_loading_elapsed()

    assert controller._startup_view.login_transition_calls == []
    assert "window" not in created
    assert controller._main_window is None


def test_controller_reopens_loading_state_after_settings_starts_refresh(qapp, monkeypatch):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED)
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: _FakeMainWindow(**kwargs),
        minimum_loading_ms=2500,
    )

    class DummyDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            session.status = ChapterConnectionStatus.LOADING
            return 0

    monkeypatch.setattr("tuv_tools.ui.views.settings_dialog.SettingsDialog", DummyDialog)

    controller._open_settings()

    assert controller._startup_view.transition_to_loading_calls == ["正在连接..."]
    assert controller._startup_view.login_transition_calls == []


def test_controller_skip_login_enters_main_window_offline(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.ui.startup_controller import StartupController

    session = _FakeSessionManager(ChapterConnectionStatus.LOGIN_REQUIRED)
    created = {}
    controller = StartupController(
        session_manager=session,
        startup_view_factory=_FakeStartupView,
        main_window_factory=lambda **kwargs: created.setdefault("window", _FakeMainWindow(**kwargs)),
        minimum_loading_ms=2500,
    )

    controller.start()
    controller._on_minimum_loading_elapsed()
    controller._startup_view.skip_requested.emit()

    assert session.skip_calls == 1
    assert created["window"].shown is True
