# 条款管理模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 tuv-tools 中实现 TUV 条款管理功能，对接后端 API 完成认证和条款 CRUD。

**Architecture:** 独立 `core/chapter/` 模块，包含 HTTP 客户端、RSA 加密、认证、API 操作和数据模型。UI 层为单个 `chapter_view.py` 视图，通过 QThread + Signal 模式执行网络操作。

**Tech Stack:** Python 3.11+, PySide6, requests, pycryptodome

---

## File Map

| 文件 | 职责 |
|------|------|
| `src/tuv_tools/core/chapter/__init__.py` | 模块公开接口 |
| `src/tuv_tools/core/chapter/models.py` | Chapter, PageResult, ApiConfig, ChapterStatus |
| `src/tuv_tools/core/chapter/client.py` | TuvClient HTTP 封装 |
| `src/tuv_tools/core/chapter/crypto.py` | RSA 公钥加密 |
| `src/tuv_tools/core/chapter/auth.py` | 认证流程 + Token 缓存 |
| `src/tuv_tools/core/chapter/api.py` | 条款 CRUD 函数 |
| `src/tuv_tools/config/settings.py` | 扩展 AppSettings，加入 ApiConfig 持久化 |
| `src/tuv_tools/ui/views/chapter_view.py` | 条款管理 PySide6 视图 |
| `src/tuv_tools/ui/main_window.py` | 注册新视图入口 |
| `pyproject.toml` | 新增 requests + pycryptodome 依赖 |
| `tests/test_models.py` | 模型序列化测试 |
| `tests/test_crypto.py` | RSA 加密测试 |
| `tests/test_auth.py` | 认证流程测试 |
| `tests/test_api.py` | API 函数测试 |

---

