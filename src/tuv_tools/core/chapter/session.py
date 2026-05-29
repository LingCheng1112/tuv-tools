"""应用级 Chapter 连接状态中心。"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from PySide6.QtCore import QObject, QThread, Signal

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import ApiConfig


class ChapterConnectionStatus(StrEnum):
    LOADING = "loading"
    CONNECTED = "connected"
    LOGIN_REQUIRED = "login_required"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class _LoginWorker(QThread):
    finished_ok = Signal(object, bool)
    failed = Signal(str)

    def __init__(self, config: ApiConfig):
        super().__init__()
        self._config = config

    def run(self) -> None:
        try:
            verify: str | bool | None = self._config.ca_cert_file or None
            client = TuvClient(
                self._config.base_url,
                self._config.request_timeout,
                verify=verify,
            )
            success = auto_login(client, self._config)
            self.finished_ok.emit(client, success)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterSessionManager(QObject):
    """统一管理应用级 chapter 连接状态与登录动作。"""

    status_changed = Signal(str)

    def __init__(self, settings: AppSettings | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings or AppSettings()
        self._config: ApiConfig | None = None
        self._client: TuvClient | None = None
        self._status = ChapterConnectionStatus.LOGIN_REQUIRED
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
        return self._has_complete_credentials(self._settings.load_api_config())

    def status_text(self) -> str:
        mapping = {
            ChapterConnectionStatus.LOADING: "连接中...",
            ChapterConnectionStatus.CONNECTED: "已连接",
            ChapterConnectionStatus.LOGIN_REQUIRED: "未连接",
            ChapterConnectionStatus.DISCONNECTED: "未连接",
            ChapterConnectionStatus.ERROR: "连接失败",
        }
        return mapping[self._status]

    def initialize_on_startup(self) -> None:
        self._settings.ensure_app_data_root_ready()
        self.refresh_login()

    def refresh_login(self) -> None:
        self._config = self._settings.load_api_config()
        self._client = None
        if not self._has_complete_credentials(self._config):
            self._last_error = ""
            self._set_status(ChapterConnectionStatus.LOGIN_REQUIRED)
            return
        error_message = self._validate_login_config(self._config)
        if error_message:
            self._last_error = error_message
            self._set_status(ChapterConnectionStatus.ERROR)
            return
        self._last_error = ""
        self._set_status(ChapterConnectionStatus.LOADING)
        self._start_login_worker(self._config)

    def apply_saved_credentials(self) -> None:
        self.refresh_login()

    def login_with_credentials(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        ca_cert_file: str | None = None,
    ) -> None:
        existing = self._settings.load_api_config() or ApiConfig()
        updated = replace(
            existing,
            base_url=base_url.strip(),
            username=username.strip(),
            password=password,
            ca_cert_file=existing.ca_cert_file if ca_cert_file is None else ca_cert_file.strip(),
        )
        self._settings.save_api_config(updated)
        self.refresh_login()

    def skip_login(self) -> None:
        self._client = None
        self._last_error = ""
        self._set_status(ChapterConnectionStatus.DISCONNECTED)

    def _start_login_worker(self, config: ApiConfig) -> None:
        self._worker = _LoginWorker(config)
        self._worker.finished_ok.connect(self._on_login_finished)
        self._worker.failed.connect(self._on_login_failed)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    @staticmethod
    def _has_complete_credentials(config: ApiConfig | None) -> bool:
        if config is None:
            return False
        return bool(config.base_url.strip() and config.username.strip() and config.password)

    @staticmethod
    def _validate_login_config(config: ApiConfig) -> str:
        # CA 证书仅在连接使用自签证书的服务器时需要手动配置；
        # 公网可信证书由 requests 通过系统 CA bundle 验证，无需额外配置。
        return ""

    def _on_login_finished(self, client: TuvClient, success: bool) -> None:
        if success:
            self._client = client
            self._last_error = ""
            self._set_status(ChapterConnectionStatus.CONNECTED)
            return
        self._client = None
        self._last_error = "登录失败，请检查账号、密码和证书配置。"
        self._set_status(ChapterConnectionStatus.ERROR)

    def _on_login_failed(self, message: str) -> None:
        self._client = None
        self._last_error = message
        self._set_status(ChapterConnectionStatus.ERROR)

    def _clear_worker(self) -> None:
        self._worker = None

    def _set_status(self, status: ChapterConnectionStatus) -> None:
        self._status = status
        self.status_changed.emit(status.value)
