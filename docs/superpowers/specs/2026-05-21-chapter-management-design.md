# 条款管理模块设计

## 概述

在 tuv-tools（PySide6 桌面应用）中新增"条款管理"功能模块，对接 TUV 后端 API，提供条款的查询、创建、编辑、删除及批量创建能力。

### 范围

- 认证（RSA 加密登录 + Token 缓存）
- 条款 CRUD（查询/创建/编辑/删除 + 批量创建）
- **不含**：审批工作流（requestReview/chapterReview/upgrade/obsoleted/recover）

### 约束

- 后端为 Spring Boot（eladmin 框架），API 风格为 RESTful + Spring Data 分页
- 登录需 RSA 加密密码 + 验证码字段（当前环境无验证码，code/uuid 传空）
- 只有草稿状态且未被模板引用的条款可删除

---

## 架构

采用方案 A：独立模块，与现有 `splitter` 平行。

```
src/tuv_tools/
├── core/
│   ├── splitter/              # 现有 - 文档拆分
│   └── chapter/               # 新增 - 条款管理
│       ├── __init__.py
│       ├── client.py          # TuvClient HTTP 封装
│       ├── crypto.py          # RSA 加密
│       ├── auth.py            # 认证逻辑 + Token 缓存
│       ├── api.py             # 条款 CRUD 函数
│       └── models.py          # 数据模型
├── config/
│   └── settings.py            # 扩展 AppSettings，加入 ApiConfig
├── ui/
│   └── views/
│       ├── splitter_view.py   # 现有
│       └── chapter_view.py    # 新增 - 条款管理视图
```

导航：侧边栏新增"条款管理"入口，与"文档拆分"并列。

---

## 数据模型

### ChapterStatus 枚举

```python
class ChapterStatus(IntEnum):
    DRAFT = 0        # 草稿
    VALID = 1        # 有效
    INVALID = 2      # 无效
    IN_REVIEW = 3    # 审核中
    REJECT = 4       # 驳回
    OBSOLETED = 5    # 已废弃
```

### Chapter dataclass

```python
@dataclass
class Chapter:
    id: int | None = None
    term: str = ""                  # 条款编号
    test_content: str = ""          # 测试内容 (API: testContent)
    standard: str = ""              # 标准名称
    standard_version: str = ""      # 标准版本 (API: standardVersion)
    version: str = "1.0"            # 条款版本
    status: int = 0                 # 状态 (ChapterStatus)
    product_type: str = ""          # 产品类别 (API: productType)
    plan_sr: float = 1.0            # PlanSR (API: planSr, BigDecimal)
    specific_product: str = ""      # 特定产品 (API: specificProduct)
    folder_id: int = 0              # 归属文件夹 (API: folder.id)
    minio_file_url: str = ""        # DOCX 文件链接 (API: minioFileUrl)
    quote_cnt: int = 0              # 被模板引用次数 (API: quoteCnt)
    draft_by: str = ""              # 草拟人用户名
    review_by: str = ""             # 审核人用户名
    review_opinion: str = ""        # 审核意见 (API: reviewOpinion)
    create_by: str = ""             # 创建人
    update_by: str = ""             # 更新人
    create_time: int | None = None  # 创建时间 (时间戳 ms)
    update_time: int | None = None  # 更新时间 (时间戳 ms)
```

序列化规则：
- Python snake_case → API camelCase（`test_content` → `testContent`）
- `folder_id` 序列化为嵌套对象 `{"folder": {"id": N}}`
- 创建时后端自动设置 `status=0`, `draftBy=当前用户`, `quoteCnt=0`

### PageResult dataclass

```python
@dataclass
class PageResult:
    content: list[Chapter]
    total_elements: int
```

### ApiConfig dataclass

```python
@dataclass
class ApiConfig:
    base_url: str = "http://127.0.0.1:8080"
    username: str = ""
    password: str = ""
    rsa_private_key: str = ""       # Base64 PKCS8 私钥
    token_cache_file: str = ".token_cache"
    token_idle_timeout: int = 7200  # 秒
    request_timeout: int = 30       # 秒
```

持久化方式：JSON 文件（`api_config.json`），存储在项目根目录或用户目录。

---

## API 接口契约

### 认证

| 方法 | 路径 | 说明 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/auth/login` | 登录 | `{username, password, code, uuid}` | `{token: "Bearer xxx", user: {...}}` |
| GET | `/auth/info` | 验证 Token | 无 | 用户信息 JSON |
| DELETE | `/auth/logout` | 登出 | 无 | 无 |

- `password` 为 RSA 公钥加密后的 Base64 字符串
- `code` 和 `uuid` 当前传空字符串

### 条款 CRUD

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/api/chapter` | 分页查询 | Query: page, size, folderId, term, testContent, status, standard, standardVersion, specificProduct, version | `{content: [], totalElements: N}` |
| POST | `/api/chapter` | 创建 | Body: Chapter JSON | `201 Created`（无 body） |
| PUT | `/api/chapter` | 更新 | Body: Chapter JSON（含 id） | `204 No Content` |
| DELETE | `/api/chapter` | 删除 | Body: `[id1, id2, ...]` | `200 OK` |

查询参数说明：
- `page`: 0-based 页码
- `size`: 每页条数
- 条件字段均为可选，非空时才传递
- `term`, `testContent`, `standard`, `standardVersion`, `specificProduct` 为 LIKE 模糊匹配
- `status` 为精确匹配
- 后端自动按当前用户 productType 过滤

