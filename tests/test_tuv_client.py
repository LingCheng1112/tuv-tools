"""测试 TuvClient 的请求配置。"""

from __future__ import annotations

from unittest.mock import MagicMock

from tuv_tools.core.chapter.client import TuvClient


class TestTuvClient:
    def test_http_client_does_not_force_verify_argument(self, monkeypatch):
        client = TuvClient("http://127.0.0.1:8080")
        response = MagicMock()
        response.raise_for_status.return_value = None
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return response

        monkeypatch.setattr(client._session, "request", fake_request)

        client.get("/auth/info")

        assert calls == [
            ("GET", "http://127.0.0.1:8080/auth/info", {"timeout": 30})
        ]

    def test_https_client_uses_configured_ca_bundle(self, monkeypatch):
        client = TuvClient("https://example.com", timeout=12, verify="C:/certs/root-ca.pem")
        response = MagicMock()
        response.raise_for_status.return_value = None
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return response

        monkeypatch.setattr(client._session, "request", fake_request)

        client.post("/auth/login", json={"username": "admin"})

        assert calls == [
            (
                "POST",
                "https://example.com/auth/login",
                {
                    "json": {"username": "admin"},
                    "timeout": 12,
                    "verify": "C:/certs/root-ca.pem",
                },
            )
        ]
