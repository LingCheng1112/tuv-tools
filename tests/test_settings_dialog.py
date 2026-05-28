"""测试设置弹窗中的本地数据目录与登录配置。"""

from __future__ import annotations

import os
import sqlite3
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


def test_settings_dialog_switches_app_data_root_and_shows_restart_hint(qapp, monkeypatch, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)

    dialog = SettingsDialog(settings=settings)
    target_root = tmp_path / "custom-data-root"
    dialog._app_data_root_edit.setText(str(target_root))
    dialog._api_url_edit.setText("http://127.0.0.1:8080")
    dialog._api_user_edit.setText("admin")
    dialog._api_pass_edit.setText("secret")

    info_messages = []
    monkeypatch.setattr(dialog, "_show_information", lambda title, message: info_messages.append(message))

    app_data_root_changed, _ = dialog._persist_changes()

    assert app_data_root_changed is True
    assert settings.get_app_data_root() == target_root
    saved = dialog._db.load_api_config()
    assert saved is not None
    assert saved.base_url == "http://127.0.0.1:8080"
    assert saved.username == "admin"
    assert saved.password == "secret"
    dialog._show_information("设置已保存", "本地数据目录已更新，重启工具后生效。")
    assert info_messages == ["本地数据目录已更新，重启工具后生效。"]


def test_settings_dialog_imports_old_app_data_and_can_delete_old_root(qapp, monkeypatch, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    old_root = tmp_path / "old-data"
    new_root = tmp_path / "new-data"
    (old_root / "chapter-batch" / "42" / "clauses_docx").mkdir(parents=True)
    (old_root / "chapter-batch" / "42" / "clauses_docx" / "10_1.docx").write_text("docx", encoding="utf-8")
    (old_root / ".token_cache").write_text("{}", encoding="utf-8")
    sqlite3.connect(old_root / "tuv-tools.db").close()

    settings = AppSettings(project_root=project_root)
    settings.set_app_data_root(old_root)
    dialog = SettingsDialog(settings=settings)
    dialog._app_data_root_edit.setText(str(new_root))

    monkeypatch.setattr(
        dialog,
        "_ask_delete_old_root",
        lambda: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(dialog, "_show_information", lambda title, message: None)
    removed_roots = []
    monkeypatch.setattr(settings, "remove_app_data_root", lambda root: removed_roots.append(root))

    app_data_root_changed, copied = dialog._persist_changes()

    assert app_data_root_changed is True
    assert copied is True
    if copied and old_root.exists():
        if dialog._ask_delete_old_root() == __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes:
            settings.remove_app_data_root(old_root)
    assert settings.get_app_data_root() == new_root
    assert (new_root / "chapter-batch" / "42" / "clauses_docx" / "10_1.docx").exists()
    assert removed_roots == [old_root]


def test_settings_dialog_persists_ca_certificate_path(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("fake-ca", encoding="utf-8")

    dialog = SettingsDialog(settings=settings)
    dialog._api_url_edit.setText("https://example.com")
    dialog._api_user_edit.setText("admin")
    dialog._api_pass_edit.setText("secret")
    dialog._ca_cert_path = str(ca_file)
    dialog._update_ca_cert_status()

    dialog._persist_changes()

    saved = dialog._db.load_api_config()
    assert saved is not None
    assert saved.ca_cert_file == "certs/ca.pem"
    assert (settings.get_app_data_root() / "certs" / "ca.pem").read_text(encoding="utf-8") == "fake-ca"
    assert dialog._ca_cert_status.text() == "已配置"


def test_settings_dialog_can_clear_ca_certificate_status(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    dialog = SettingsDialog(settings=settings)

    dialog._ca_cert_path = str(tmp_path / "ca.pem")
    dialog._update_ca_cert_status()
    dialog._clear_ca_cert()

    assert dialog._ca_cert_status.text() == "未配置"


def test_settings_dialog_login_button_calls_session_refresh(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    calls: list[str] = []

    class DummySession:
        def refresh_login(self):
            calls.append("refresh")

        def status_text(self):
            return "未连接"

        @property
        def last_error(self):
            return ""

    dialog = SettingsDialog(settings=settings, session_manager=DummySession())
    dialog._login_btn.click()

    assert calls == ["refresh"]