## Task 1: 依赖与模块骨架

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tuv_tools/core/chapter/__init__.py`
- Create: `src/tuv_tools/core/chapter/models.py`

- [ ] **Step 1: 更新 pyproject.toml 添加依赖**

```toml
dependencies = [
    "PySide6>=6.6.0",
    "requests>=2.28.0",
    "pycryptodome>=3.15.0",
]
```

- [ ] **Step 2: 安装新依赖**

Run: `pip install -e ".[dev]"`
Expected: 成功安装 requests 和 pycryptodome

- [ ] **Step 3: 创建 models.py**

```python
"""条款管理数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class ChapterStatus(IntEnum):
    """条款状态枚举"""
    DRAFT = 0
    VALID = 1
    INVALID = 2
    IN_REVIEW = 3
    REJECT = 4
    OBSOLETED = 5


STATUS_LABELS: dict[int, str] = {
    ChapterStatus.DRAFT: "草稿",
    ChapterStatus.VALID: "有效",
    ChapterStatus.INVALID: "无效",
    ChapterStatus.IN_REVIEW: "审核中",
    ChapterStatus.REJECT: "驳回",
    ChapterStatus.OBSOLETED: "已废弃",
}


@dataclass
class Chapter:
    """条款数据模型"""
    id: int | None = None
    term: str = ""
    test_content: str = ""
    standard: str = ""
    standard_version: str = ""
    version: str = "1.0"
    status: int = 0
    product_type: str = ""
    plan_sr: float = 1.0
    specific_product: str = ""
    folder_id: int = 0
    minio_file_url: str = ""
    quote_cnt: int = 0
    draft_by: str = ""
    review_by: str = ""
    review_opinion: str = ""
    create_by: str = ""
    update_by: str = ""
    create_time: int | None = None
    update_time: int | None = None

    def to_api_dict(self) -> dict:
        """序列化为 API 请求体（camelCase + folder 嵌套）"""
        d: dict = {}
        if self.id is not None:
            d["id"] = self.id
        d["term"] = self.term
        d["testContent"] = self.test_content
        d["standard"] = self.standard
        d["standardVersion"] = self.standard_version
        d["version"] = self.version
        d["status"] = self.status
        d["productType"] = self.product_type
        d["planSr"] = self.plan_sr
        d["specificProduct"] = self.specific_product
        d["folder"] = {"id": self.folder_id}
        return d

    @classmethod
    def from_api_dict(cls, data: dict) -> Chapter:
        """从 API 响应反序列化"""
        folder = data.get("folder") or {}
        draft_by_obj = data.get("draftBy") or {}
        review_by_obj = data.get("reviewBy") or {}
        return cls(
            id=data.get("id"),
            term=data.get("term", ""),
            test_content=data.get("testContent", ""),
            standard=data.get("standard", ""),
            standard_version=data.get("standardVersion", ""),
            version=data.get("version", "1.0"),
            status=data.get("status", 0),
            product_type=data.get("productType", ""),
            plan_sr=float(data.get("planSr", 1.0) or 1.0),
            specific_product=data.get("specificProduct", ""),
            folder_id=folder.get("id", 0) if isinstance(folder, dict) else 0,
            minio_file_url=data.get("minioFileUrl", ""),
            quote_cnt=data.get("quoteCnt", 0) or 0,
            draft_by=draft_by_obj.get("username", "") if isinstance(draft_by_obj, dict) else "",
            review_by=review_by_obj.get("username", "") if isinstance(review_by_obj, dict) else "",
            review_opinion=data.get("reviewOpinion", "") or "",
            create_by=data.get("createBy", ""),
            update_by=data.get("updateBy", ""),
            create_time=data.get("createTime"),
            update_time=data.get("updateTime"),
        )


@dataclass
class PageResult:
    """分页查询结果"""
    content: list[Chapter] = field(default_factory=list)
    total_elements: int = 0

    @classmethod
    def from_api_dict(cls, data: dict) -> PageResult:
        """从 API 分页响应反序列化"""
        items = [Chapter.from_api_dict(item) for item in data.get("content", [])]
        return cls(content=items, total_elements=data.get("totalElements", 0))


@dataclass
class ApiConfig:
    """API 连接配置"""
    base_url: str = "http://127.0.0.1:8080"
    username: str = ""
    password: str = ""
    rsa_private_key: str = ""
    token_cache_file: str = ".token_cache"
    token_idle_timeout: int = 7200
    request_timeout: int = 30
```

- [ ] **Step 4: 创建 __init__.py**

```python
"""条款管理模块"""

from .models import ApiConfig, Chapter, ChapterStatus, PageResult, STATUS_LABELS

__all__ = ["ApiConfig", "Chapter", "ChapterStatus", "PageResult", "STATUS_LABELS"]
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/tuv_tools/core/chapter/
git commit -m "feat(chapter): add data models and dependencies"
```

---

## Task 2: 模型序列化测试

**Files:**
- Create: `tests/test_models.py`

- [ ] **Step 1: 编写测试**

```python
"""测试条款数据模型序列化"""

from tuv_tools.core.chapter.models import Chapter, PageResult


class TestChapterSerialization:
    def test_to_api_dict_basic(self):
        ch = Chapter(term="10.2", test_content="温度测试", standard="IEC 60335",
                     version="1.0", product_type="家电", folder_id=5)
        d = ch.to_api_dict()
        assert d["term"] == "10.2"
        assert d["testContent"] == "温度测试"
        assert d["folder"] == {"id": 5}
        assert d["planSr"] == 1.0
        assert "id" not in d

    def test_to_api_dict_with_id(self):
        ch = Chapter(id=42, term="10.3", test_content="泄漏", standard="IEC 60335",
                     folder_id=1)
        d = ch.to_api_dict()
        assert d["id"] == 42

    def test_from_api_dict_full(self):
        data = {
            "id": 1, "term": "10.2", "testContent": "温度测试",
            "standard": "IEC 60335", "standardVersion": "6th",
            "version": "2.0", "status": 1, "productType": "家电",
            "planSr": 1.5, "specificProduct": "电饭煲",
            "folder": {"id": 3, "folderName": "EMC"},
            "minioFileUrl": "http://minio/file.docx",
            "quoteCnt": 2,
            "draftBy": {"username": "tyler"},
            "reviewBy": None,
            "reviewOpinion": None,
            "createBy": "admin", "updateBy": "admin",
            "createTime": 1716100000000, "updateTime": 1716100000000,
        }
        ch = Chapter.from_api_dict(data)
        assert ch.id == 1
        assert ch.test_content == "温度测试"
        assert ch.folder_id == 3
        assert ch.draft_by == "tyler"
        assert ch.review_by == ""
        assert ch.plan_sr == 1.5

    def test_from_api_dict_missing_fields(self):
        ch = Chapter.from_api_dict({"id": 99})
        assert ch.id == 99
        assert ch.term == ""
        assert ch.folder_id == 0

    def test_roundtrip(self):
        original = Chapter(id=10, term="11.1", test_content="能量限制",
                           standard="IEC 62368", folder_id=7, plan_sr=2.0)
        api_dict = original.to_api_dict()
        # 模拟后端返回（folder 展开为对象）
        api_dict["draftBy"] = None
        api_dict["reviewBy"] = None
        api_dict["createBy"] = ""
        api_dict["updateBy"] = ""
        api_dict["createTime"] = None
        api_dict["updateTime"] = None
        api_dict["minioFileUrl"] = ""
        api_dict["quoteCnt"] = 0
        api_dict["reviewOpinion"] = None
        restored = Chapter.from_api_dict(api_dict)
        assert restored.term == original.term
        assert restored.folder_id == original.folder_id


class TestPageResult:
    def test_from_api_dict(self):
        data = {
            "content": [
                {"id": 1, "term": "10.2", "testContent": "test"},
                {"id": 2, "term": "10.3", "testContent": "test2"},
            ],
            "totalElements": 42,
        }
        page = PageResult.from_api_dict(data)
        assert page.total_elements == 42
        assert len(page.content) == 2
        assert page.content[0].term == "10.2"

    def test_from_api_dict_empty(self):
        page = PageResult.from_api_dict({"content": [], "totalElements": 0})
        assert page.total_elements == 0
        assert page.content == []
```

- [ ] **Step 2: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_models.py
git commit -m "test(chapter): add model serialization tests"
```

---

## Task 3: HTTP 客户端

**Files:**
- Create: `src/tuv_tools/core/chapter/client.py`

- [ ] **Step 1: 实现 TuvClient**

```python
"""TUV 后端 HTTP 客户端"""

from __future__ import annotations

import requests


class TuvClient:
    """封装 requests.Session，自动管理 JWT Authorization 头"""

    def __init__(self, base_url: str, timeout: int = 30):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
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
        resp = self._session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp
```

- [ ] **Step 2: Commit**

```bash
git add src/tuv_tools/core/chapter/client.py
git commit -m "feat(chapter): add TuvClient HTTP wrapper"
```

---

## Task 4: RSA 加密

**Files:**
- Create: `src/tuv_tools/core/chapter/crypto.py`
- Create: `tests/test_crypto.py`

- [ ] **Step 1: 编写测试**

```python
"""测试 RSA 加密"""

import base64

from Crypto.PublicKey import RSA

from tuv_tools.core.chapter.crypto import derive_public_key, encrypt_password

# 生成测试用 1024-bit RSA 密钥对
_TEST_KEY = RSA.generate(1024)
_TEST_PRIVATE_B64 = base64.b64encode(_TEST_KEY.export_key("DER", pkcs=8)).decode()


class TestCrypto:
    def test_derive_public_key(self):
        pub_b64 = derive_public_key(_TEST_PRIVATE_B64)
        pub_der = base64.b64decode(pub_b64)
        pub_key = RSA.import_key(pub_der)
        assert pub_key.n == _TEST_KEY.n
        assert pub_key.e == _TEST_KEY.e

    def test_encrypt_password_produces_base64(self):
        encrypted = encrypt_password("123456", _TEST_PRIVATE_B64)
        # 结果应该是合法的 base64
        raw = base64.b64decode(encrypted)
        assert len(raw) > 0

    def test_encrypt_decrypt_roundtrip(self):
        from Crypto.Cipher import PKCS1_v1_5
        password = "test_password_123"
        encrypted = encrypt_password(password, _TEST_PRIVATE_B64)
        cipher = PKCS1_v1_5.new(_TEST_KEY)
        decrypted = cipher.decrypt(base64.b64decode(encrypted), sentinel=b"FAIL")
        assert decrypted.decode() == password

    def test_encrypt_long_password(self):
        long_pw = "a" * 200
        encrypted = encrypt_password(long_pw, _TEST_PRIVATE_B64)
        from Crypto.Cipher import PKCS1_v1_5
        cipher = PKCS1_v1_5.new(_TEST_KEY)
        raw = base64.b64decode(encrypted)
        # 分块解密（128 字节一块）
        key_size = 128
        blocks = [raw[i:i+key_size] for i in range(0, len(raw), key_size)]
        decrypted = b""
        for block in blocks:
            decrypted += cipher.decrypt(block, sentinel=b"FAIL")
        assert decrypted.decode() == long_pw
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL（crypto 模块不存在）

- [ ] **Step 3: 实现 crypto.py**

```python
"""RSA 密码加密（兼容后端 Java RsaUtils）"""

from __future__ import annotations

import base64

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


def derive_public_key(private_key_b64: str) -> str:
    """从 Base64 PKCS8 私钥推导公钥（DER 格式 Base64）"""
    private_der = base64.b64decode(private_key_b64)
    private_key = RSA.import_key(private_der)
    public_der = private_key.publickey().export_key("DER")
    return base64.b64encode(public_der).decode()


def encrypt_password(password: str, private_key_b64: str) -> str:
    """用 RSA 公钥分块加密密码，输出 Base64 密文"""
    pub_b64 = derive_public_key(private_key_b64)
    pub_der = base64.b64decode(pub_b64)
    pub_key = RSA.import_key(pub_der)
    cipher = PKCS1_v1_5.new(pub_key)

    data = password.encode("utf-8")
    key_size = pub_key.size_in_bytes()  # 128 for 1024-bit
    max_block = key_size - 11  # PKCS1 padding overhead

    encrypted = b""
    for i in range(0, len(data), max_block):
        block = data[i:i + max_block]
        encrypted += cipher.encrypt(block)

    return base64.b64encode(encrypted).decode()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_crypto.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/chapter/crypto.py tests/test_crypto.py
git commit -m "feat(chapter): add RSA password encryption"
```

---

## Task 5: 认证模块

**Files:**
- Create: `src/tuv_tools/core/chapter/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: 编写测试**

```python
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
        rsa_private_key="",  # 测试中 mock 掉加密
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

    def test_load_expired(self, tmp_cache):
        save_token_cache(str(tmp_cache), "old_token", "tyler")
        # 篡改时间为 3 小时前
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
    def test_cached_token_invalid_triggers_login(self, mock_encrypt, config, tmp_cache):
        save_token_cache(str(tmp_cache), "expired_token", "tyler")
        client = TuvClient(config.base_url)
        mock_encrypt.return_value = "encrypted_pw"
        # GET /auth/info 返回 401
        error_401 = requests.HTTPError(response=MagicMock(status_code=401))
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL（auth 模块不存在）

- [ ] **Step 3: 实现 auth.py**

```python
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
    Path(cache_path).write_text(json.dumps(data), encoding="utf-8")


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
    # 尝试从缓存恢复
    cached = load_token_cache(config.token_cache_file, config.token_idle_timeout)
    if cached:
        client.token = cached["token"]
        try:
            client.get("/auth/info")
            return True
        except requests.HTTPError:
            clear_token_cache(config.token_cache_file)
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
    save_token_cache(config.token_cache_file, token, config.username)
    return True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_auth.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/chapter/auth.py tests/test_auth.py
git commit -m "feat(chapter): add authentication with token caching"
```

---

## Task 6: 条款 API 函数

**Files:**
- Create: `src/tuv_tools/core/chapter/api.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: 编写测试**

```python
"""测试条款 API 函数"""

from unittest.mock import MagicMock

from tuv_tools.core.chapter.api import (
    create_chapter,
    delete_chapters,
    get_chapters,
    update_chapter,
)
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import Chapter


def _mock_client():
    return MagicMock(spec=TuvClient)


class TestGetChapters:
    def test_basic_query(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "content": [{"id": 1, "term": "10.2", "testContent": "test"}],
            "totalElements": 1,
        }
        result = get_chapters(client, page=0, size=20)
        assert result.total_elements == 1
        assert result.content[0].term == "10.2"
        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert call_kwargs[0][0] == "/api/chapter"
        params = call_kwargs[1]["params"]
        assert params["page"] == 0
        assert params["size"] == 20

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"content": [], "totalElements": 0}
        get_chapters(client, page=1, size=10, term="10.2", status=0)
        params = client.get.call_args[1]["params"]
        assert params["term"] == "10.2"
        assert params["status"] == 0
        assert "specificProduct" not in params


class TestCreateChapter:
    def test_success(self):
        client = _mock_client()
        client.post.return_value.status_code = 201
        ch = Chapter(term="10.2", test_content="温度", standard="IEC 60335", folder_id=1)
        result = create_chapter(client, ch)
        assert result is True
        body = client.post.call_args[1]["json"]
        assert body["term"] == "10.2"
        assert body["folder"] == {"id": 1}


class TestUpdateChapter:
    def test_success(self):
        client = _mock_client()
        client.put.return_value.status_code = 204
        ch = Chapter(id=42, term="10.2", test_content="更新", standard="IEC 60335", folder_id=1)
        result = update_chapter(client, ch)
        assert result is True
        body = client.put.call_args[1]["json"]
        assert body["id"] == 42


class TestDeleteChapters:
    def test_success(self):
        client = _mock_client()
        client.delete.return_value.status_code = 200
        result = delete_chapters(client, [1, 2, 3])
        assert result is True
        body = client.delete.call_args[1]["json"]
        assert body == [1, 2, 3]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api.py -v`
Expected: FAIL（api 模块不存在）

- [ ] **Step 3: 实现 api.py**

```python
"""条款 CRUD API 函数"""

from __future__ import annotations

from .client import TuvClient
from .models import Chapter, PageResult


def get_chapters(client: TuvClient, page: int = 0, size: int = 20, **filters) -> PageResult:
    """分页查询条款"""
    params: dict = {"page": page, "size": size}
    for key in ("folderId", "term", "testContent", "status", "standard",
                "standardVersion", "specificProduct", "version"):
        snake = _to_snake(key)
        value = filters.get(snake) or filters.get(key)
        if value is not None and value != "":
            params[key] = value
    resp = client.get("/api/chapter", params=params)
    return PageResult.from_api_dict(resp.json())


def create_chapter(client: TuvClient, chapter: Chapter) -> bool:
    """创建条款"""
    resp = client.post("/api/chapter", json=chapter.to_api_dict())
    return 200 <= resp.status_code < 300


def update_chapter(client: TuvClient, chapter: Chapter) -> bool:
    """更新条款"""
    resp = client.put("/api/chapter", json=chapter.to_api_dict())
    return 200 <= resp.status_code < 300


def delete_chapters(client: TuvClient, ids: list[int]) -> bool:
    """批量删除条款"""
    resp = client.delete("/api/chapter", json=ids)
    return 200 <= resp.status_code < 300


def _to_snake(camel: str) -> str:
    """camelCase -> snake_case"""
    result = []
    for ch in camel:
        if ch.isupper():
            result.append("_")
            result.append(ch.lower())
        else:
            result.append(ch)
    return "".join(result)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/chapter/api.py tests/test_api.py
git commit -m "feat(chapter): add chapter CRUD API functions"
```

---

## Task 7: 配置持久化

**Files:**
- Modify: `src/tuv_tools/config/settings.py`

- [ ] **Step 1: 扩展 settings.py 添加 ApiConfig 持久化**

在 `AppSettings` 类中添加 API 配置的加载和保存方法：

```python
"""全局配置管理"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _find_project_root() -> Path:
    """从当前文件向上查找包含 pyproject.toml 的目录作为项目根"""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


