"""认证流程：Token 缓存 + 自动登录"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .client import TuvClient
from .crypto import encrypt_password
from .models import ApiConfig


def save_token_cache(cache_path: str, token: str, username: str) -> None:
    """保存 token 到缓存文件"""
    data = {"token": token, "username": username, "time": time.time()}
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def load_token_cache(cache_path: str, timeout: int) -> dict | None:
    """加载 token 缓存，过期返回 None"""
    path = Path(cache_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("time", 0) > timeout:
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def clear_token_cache(cache_path: str) -> None:
    """清除 token 缓存文件"""
    path = Path(cache_path)
    if path.exists():
        path.unlink()


def auto_login(client: TuvClient, config: ApiConfig) -> bool:
    """自动登录流程，成功返回 True"""
    cache_path = config.token_cache_file

    # 尝试从缓存恢复
    if cache_path:
        cached = load_token_cache(cache_path, config.token_idle_timeout)
        if cached:
            if cached.get("username") != config.username:
                clear_token_cache(cache_path)
            else:
                client.token = cached["token"]
                try:
                    client.get("/auth/info")
                    return True
                except requests.HTTPError:
                    clear_token_cache(cache_path)
                    client.token = ""
                except (requests.ConnectionError, requests.Timeout):
                    client.token = ""
                    return False

    # 完整登录
    if not config.rsa_private_key:
        return False
    encrypted_pw = encrypt_password(config.password, config.rsa_private_key)
    try:
        resp = client.post("/auth/login", json={
            "username": config.username,
            "password": encrypted_pw,
            "code": "",
            "uuid": "",
        })
    except (requests.ConnectionError, requests.Timeout):
        return False
    except requests.HTTPError:
        return False

    data = resp.json()
    token_raw = data.get("token", "")
    token = token_raw.removeprefix("Bearer ")
    if not token:
        return False

    client.token = token
    if cache_path:
        save_token_cache(cache_path, token, config.username)
    return True