---

## 核心逻辑层

### client.py — HTTP 客户端

基于 `requests.Session`：
- `token` property setter 自动管理 `Authorization: Bearer <token>` 头
- `get/post/put/delete` 方法，统一 timeout 和 `raise_for_status()`
- 返回 `requests.Response` 对象

### crypto.py — RSA 加密

- 从 Base64 PKCS8 私钥推导公钥
- PKCS1_v1_5 分块加密（1024-bit key → 117 字节块）
- 输出 Base64 密文
- 兼容后端 Java `RsaUtils.decryptByPrivateKey`

### auth.py — 认证

流程：
1. 读取 `.token_cache`（JSON: `{token, username, time}`）
2. 缓存有效（未超时）→ 设置 token → `GET /auth/info` 验证
3. 验证通过 → 返回成功
4. 缓存无效或验证失败 → RSA 加密密码 → `POST /auth/login`（code="", uuid=""）
5. 登录成功 → 去掉 "Bearer " 前缀 → 保存 token 到缓存

### api.py — 条款操作

函数式设计，每个函数接收 `client: TuvClient`：

```python
def get_chapters(client, page=0, size=20, **filters) -> PageResult
def create_chapter(client, chapter: Chapter) -> bool
def update_chapter(client, chapter: Chapter) -> bool
def delete_chapters(client, ids: list[int]) -> bool
```

批量创建：调用层循环调用 `create_chapter`（后端无批量接口）。

---

## UI 层

### 布局：顶部工具栏 + 全宽表格

```
┌─────────────────────────────────────────────────────────┐
│ [状态: ● 已连接]                             [⚙ 设置]   │
├─────────────────────────────────────────────────────────┤
│ Folder:[___] 条款号:[___] 标准:[___] 状态:[▼]           │
│                                   [查询] [清空]  [+新增] │
├─────────────────────────────────────────────────────────┤
│ ID | 条款号 | 标准 | 版本 | 测试内容 | 状态 | 操作       │
│ ─────────────────────────────────────────────────────── │
│  1 | 10.2  | IEC..| 1.0 | 温度测试 | 草稿 | 编辑 删除  │
│  2 | 10.3  | IEC..| 2.0 | 泄漏电流 | 有效 | 编辑       │
├─────────────────────────────────────────────────────────┤
│ ◀ 1 [2] 3 ▶                          共 96 条，每页 20  │
└─────────────────────────────────────────────────────────┘
```

### 交互流程

1. 首次进入视图 → 检查 `ApiConfig` 是否已配置 → 无则弹出设置对话框
2. 有配置 → 后台线程自动登录 → 成功则加载首页数据
3. 登录失败 → 状态指示器显示"未连接"，用户可点击设置按钮重新配置
4. 查询/创建/编辑/删除均在后台线程执行，通过 Signal 回调更新 UI

### 对话框

**设置对话框**：
- API URL（文本输入）
- 用户名（文本输入）
- 密码（密码输入）
- RSA 私钥（多行文本，Base64）
- 保存后写入 `api_config.json`

**新增/编辑对话框**：
- 归属文件夹 ID *（必填）
- 条款编号 *（必填，批量时逗号分隔）
- 测试内容 *（必填，批量时逗号分隔）
- 产品类别 *
- PlanSR *（默认 1）
- 标准 *
- 条款版本 *（默认 "1.0"）
- 标准版本（可选）
- 特定产品（可选）
- 批量模式开关（勾选后条款号和测试内容支持逗号分隔多条）

**删除确认**：简单确认对话框，提示"只有草稿状态且未被引用的条款可删除"。

### 后台线程模式

沿用项目现有 `QThread + Signal` 模式：

```python
class ChapterWorker(QThread):
    result_ready = Signal(object)   # 成功结果
    error_occurred = Signal(str)    # 错误信息
```

每次网络操作创建一个 Worker 实例，完成后通过 Signal 回调主线程。

---

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 网络不可达 / 超时 | 状态指示器变红 + 状态栏提示，不弹窗 |
| 401 Unauthorized | 清除 token 缓存，状态显示"未连接" |
| 403 Forbidden | 状态栏提示"权限不足" |
| 4xx/5xx 业务错误 | 状态栏显示错误信息，操作按钮恢复可用 |
| 批量创建部分失败 | 完成后弹出汇总窗口（成功 N 条 + 失败列表） |
| 删除受限（非草稿/被引用） | 状态栏提示具体原因 |

---

## 依赖变更

`pyproject.toml` 新增：

```toml
dependencies = [
    "PySide6>=6.6.0",
    "requests>=2.28.0",
    "pycryptodome>=3.15.0",
]
```

---

## 测试策略

- `crypto.py`：验证加密输出格式与后端解密兼容
- `auth.py`：token 缓存读写、过期判断、登录流程（mock HTTP）
- `api.py`：请求参数序列化（snake_case → camelCase、folder 嵌套）、响应反序列化
- `models.py`：序列化/反序列化往返一致性
- UI 层：手动验证

---

## 注册入口

在 `main_window.py:_register_views()` 中添加：

```python
from .views.chapter_view import ChapterView

def _register_views(self):
    self._add_view("文档拆分", SplitterView())
    self._add_view("条款管理", ChapterView())
```