PROJECT_ROOT = _find_project_root()
RESOURCES_DIR = PROJECT_ROOT / "resources"
API_CONFIG_FILE = PROJECT_ROOT / "api_config.json"


@dataclass
class AppSettings:
    """应用全局配置"""
    default_rules_path: Path = field(default_factory=lambda: RESOURCES_DIR / "inline_clean_rules.json")

    def load_inline_clean_patterns(self, rules_path: Path | None = None) -> list[re.Pattern[str]]:
        """加载行内清洗规则为编译后的正则列表"""
        path = rules_path or self.default_rules_path
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = data.get("inline_clean_rules", [])
        patterns: list[re.Pattern[str]] = []
        for rule in rules:
            pattern = rule.get("pattern", "").strip()
            if not pattern:
                continue
            patterns.append(re.compile(pattern, re.IGNORECASE))
        return patterns

    @staticmethod
    def load_api_config(config_path: Path | None = None):
        """加载 API 配置，不存在则返回 None"""
        from tuv_tools.core.chapter.models import ApiConfig
        path = config_path or API_CONFIG_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ApiConfig(**{k: v for k, v in data.items()
                               if k in ApiConfig.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def save_api_config(config, config_path: Path | None = None) -> None:
        """保存 API 配置到 JSON 文件"""
        from dataclasses import asdict
        path = config_path or API_CONFIG_FILE
        path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False),
                        encoding="utf-8")
