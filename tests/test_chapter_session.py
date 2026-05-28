"""测试 ChapterSessionManager 的全局连接状态机。"""

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


def test_initialize_without_credentials_enters_login_required(qapp, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.session import (
        ChapterConnectionStatus,
        ChapterSessionManager,
    )

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    session = ChapterSessionManager(settings=settings)

    session.initialize_on_startup()

    assert session.status == ChapterConnectionStatus.LOGIN_REQUIRED
    assert session.last_error == ""


def test_https_without_ca_enters_error_before_request(qapp, monkeypatch, tmp_path):
    from dataclasses import replace

    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.models import ApiConfig
    from tuv_tools.core.chapter.session import (
        ChapterConnectionStatus,
        ChapterSessionManager,
    )

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    settings.save_api_config(
        replace(
            ApiConfig(),
            base_url="https://example.com",
            username="admin",
            password="secret",
            rsa_private_key="fixed-key",
        )
    )

    session = ChapterSessionManager(settings=settings)
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_start_login_worker",
        lambda config: calls.append(config.base_url),
    )

    session.initialize_on_startup()

    assert session.status == ChapterConnectionStatus.ERROR
    assert "CA" in session.last_error
    assert calls == []


def test_http_saved_credentials_can_connect(qapp, monkeypatch, tmp_path):
    from dataclasses import replace

    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.client import TuvClient
    from tuv_tools.core.chapter.models import ApiConfig
    from tuv_tools.core.chapter.session import (
        ChapterConnectionStatus,
        ChapterSessionManager,
    )

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    settings = AppSettings(project_root=project_root)
    settings.save_api_config(
        replace(
            ApiConfig(),
            base_url="http://127.0.0.1:8080",
            username="admin",
            password="secret",
            rsa_private_key="fixed-key",
        )
    )

    session = ChapterSessionManager(settings=settings)

    def fake_start_login_worker(config):
        client = TuvClient(config.base_url, config.request_timeout)
        session._on_login_finished(client, True)

    monkeypatch.setattr(session, "_start_login_worker", fake_start_login_worker)

    session.initialize_on_startup()

    assert session.status == ChapterConnectionStatus.CONNECTED
    assert session.get_connected_client() is not None
    assert session.last_error == ""


def test_skip_login_switches_to_disconnected_without_request(qapp, monkeypatch, tmp_path):
    from tuv_tools.config import AppSettings
    from tuv_tools.core.chapter.session import (
        ChapterConnectionStatus,
        ChapterSessionManager,
    )

    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    session = ChapterSessionManager(settings=AppSettings(project_root=project_root))
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_start_login_worker",
        lambda config: calls.append(config.base_url),
    )

    session.skip_login()

    assert session.status == ChapterConnectionStatus.DISCONNECTED
    assert session.get_connected_client() is None
    assert calls == []
