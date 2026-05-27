"""应用级 Chapter 连接状态中心。"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QObject, QThread, Signal

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import ApiConfig


class ChapterConnectionStatus(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class _LoginWorker(QThread):
    finished_ok = Signal(object, bool)
    failed = Signal(str)

    def __init__(self, config: ApiConfig):
        super().__init__()
        self._config = config

    def run(self) -> None:
        try:
            client = TuvClient(self._config.base_url, self._config.request_timeout)
            success = auto_login(client, self._config)
            self.finished_ok.emit(client, success)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterSessionManager(QObject):
    """统一管理应用级 chapter 连接状态与登录入口。"""

    status_changed = Signal(str)
    login_dialog_requested = Signal()

    def __init__(self, settings: AppSettings | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings or AppSettings()
        self._config: ApiConfig | None = None
        self._client: TuvClient | None = None
        self._status = ChapterConnectionStatus.UNCONFIGURED
        self._last_error = ""
        self._worker: _LoginWorker | None = None

    @property
    def status(self) -> ChapterConnectionStatus:
        return self._status

    @property
    def client(self) -> TuvClient | None:
        return self._client

    @property
    def config(self) -> ApiConfig | None:
        return self._config

    @property
    def last_error(self) -> str:
        return self._last_error

    def is_connected(self) -> bool:
        return self._status == ChapterConnectionStatus.CONNECTED and self._client is not None

    def get_connected_client(self) -> TuvClient | None:
        if not self.is_connected():
            return None
        return self._client

    def get_connected_config(self) -> ApiConfig | None:
        if not self.is_connected():
            return None
        return self._config

    def has_credentials(self) -> bool:
        config = self._settings.load_api_config()
        if config is None:
            return False
        return bool(config.base_url.strip() and config.username.strip() and config.password)

    def status_text(self) -> str:
        mapping = {
            ChapterConnectionStatus.UNCONFIGURED: "● 未连接",
            ChapterConnectionStatus.CONNECTING: "● 连接中...",
            ChapterConnectionStatus.CONNECTED: "● 已连接",
            ChapterConnectionStatus.DISCONNECTED: "● 未连接",
        }
        return mapping[self._status]

    def initialize_on_startup(self) -> None:
        self._settings.ensure_app_data_root_ready()
        if not self.has_credentials():
            self._set_status(ChapterConnectionStatus.UNCONFIGURED)
            self.login_dialog_requested.emit()
            return
        self.refresh_login(silent=True)

    def refresh_login(self, *, silent: bool = False) -> None:
        self._config = self._settings.load_api_config()
        if self._config is None or not self.has_credentials():
            self._client = None
            self._set_status(ChapterConnectionStatus.UNCONFIGURED)
            if not silent:
                self.login_dialog_requested.emit()
            return
        self._set_status(ChapterConnectionStatus.CONNECTING)
        self._last_error = ""
        self._worker = _LoginWorker(self._config)
        self._worker.finished_ok.connect(self._on_login_finished)
        self._worker.failed.connect(self._on_login_failed)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def request_login_dialog(self) -> None:
        self.login_dialog_requested.emit()

    def apply_saved_credentials(self) -> None:
        self.refresh_login(silent=True)

    def _on_login_finished(self, client: TuvClient, success: bool) -> None:
        if success:
            self._client = client
            self._set_status(ChapterConnectionStatus.CONNECTED)
            return
        self._client = None
        self._set_status(ChapterConnectionStatus.DISCONNECTED)

    def _on_login_failed(self, message: str) -> None:
        self._client = None
        self._last_error = message
        self._set_status(ChapterConnectionStatus.DISCONNECTED)

    def _clear_worker(self) -> None:
        self._worker = None

    def _set_status(self, status: ChapterConnectionStatus) -> None:
        self._status = status
        self.status_changed.emit(status.value)