```

- [ ] **Step 2: 运行现有测试确认无回归**

Run: `pytest -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add src/tuv_tools/config/settings.py
git commit -m "feat(config): add ApiConfig load/save to settings"
```

---

## Task 8: 条款管理 UI 视图

**Files:**
- Create: `src/tuv_tools/ui/views/chapter_view.py`
- Modify: `src/tuv_tools/ui/main_window.py`

- [ ] **Step 1: 创建 chapter_view.py（第一部分：类骨架 + 工具栏）**

```python
"""条款管理视图"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter import ApiConfig, Chapter, ChapterStatus, PageResult, STATUS_LABELS
from tuv_tools.core.chapter.api import create_chapter, delete_chapters, get_chapters, update_chapter
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient


class ChapterWorker(QThread):
    """后台网络操作线程"""
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.result_ready.emit(result)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class ChapterView(QWidget):
    """条款管理视图"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._client: TuvClient | None = None
        self._config: ApiConfig | None = None
        self._worker: ChapterWorker | None = None
        self._current_page = 0
        self._page_size = 20
        self._total = 0
        self._connected = False
        self._setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._connected:
            self._try_connect()

    def _try_connect(self):
        self._config = self._settings.load_api_config()
        if not self._config:
            self._show_settings_dialog()
            return
        self._client = TuvClient(self._config.base_url, self._config.request_timeout)
        self._run_worker(
            lambda: auto_login(self._client, self._config),
            self._on_login_result,
            self._on_login_error,
        )

    def _on_login_result(self, success):
        if success:
            self._connected = True
            self._status_label.setText("● 已连接")
            self._status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self._fetch_chapters()
        else:
            self._status_label.setText("● 未连接")
            self._status_label.setStyleSheet("color: #f44336; font-weight: bold;")

    def _on_login_error(self, msg):
        self._status_label.setText("● 未连接")
        self._status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        self._info_label.setText(f"Connection error: {msg}")
