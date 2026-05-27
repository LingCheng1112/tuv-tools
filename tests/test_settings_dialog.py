"""测试设置弹窗中的本地数据目录配置。"""

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
    from tuv_tools.core.chapter.models import ApiConfig
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
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: info_messages.append(args[2]),
    )

    dialog._save_and_accept()

    assert settings.get_app_data_root() == target_root
    saved = dialog._db.load_api_config()
    assert saved is not None
    assert saved.base_url == "http://127.0.0.1:8080"
    assert saved.username == "admin"
    assert saved.password == "secret"
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
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    dialog._save_and_accept()

    assert settings.get_app_data_root() == new_root
    assert (new_root / "chapter-batch" / "42" / "clauses_docx" / "10_1.docx").exists()
    assert not old_root.exists()
