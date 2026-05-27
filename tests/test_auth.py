"""测试认证流程"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tuv_tools.core.chapter.auth import (
    auto_login,
    clear_token_cache,
    load_token_cache,
    save_token_cache,
)
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import ApiConfig


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / ".token_cache"


@pytest.fixture
def config(tmp_cache):
    return ApiConfig(
        base_url="http://localhost:8080",
        username="tyler",
        password="123456",
        rsa_private_key="",
        token_cache_file=str(tmp_cache),
        token_idle_timeout=7200,
    )


class TestTokenCache:
    def test_save_and_load(self, tmp_cache):
        save_token_cache(str(tmp_cache), "abc123", "tyler")
        result = load_token_cache(str(tmp_cache), timeout=7200)
        assert result is not None
        assert result["token"] == "abc123"
        assert result["username"] == "tyler"

    def test_save_creates_parent_directory(self, tmp_path):
        nested_cache = tmp_path / "nested" / ".token_cache"
        save_token_cache(str(nested_cache), "abc123", "tyler")
        assert nested_cache.exists()

    def test_load_expired(self, tmp_cache):
        save_token_cache(str(tmp_cache), "old_token", "tyler")
        data = json.loads(Path(tmp_cache).read_text())
        data["time"] = time.time() - 10800
        Path(tmp_cache).write_text(json.dumps(data))
        result = load_token_cache(str(tmp_cache), timeout=7200)
        assert result is None

    def test_load_missing_file(self, tmp_path):
        result = load_token_cache(str(tmp_path / "nonexist"), timeout=7200)
        assert result is None

    def test_clear(self, tmp_cache):
        save_token_cache(str(tmp_cache), "token", "user")
        clear_token_cache(str(tmp_cache))
        assert not Path(tmp_cache).exists()


class TestAutoLogin:
    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_cached_token_valid(self, mock_encrypt, config, tmp_cache):
        save_token_cache(str(tmp_cache), "valid_token", "tyler")
        client = TuvClient(config.base_url)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"username": "tyler"}
        with patch.object(client, "get", return_value=mock_resp):
            result = auto_login(client, config)
        assert result is True
        assert client.token == "valid_token"

    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_cached_token_for_different_user_is_ignored(self, mock_encrypt, config, tmp_cache):
        save_token_cache(str(tmp_cache), "old_user_token", "other")
        client = TuvClient(config.base_url)
        mock_encrypt.return_value = "encrypted_pw"
        config.rsa_private_key = "fake_key"
        login_resp = MagicMock()
        login_resp.status_code = 200
        login_resp.json.return_value = {"token": "Bearer new_token"}

        with patch.object(client, "get") as mock_get, \
             patch.object(client, "post", return_value=login_resp) as mock_post:
            result = auto_login(client, config)

        assert result is True
        assert client.token == "new_token"
        mock_get.assert_not_called()
        mock_post.assert_called_once()

    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_cached_token_invalid_triggers_login(self, mock_encrypt, config, tmp_cache):
        save_token_cache(str(tmp_cache), "expired_token", "tyler")
        client = TuvClient(config.base_url)
        mock_encrypt.return_value = "encrypted_pw"
        config.rsa_private_key = "fake_key"
        error_resp = MagicMock()
        error_resp.status_code = 401
        error_401 = requests.HTTPError(response=error_resp)
        login_resp = MagicMock()
        login_resp.status_code = 200
        login_resp.json.return_value = {"token": "Bearer new_token"}
        with patch.object(client, "get", side_effect=error_401):
            with patch.object(client, "post", return_value=login_resp):
                result = auto_login(client, config)
        assert result is True
        assert client.token == "new_token"

    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_network_error_does_not_retry_login(self, mock_encrypt, config, tmp_cache):
        save_token_cache(str(tmp_cache), "some_token", "tyler")
        client = TuvClient(config.base_url)
        with patch.object(client, "get", side_effect=requests.ConnectionError("refused")):
            result = auto_login(client, config)
        assert result is False
        mock_encrypt.assert_not_called()

    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_no_rsa_key_returns_false(self, mock_encrypt, config, tmp_cache):
        client = TuvClient(config.base_url)
        result = auto_login(client, config)
        assert result is False

    @patch("tuv_tools.core.chapter.auth.encrypt_password")
    def test_login_saves_token_when_cache_parent_missing(self, mock_encrypt, config, tmp_path):
        config.rsa_private_key = "fake_key"
        config.token_cache_file = str(tmp_path / "missing" / ".token_cache")
        mock_encrypt.return_value = "encrypted_pw"
        client = TuvClient(config.base_url)
        login_resp = MagicMock()
        login_resp.status_code = 200
        login_resp.json.return_value = {"token": "Bearer new_token"}

        with patch.object(client, "post", return_value=login_resp):
            result = auto_login(client, config)

        assert result is True
        assert client.token == "new_token"
        assert Path(config.token_cache_file).exists()