```

- [ ] **Step 2: 添加 _setup_ui 方法（工具栏 + 表格 + 分页）**

```python
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # 顶部状态栏
        top_row = QHBoxLayout()
        self._status_label = QLabel("● 未连接")
        self._status_label.setStyleSheet("color: #888; font-weight: bold;")
        top_row.addWidget(self._status_label)
        top_row.addStretch()
        self._settings_btn = QPushButton("⚙ 设置")
        self._settings_btn.clicked.connect(self._show_settings_dialog)
        top_row.addWidget(self._settings_btn)
        layout.addLayout(top_row)

        # 查询工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Folder:"))
        self._folder_edit = QLineEdit()
        self._folder_edit.setFixedWidth(60)
        toolbar.addWidget(self._folder_edit)
        toolbar.addWidget(QLabel("条款号:"))
        self._term_edit = QLineEdit()
        self._term_edit.setFixedWidth(80)
        toolbar.addWidget(self._term_edit)
        toolbar.addWidget(QLabel("标准:"))
        self._standard_edit = QLineEdit()
        self._standard_edit.setFixedWidth(100)
        toolbar.addWidget(self._standard_edit)
        toolbar.addWidget(QLabel("状态:"))
        self._status_combo = QComboBox()
        self._status_combo.addItem("全部", None)
        for val, label in STATUS_LABELS.items():
            self._status_combo.addItem(label, val)
        self._status_combo.setFixedWidth(80)
        toolbar.addWidget(self._status_combo)

        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._on_query)
        toolbar.addWidget(self._query_btn)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._on_clear_filters)
        toolbar.addWidget(self._clear_btn)
        toolbar.addStretch()
        self._add_btn = QPushButton("+ 新增")
        self._add_btn.setStyleSheet("background-color:#4caf50;color:white;font-weight:bold;border:none;border-radius:4px;padding:6px 16px;")
        self._add_btn.clicked.connect(self._show_create_dialog)
        toolbar.addWidget(self._add_btn)
        layout.addLayout(toolbar)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(["ID", "条款号", "标准", "版本", "测试内容", "状态", "操作"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        # 分页
        page_row = QHBoxLayout()
        self._prev_btn = QPushButton("◀ 上一页")
        self._prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self._prev_btn)
        self._page_label = QLabel("第 0/0 页")
        page_row.addWidget(self._page_label)
        self._next_btn = QPushButton("下一页 ▶")
        self._next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self._next_btn)
        page_row.addStretch()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888; font-size: 12px;")
        page_row.addWidget(self._info_label)
        layout.addLayout(page_row)
