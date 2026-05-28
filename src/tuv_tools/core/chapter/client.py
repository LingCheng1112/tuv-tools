"""TUV 后端 HTTP 客户端。"""

from __future__ import annotations

import requests


class TuvClient:
    """封装 requests.Session，自动管理 JWT Authorization 头。"""

    def __init__(self, base_url: str, timeout: int = 30, verify: str | bool | None = None):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._verify = verify
        self._session = requests.Session()
        self._token: str = ""

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        self._token = value
        if value:
            self._session.headers["Authorization"] = f"Bearer {value}"
        else:
            self._session.headers.pop("Authorization", None)

    def get(self, path: str, **kwargs) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self._base_url}{path}"
        kwargs.setdefault("timeout", self._timeout)
        if self._verify is not None:
            kwargs.setdefault("verify", self._verify)
        response = self._session.request(method, url, **kwargs)
        response.raise_for_status()
        return response
