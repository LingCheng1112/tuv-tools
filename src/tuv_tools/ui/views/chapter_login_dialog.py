"""轻量登录弹窗。"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.models import ApiConfig


class ChapterLoginDialog(QDialog):
    """首次使用或手动重连时使用的轻量登录弹窗。"""

    def __init__(self, parent=None, settings: AppSettings | None = None):
        super().__init__(parent)
        self.setWindowTitle("登录")
        self.setMinimumWidth(420)
        self._settings = settings or AppSettings()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form_container = QWidget(self)
        form = QFormLayout(form_container)

        existing = self._settings.load_api_config() or ApiConfig()
        self._url_edit = QLineEdit(existing.base_url or "http://127.0.0.1:8080")
        self._user_edit = QLineEdit(existing.username)
        self._password_edit = QLineEdit(existing.password)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("API URL", self._url_edit)
        form.addRow("用户名", self._user_edit)
        form.addRow("密码", self._password_edit)
        layout.addWidget(form_container)

        actions = QHBoxLayout()
        self._settings_btn = QPushButton("打开设置")
        self._settings_btn.clicked.connect(self._open_settings)
        actions.addWidget(self._settings_btn)
        actions.addStretch()
        layout.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("登录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _open_settings(self) -> None:
        from tuv_tools.ui.views.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self, settings=self._settings)
        dlg.exec()
        updated = self._settings.load_api_config()
        if updated is not None:
            self._url_edit.setText(updated.base_url)
            self._user_edit.setText(updated.username)
            self._password_edit.setText(updated.password)

    def _save_and_accept(self) -> None:
        existing = self._settings.load_api_config() or ApiConfig()
        updated = replace(
            existing,
            base_url=self._url_edit.text().strip(),
            username=self._user_edit.text().strip(),
            password=self._password_edit.text(),
        )
        self._settings.save_api_config(updated)
        self.accept()
