"""启动控制器：接管首屏加载与登录承接。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from tuv_tools.config import AppSettings, RESOURCES_DIR
from tuv_tools.core.chapter.session import ChapterConnectionStatus, ChapterSessionManager
from tuv_tools.ui.main_window import MainWindow
from tuv_tools.ui.views.startup_view import StartupView


class StartupController(QObject):
    """协调启动页、全局会话与主窗口切换。"""

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        session_manager: ChapterSessionManager | None = None,
        startup_view_factory=StartupView,
        main_window_factory=MainWindow,
        minimum_loading_ms: int = 2500,
    ):
        super().__init__()
        self._settings = settings or AppSettings()
        self._session_manager = session_manager or ChapterSessionManager(self._settings, self)
        self._startup_view_factory = startup_view_factory
        self._main_window_factory = main_window_factory
        self._minimum_loading_ms = minimum_loading_ms
        self._minimum_elapsed = False
        self._startup_finished = False
        try:
            self._startup_view = self._startup_view_factory(logo_path=self._logo_path())
        except TypeError:
            self._startup_view = self._startup_view_factory()
        self._main_window = None
        self._session_manager.status_changed.connect(self._on_session_status_changed)
        self._startup_view.login_submitted.connect(self._on_login_submitted)
        self._startup_view.skip_requested.connect(self._on_skip_requested)
        self._startup_view.settings_requested.connect(self._open_settings)

    def start(self) -> None:
        self._startup_view.show_loading()
        self._startup_view.show()
        QTimer.singleShot(self._minimum_loading_ms, self._on_minimum_loading_elapsed)
        self._session_manager.initialize_on_startup()

    def _logo_path(self) -> Path:
        return RESOURCES_DIR / "TUV.svg"

    def _on_minimum_loading_elapsed(self) -> None:
        self._minimum_elapsed = True
        self._try_finish_startup()

    def _on_session_status_changed(self, _status: str) -> None:
        self._startup_finished = True
        self._try_finish_startup()

    def _try_finish_startup(self) -> None:
        if not self._minimum_elapsed or not self._startup_finished:
            return
        if self._session_manager.status == ChapterConnectionStatus.LOADING:
            return
        if self._session_manager.status in {
            ChapterConnectionStatus.CONNECTED,
            ChapterConnectionStatus.DISCONNECTED,
        }:
            self._show_main_window()
            return
        self._startup_view.transition_to_login(
            self._session_manager.config,
            self._session_manager.last_error,
        )

    def _show_main_window(self) -> None:
        if self._main_window is None:
            self._main_window = self._main_window_factory(
                settings=self._settings,
                session_manager=self._session_manager,
            )
        self._main_window.show()
        self._startup_view.close()

    def _on_login_submitted(self, base_url: str, username: str, password: str) -> None:
        self._startup_finished = False
        self._minimum_elapsed = True
        self._startup_view.transition_to_loading("正在连接...")
        self._session_manager.login_with_credentials(base_url, username, password)

    def _on_skip_requested(self) -> None:
        self._session_manager.skip_login()

    def _open_settings(self) -> None:
        from tuv_tools.ui.views.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            self._startup_view,
            settings=self._settings,
            session_manager=self._session_manager,
        )
        dialog.exec()
        if self._session_manager.status == ChapterConnectionStatus.LOADING:
            self._startup_view.transition_to_loading("正在连接...")
            return
        self._startup_view.transition_to_login(
            self._session_manager.config,
            self._session_manager.last_error,
        )