```

- [ ] **Step 3: 添加查询/分页/CRUD 方法**

```python
    def _build_filters(self) -> dict:
        filters = {}
        folder_text = self._folder_edit.text().strip()
        if folder_text:
            filters["folderId"] = int(folder_text)
        term = self._term_edit.text().strip()
        if term:
            filters["term"] = term
        standard = self._standard_edit.text().strip()
        if standard:
            filters["standard"] = standard
        status_val = self._status_combo.currentData()
        if status_val is not None:
            filters["status"] = status_val
        return filters

    def _fetch_chapters(self):
        if not self._client:
            return
        filters = self._build_filters()
        self._set_buttons_enabled(False)
        self._run_worker(
            lambda: get_chapters(self._client, self._current_page, self._page_size, **filters),
            self._on_chapters_loaded,
            self._on_error,
        )

    def _on_chapters_loaded(self, page_result: PageResult):
        self._total = page_result.total_elements
        self._populate_table(page_result.content)
        total_pages = max(1, (self._total + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"第 {self._current_page + 1}/{total_pages} 页")
        self._info_label.setText(f"共 {self._total} 条，每页 {self._page_size}")
        self._set_buttons_enabled(True)

    def _populate_table(self, chapters: list[Chapter]):
        self._table.setRowCount(len(chapters))
        for row, ch in enumerate(chapters):
            self._table.setItem(row, 0, QTableWidgetItem(str(ch.id or "")))
            self._table.setItem(row, 1, QTableWidgetItem(ch.term))
            self._table.setItem(row, 2, QTableWidgetItem(ch.standard))
            self._table.setItem(row, 3, QTableWidgetItem(ch.version))
            self._table.setItem(row, 4, QTableWidgetItem(ch.test_content))
            status_text = STATUS_LABELS.get(ch.status, str(ch.status))
            self._table.setItem(row, 5, QTableWidgetItem(status_text))
            # 操作列
            ops = QWidget()
            ops_layout = QHBoxLayout(ops)
            ops_layout.setContentsMargins(4, 0, 4, 0)
            edit_btn = QPushButton("编辑")
            edit_btn.setFixedHeight(24)
            edit_btn.clicked.connect(lambda _, c=ch: self._show_edit_dialog(c))
            ops_layout.addWidget(edit_btn)
            if ch.status == ChapterStatus.DRAFT and ch.quote_cnt == 0:
                del_btn = QPushButton("删除")
                del_btn.setFixedHeight(24)
                del_btn.setStyleSheet("color: #f44336;")
                del_btn.clicked.connect(lambda _, c=ch: self._confirm_delete(c))
                ops_layout.addWidget(del_btn)
            self._table.setCellWidget(row, 6, ops)

    def _on_query(self):
        self._current_page = 0
        self._fetch_chapters()

    def _on_clear_filters(self):
        self._folder_edit.clear()
        self._term_edit.clear()
        self._standard_edit.clear()
        self._status_combo.setCurrentIndex(0)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._fetch_chapters()

    def _next_page(self):
        total_pages = max(1, (self._total + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._fetch_chapters()

    def _confirm_delete(self, chapter: Chapter):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除条款 {chapter.term}？\n（只有草稿状态且未被引用的条款可删除）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker(
                lambda: delete_chapters(self._client, [chapter.id]),
                lambda _: self._fetch_chapters(),
                self._on_error,
            )

    def _on_error(self, msg: str):
        self._info_label.setText(f"Error: {msg}")
        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled: bool):
        self._query_btn.setEnabled(enabled)
        self._add_btn.setEnabled(enabled)
        self._prev_btn.setEnabled(enabled)
        self._next_btn.setEnabled(enabled)

    def _run_worker(self, func, on_result, on_error):
        self._worker = ChapterWorker(func)
        self._worker.result_ready.connect(on_result)
        self._worker.error_occurred.connect(on_error)
        self._worker.start()
```

- [ ] **Step 4: 添加对话框方法（设置 + 新增/编辑）**

```python
    def _show_settings_dialog(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            self._settings.save_api_config(self._config)
            self._connected = False
            self._try_connect()

    def _show_create_dialog(self):
        dlg = ChapterDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            chapters = dlg.get_chapters()
            if len(chapters) == 1:
                self._run_worker(
                    lambda: create_chapter(self._client, chapters[0]),
                    lambda _: self._fetch_chapters(),
                    self._on_error,
                )
            else:
                self._batch_create(chapters)

    def _show_edit_dialog(self, chapter: Chapter):
        dlg = ChapterDialog(chapter=chapter, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_chapters()[0]
            updated.id = chapter.id
            self._run_worker(
                lambda: update_chapter(self._client, updated),
                lambda _: self._fetch_chapters(),
                self._on_error,
            )

    def _batch_create(self, chapters: list[Chapter]):
        results = {"success": 0, "errors": []}
        def do_batch():
            for i, ch in enumerate(chapters):
                try:
                    create_chapter(self._client, ch)
                    results["success"] += 1
                except Exception as e:
                    results["errors"].append(f"{ch.term}: {e}")
            return results
        self._run_worker(do_batch, self._on_batch_done, self._on_error)

    def _on_batch_done(self, results):
        msg = f"成功: {results['success']} 条"
        if results["errors"]:
            msg += f"\n失败: {len(results['errors'])} 条\n" + "\n".join(results["errors"])
        QMessageBox.information(self, "批量创建结果", msg)
        self._fetch_chapters()
```

- [ ] **Step 5: 添加 SettingsDialog 和 ChapterDialog 类**

```python
class SettingsDialog(QDialog):
    """API 设置对话框"""

    def __init__(self, config: ApiConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)

        self._url_edit = QLineEdit(config.base_url if config else "http://127.0.0.1:8080")
        layout.addRow("API URL:", self._url_edit)
        self._user_edit = QLineEdit(config.username if config else "")
        layout.addRow("用户名:", self._user_edit)
        self._pass_edit = QLineEdit(config.password if config else "")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("密码:", self._pass_edit)
        self._key_edit = QPlainTextEdit(config.rsa_private_key if config else "")
        self._key_edit.setMaximumHeight(100)
        layout.addRow("RSA 私钥:", self._key_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_config(self) -> ApiConfig:
        return ApiConfig(
            base_url=self._url_edit.text().strip(),
            username=self._user_edit.text().strip(),
            password=self._pass_edit.text(),
            rsa_private_key=self._key_edit.toPlainText().strip(),
        )


class ChapterDialog(QDialog):
    """新增/编辑条款对话框"""

    def __init__(self, chapter: Chapter | None = None, parent=None):
        super().__init__(parent)
        self._editing = chapter is not None
        self.setWindowTitle("编辑条款" if self._editing else "新增条款")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)

        if not self._editing:
            self._batch_cb = QCheckBox("批量模式（条款号和测试内容用逗号分隔）")
            layout.addRow(self._batch_cb)

        self._folder_edit = QLineEdit(str(chapter.folder_id) if chapter else "")
        layout.addRow("文件夹 ID *:", self._folder_edit)
        self._term_edit = QLineEdit(chapter.term if chapter else "")
        layout.addRow("条款编号 *:", self._term_edit)
        self._content_edit = QLineEdit(chapter.test_content if chapter else "")
        layout.addRow("测试内容 *:", self._content_edit)
        self._product_edit = QLineEdit(chapter.product_type if chapter else "")
        layout.addRow("产品类别 *:", self._product_edit)
        self._sr_edit = QLineEdit(str(chapter.plan_sr) if chapter else "1")
        layout.addRow("PlanSR *:", self._sr_edit)
        self._standard_edit = QLineEdit(chapter.standard if chapter else "")
        layout.addRow("标准 *:", self._standard_edit)
        self._version_edit = QLineEdit(chapter.version if chapter else "1.0")
        layout.addRow("条款版本 *:", self._version_edit)
        self._std_ver_edit = QLineEdit(chapter.standard_version if chapter else "")
        layout.addRow("标准版本:", self._std_ver_edit)
        self._specific_edit = QLineEdit(chapter.specific_product if chapter else "")
        layout.addRow("特定产品:", self._specific_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_chapters(self) -> list[Chapter]:
        base = Chapter(
            folder_id=int(self._folder_edit.text().strip() or "0"),
            product_type=self._product_edit.text().strip(),
            plan_sr=float(self._sr_edit.text().strip() or "1"),
            standard=self._standard_edit.text().strip(),
            version=self._version_edit.text().strip(),
            standard_version=self._std_ver_edit.text().strip(),
            specific_product=self._specific_edit.text().strip(),
        )
        if self._editing or not self._batch_cb.isChecked():
            base.term = self._term_edit.text().strip()
            base.test_content = self._content_edit.text().strip()
            return [base]
        # 批量模式
        terms = [t.strip() for t in self._term_edit.text().split(",") if t.strip()]
        contents = [c.strip() for c in self._content_edit.text().split(",") if c.strip()]
        if len(terms) != len(contents):
            contents = contents + [""] * (len(terms) - len(contents))
        chapters = []
        for term, content in zip(terms, contents):
            from dataclasses import replace
            ch = replace(base, term=term, test_content=content)
            chapters.append(ch)
        return chapters
```

- [ ] **Step 6: 注册视图到 main_window.py**

修改 `src/tuv_tools/ui/main_window.py`：

```python
from .views.chapter_view import ChapterView

def _register_views(self):
    """注册所有功能视图（新增功能在此添加）"""
    self._add_view("文档拆分", SplitterView())
    self._add_view("条款管理", ChapterView())
```

- [ ] **Step 7: 更新 __init__.py 导出**

更新 `src/tuv_tools/core/chapter/__init__.py`：

```python
"""条款管理模块"""

from .api import create_chapter, delete_chapters, get_chapters, update_chapter
from .auth import auto_login
from .client import TuvClient
from .models import ApiConfig, Chapter, ChapterStatus, PageResult, STATUS_LABELS

__all__ = [
    "ApiConfig", "Chapter", "ChapterStatus", "PageResult", "STATUS_LABELS",
    "TuvClient", "auto_login",
    "create_chapter", "delete_chapters", "get_chapters", "update_chapter",
]
```

- [ ] **Step 8: 运行应用验证 UI**

Run: `python main.py`
Expected: 应用启动，侧边栏显示"条款管理"入口，点击后显示条款管理视图

- [ ] **Step 9: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_view.py src/tuv_tools/ui/main_window.py src/tuv_tools/core/chapter/__init__.py
git commit -m "feat(chapter): add chapter management UI view"
```

---

## Task 9: 最终集成验证

**Files:** (无新文件)

- [ ] **Step 1: 运行全部测试**

Run: `pytest -v`
Expected: 全部 PASS

- [ ] **Step 2: 启动应用手动验证**

Run: `python main.py`

验证清单：
1. 侧边栏显示"文档拆分"和"条款管理"两个入口
2. 点击"条款管理"→ 弹出设置对话框（首次无配置）
3. 填入配置保存 → 自动尝试连接
4. 连接成功 → 状态显示"已连接"，加载数据
5. 查询/分页/新增/编辑/删除功能正常
6. "文档拆分"功能不受影响

- [ ] **Step 3: 最终 Commit**

```bash
git add -A
git commit -m "feat: complete chapter management module integration"
```
