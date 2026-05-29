"""测试设置弹窗中的本地数据目录与登录配置。"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton


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

    result = dialog._persist_changes()
    app_data_root_changed = result[0]

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

    result = dialog._persist_changes()
    app_data_root_changed = result[0]
    copied = result[1]

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


def test_settings_dialog_uses_default_splitter_output_root(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)

    dialog = SettingsDialog(settings=settings)

    assert dialog._output_edit.text() == str(project_root / "doc_output")


def test_settings_dialog_persists_splitter_output_root_as_project_relative_path(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)

    dialog = SettingsDialog(settings=settings)
    dialog._output_edit.setText(str(project_root / "custom-output"))

    dialog._persist_changes()

    assert dialog._db.get_config("splitter.output_path", "") == "custom-output"


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


class _DummySession:
    def __init__(self, calls: list[str]):
        self._calls = calls

    def refresh_login(self):
        self._calls.append("refresh")

    def status_text(self):
        return "未连接"

    @property
    def last_error(self):
        return ""


def test_settings_dialog_login_tab_has_no_manual_login_controls(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    dialog = SettingsDialog(settings=AppSettings(project_root=project_root))
    api_tab = dialog._tabs.widget(1)

    button_texts = [button.text() for button in api_tab.findChildren(QPushButton)]
    label_texts = [label.text() for label in api_tab.findChildren(QLabel)]

    assert Counter(button_texts) == Counter(
        {
            "\u9009\u62e9...": 1,
            "\u6e05\u9664": 2,
            "\u4ece\u6587\u4ef6\u52a0\u8f7d...": 1,
        }
    )
    assert all("\u8fde\u63a5\u72b6\u6001" not in text for text in label_texts)
    assert all("\u6700\u8fd1\u9519\u8bef" not in text for text in label_texts)


def test_settings_dialog_save_does_not_refresh_session_when_login_config_unchanged(qapp, monkeypatch, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.models import ApiConfig
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    settings.save_api_config(
        ApiConfig(
            base_url="http://127.0.0.1:8080",
            username="admin",
            password="secret",
        )
    )
    calls: list[str] = []

    dialog = SettingsDialog(settings=settings, session_manager=_DummySession(calls))
    accepts: list[str] = []
    monkeypatch.setattr(dialog, "accept", lambda: accepts.append("accepted"))
    dialog._save_and_accept()

    assert accepts == ["accepted"]
    assert calls == []


@pytest.mark.parametrize(
    "changed_field",
    [
        "base_url",
        "username",
        "password",
        "ca_cert_set",
        "ca_cert_clear",
        "rsa_private_key_set",
        "rsa_private_key_clear",
    ],
)
def test_settings_dialog_save_refreshes_session_when_login_config_changes(
    qapp,
    monkeypatch,
    tmp_path,
    changed_field,
):
    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.models import ApiConfig
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    initial_ca_cert = ""
    initial_rsa_key = ""
    if changed_field == "ca_cert_clear":
        initial_ca_cert = "certs/ca.pem"
    if changed_field == "rsa_private_key_clear":
        initial_rsa_key = "seed-rsa-private-key"
    settings.save_api_config(
        ApiConfig(
            base_url="http://127.0.0.1:8080",
            username="admin",
            password="secret",
            ca_cert_file=initial_ca_cert,
            rsa_private_key=initial_rsa_key,
        )
    )
    calls: list[str] = []
    dialog = SettingsDialog(settings=settings, session_manager=_DummySession(calls))
    accepts: list[str] = []
    monkeypatch.setattr(dialog, "accept", lambda: accepts.append("accepted"))

    if changed_field == "base_url":
        dialog._api_url_edit.setText("http://127.0.0.2:8080")
    elif changed_field == "username":
        dialog._api_user_edit.setText("other-admin")
    elif changed_field == "password":
        dialog._api_pass_edit.setText("other-secret")
    elif changed_field == "ca_cert_set":
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("fake-ca", encoding="utf-8")
        dialog._ca_cert_path = str(ca_file)
        dialog._update_ca_cert_status()
    elif changed_field == "ca_cert_clear":
        dialog._clear_ca_cert()
    elif changed_field == "rsa_private_key_set":
        dialog._rsa_edit.setText("fake-rsa-private-key")
        dialog._update_rsa_status()
    elif changed_field == "rsa_private_key_clear":
        dialog._clear_rsa()

    dialog._save_and_accept()

    assert accepts == ["accepted"]
    assert calls == ["refresh"]


def test_settings_dialog_https_without_ca_is_blocked_on_save(qapp, monkeypatch, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.models import ApiConfig
    from tuv_tools.ui.views.settings_dialog import SettingsDialog

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    settings.save_api_config(
        ApiConfig(
            base_url="http://127.0.0.1:8080",
            username="admin",
            password="secret",
        )
    )
    dialog = SettingsDialog(settings=settings)
    dialog._api_url_edit.setText("https://example.com")
    dialog._api_user_edit.setText("admin")
    dialog._api_pass_edit.setText("secret")
    dialog._ca_cert_path = ""
    dialog._update_ca_cert_status()
    saved_before = dialog._db.load_api_config()

    warnings: list[tuple[str, str]] = []
    accepts: list[str] = []
    monkeypatch.setattr(dialog, "_show_warning", lambda title, message: warnings.append((title, message)))
    monkeypatch.setattr(dialog, "accept", lambda: accepts.append("accepted"))

    dialog._save_and_accept()

    assert accepts == []
    assert len(warnings) == 1
    assert "HTTPS" in warnings[0][1]
    assert "CA" in warnings[0][1]
    saved_after = dialog._db.load_api_config()
    assert saved_before is not None
    assert saved_after is not None
    assert saved_before.base_url == "http://127.0.0.1:8080"
    assert saved_after.base_url == "http://127.0.0.1:8080"
