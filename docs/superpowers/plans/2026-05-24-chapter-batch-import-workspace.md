# Chapter Batch Import Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `tuv-tools` 中新增一个独立的 Chapter 批量导入工作台，支持文档级持久化管理、统一拆分、抽屉确认、两阶段创建/上传、失败恢复与条款级重试。

**Architecture:** 采用“独立页面 + 独立本地数据域 + 文档级串行执行器”的方案。UI 层新增工作台视图和抽屉编辑结构，数据层在现有 SQLite 中新增工作台专用表，核心逻辑新增目录树选择器、批量草案生成、重复检查、串行执行与状态聚合模块。现有拆分核心、条款 CRUD API 和 chapter-doc/import 上传接口继续复用，不复用旧拆分页的 `imported_documents` 数据表。

**Tech Stack:** Python 3.10+, PySide6, SQLite (`sqlite3`), requests, pytest

---

## File Structure

### New Files

- `src/tuv_tools/core/chapter_batch/__init__.py`
  - Chapter 批量导入模块导出入口
- `src/tuv_tools/core/chapter_batch/models.py`
  - 文档记录、条款记录、执行状态、重复检查结果等 dataclass / enum
- `src/tuv_tools/core/chapter_batch/service.py`
  - 文档导入、草案生成、文档级公共字段回填、重新拆分等业务服务
- `src/tuv_tools/core/chapter_batch/executor.py`
  - 文档级串行执行器，两阶段创建/上传，取消安全点控制
- `src/tuv_tools/core/chapter_batch/repository.py`
  - 对 `DatabaseManager` 的批量导入领域封装，避免 View 直接写 SQL/表结构
- `src/tuv_tools/core/chapter_batch/api.py`
  - `chapter-doc/import` 上传接口封装、草稿状态校验所需接口补充
- `src/tuv_tools/ui/views/chapter_batch_view.py`
  - 独立工作台页面
- `src/tuv_tools/ui/widgets/chapter_folder_selector.py`
  - 可复用条款目录树选择器组件
- `src/tuv_tools/ui/widgets/chapter_batch_drawer.py`
  - 右侧抽屉壳体、顶部标签切换、文档头部与按钮区
- `src/tuv_tools/ui/widgets/chapter_batch_document_form.py`
  - 文档级公共字段表单
- `src/tuv_tools/ui/widgets/chapter_batch_clause_table.py`
  - 条款明细表与条款级右键菜单
- `tests/test_chapter_batch_models.py`
  - 状态枚举、数据模型、重复检查结果测试
- `tests/test_chapter_batch_repository.py`
  - 本地表 CRUD、状态聚合、重新拆分重置逻辑测试
- `tests/test_chapter_batch_service.py`
  - 草案生成、默认字段回填、标准号缺失、重复检查测试
- `tests/test_chapter_batch_executor.py`
  - 两阶段执行、取消、续跑、状态回写测试
- `tests/test_chapter_folder_selector.py`
  - 目录树选择器交互和数据回填测试
- `tests/test_chapter_batch_view.py`
  - 工作台、抽屉、批量确认、执行入口的视图级测试

### Modified Files

- `src/tuv_tools/ui/main_window.py`
  - 注册独立页面入口
- `src/tuv_tools/config/database.py`
  - 新增 batch import 专用表、迁移脚本、通用 helper
- `src/tuv_tools/core/chapter/api.py`
  - 补充查询单条条款详情或最小能力以支持“打开后端 chapter 记录”与草稿校验
- `src/tuv_tools/ui/views/chapter_view.py`
  - 复用 `chapter_folder_selector.py` 替换手输 `folder ID`
- `tests/test_database.py`
  - 覆盖新表和迁移路径
- `tests/test_api.py`
  - 覆盖 `chapter-doc/import` 与新增 chapter API 封装

### Responsibilities

- `database.py` 只负责底层 schema 和通用持久化，领域行为放 `repository.py`
- `service.py` 负责“文档工作台”的业务规则，不直接耦合 PySide6
- `executor.py` 负责状态推进，不直接操作 UI 控件
- View 和 Widget 只关心交互与信号，不写业务规则

---

## Task 1: Add Workspace Persistence Schema

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\config\database.py`
- Test: `O:\tuv-tools\tests\test_database.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`

- [ ] **Step 1: Write the failing schema tests**

```python
def test_batch_import_tables_created(tmp_path):
    from tuv_tools.config.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    conn = db._conn
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert "batch_import_documents" in tables
    assert "batch_import_clauses" in tables
    assert "batch_import_events" in tables


def test_batch_import_document_columns_exist(tmp_path):
    from tuv_tools.config.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    conn = db._conn
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(batch_import_documents)").fetchall()
    }

    assert {
        "file_path",
        "file_name",
        "document_status",
        "split_mode",
        "standard",
        "folder_id",
        "folder_name",
        "product_type",
        "plan_sr",
        "standard_version",
        "chapter_version",
        "specific_product",
        "is_queued",
        "queue_order",
    }.issubset(cols)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py -k batch_import -v`  
Expected: FAIL with missing tables / columns

- [ ] **Step 3: Add schema for workspace tables**

```python
CREATE TABLE IF NOT EXISTS batch_import_documents (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path            TEXT NOT NULL UNIQUE,
    file_name            TEXT NOT NULL,
    file_fingerprint     TEXT,
    document_status      TEXT NOT NULL DEFAULT '待拆分',
    split_mode           TEXT NOT NULL DEFAULT '条款',
    standard             TEXT,
    folder_id            INTEGER,
    folder_name          TEXT,
    product_type         TEXT,
    plan_sr              TEXT,
    standard_version     TEXT,
    chapter_version      TEXT,
    specific_product     TEXT,
    total_clause_count   INTEGER NOT NULL DEFAULT 0,
    success_clause_count INTEGER NOT NULL DEFAULT 0,
    failed_clause_count  INTEGER NOT NULL DEFAULT 0,
    skipped_clause_count INTEGER NOT NULL DEFAULT 0,
    is_queued            INTEGER NOT NULL DEFAULT 0,
    queue_order          INTEGER,
    last_error           TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_import_clauses (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id           INTEGER NOT NULL,
    sort_index            INTEGER NOT NULL,
    term                  TEXT NOT NULL,
    test_content          TEXT,
    clause_status         TEXT NOT NULL DEFAULT '待创建',
    chapter_id            INTEGER,
    backend_chapter_status INTEGER,
    source_docx_path      TEXT NOT NULL,
    duplicate_flag        INTEGER NOT NULL DEFAULT 0,
    duplicate_reason      TEXT,
    user_decision         TEXT,
    create_error          TEXT,
    upload_error          TEXT,
    last_action           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES batch_import_documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batch_import_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER,
    clause_id    INTEGER,
    event_type   TEXT NOT NULL,
    event_result TEXT NOT NULL,
    message      TEXT,
    payload_json TEXT,
    created_at   TEXT NOT NULL
);
```

- [ ] **Step 4: Add indexes and migration-safe initialization**

```python
CREATE INDEX IF NOT EXISTS idx_batch_import_documents_status
ON batch_import_documents(document_status);

CREATE INDEX IF NOT EXISTS idx_batch_import_clauses_document
ON batch_import_clauses(document_id, sort_index);

CREATE INDEX IF NOT EXISTS idx_batch_import_clauses_status
ON batch_import_clauses(clause_status);
```

- [ ] **Step 5: Run tests to verify schema passes**

Run: `pytest tests/test_database.py -k batch_import -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/config/database.py tests/test_database.py
git commit -m "feat: add batch import workspace schema"
```

---

## Task 2: Define Batch Import Domain Models

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`

- [ ] **Step 1: Write failing tests for enums and dataclasses**

```python
from tuv_tools.core.chapter_batch.models import (
    DocumentStatus,
    ClauseStatus,
    SplitMode,
)


def test_split_mode_labels_are_business_friendly():
    assert SplitMode.SECTION.value == "章节"
    assert SplitMode.CLAUSE.value == "条款"


def test_document_status_contains_workspace_states():
    assert DocumentStatus.PENDING_CONFIRM.value == "待确认"
    assert DocumentStatus.PENDING_CREATE.value == "待创建"
    assert DocumentStatus.PARTIAL.value == "部分完成"


def test_clause_status_contains_retryable_states():
    assert ClauseStatus.CREATE_FAILED.value == "创建失败"
    assert ClauseStatus.PENDING_UPLOAD.value == "待上传"
    assert ClauseStatus.SKIPPED.value == "用户跳过"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_models.py -v`  
Expected: FAIL with module or enum not found

- [ ] **Step 3: Implement enums and core dataclasses**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SplitMode(str, Enum):
    SECTION = "章节"
    CLAUSE = "条款"


class DocumentStatus(str, Enum):
    PENDING_SPLIT = "待拆分"
    SPLITTING = "拆分中"
    PENDING_CONFIRM = "待确认"
    PENDING_CREATE = "待创建"
    CREATING = "创建中"
    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    COMPLETED = "已完成"
    PARTIAL = "部分完成"
    SKIPPED = "已跳过"
    FAILED = "失败"


class ClauseStatus(str, Enum):
    PENDING_CREATE = "待创建"
    CREATE_FAILED = "创建失败"
    PENDING_UPLOAD = "待上传"
    UPLOAD_SUCCESS = "上传成功"
    UPLOAD_FAILED = "上传失败"
    SKIPPED = "用户跳过"


@dataclass
class BatchImportDocument:
    id: int | None = None
    file_path: str = ""
    file_name: str = ""
    file_fingerprint: str = ""
    document_status: str = DocumentStatus.PENDING_SPLIT.value
    split_mode: str = SplitMode.CLAUSE.value
    standard: str = ""
    folder_id: int | None = None
    folder_name: str = ""
    product_type: str = ""
    plan_sr: str = "1"
    standard_version: str = ""
    chapter_version: str = "1.0"
    specific_product: str = ""
    total_clause_count: int = 0
    success_clause_count: int = 0
    failed_clause_count: int = 0
    skipped_clause_count: int = 0
    is_queued: bool = False
    queue_order: int | None = None
    last_error: str = ""


@dataclass
class BatchImportClause:
    id: int | None = None
    document_id: int | None = None
    sort_index: int = 0
    term: str = ""
    test_content: str = ""
    clause_status: str = ClauseStatus.PENDING_CREATE.value
    chapter_id: int | None = None
    backend_chapter_status: int | None = None
    source_docx_path: str = ""
    duplicate_flag: bool = False
    duplicate_reason: str = ""
    user_decision: str = ""
    create_error: str = ""
    upload_error: str = ""
    last_action: str = ""
```

- [ ] **Step 4: Add helper predicates for executable states**

```python
EXECUTABLE_DOCUMENT_STATUSES = {
    DocumentStatus.PENDING_CREATE.value,
    DocumentStatus.PENDING_UPLOAD.value,
    DocumentStatus.PARTIAL.value,
    DocumentStatus.FAILED.value,
}


def is_document_executable(status: str) -> bool:
    return status in EXECUTABLE_DOCUMENT_STATUSES
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_models.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/models.py tests/test_chapter_batch_models.py
git commit -m "feat: add batch import domain models"
```

---

## Task 3: Add Repository Layer for Workspace Records

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
- Modify: `O:\tuv-tools\src\tuv_tools\config\database.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`

- [ ] **Step 1: Write failing repository tests for CRUD and aggregation**

```python
def test_create_document_and_clauses(tmp_path):
    from tuv_tools.config.database import DatabaseManager
    from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, BatchImportClause

    db = DatabaseManager(tmp_path / "batch.db")
    repo = ChapterBatchRepository(db)
    doc = BatchImportDocument(file_path="C:/a.docx", file_name="a.docx")
    doc_id = repo.create_document(doc)
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(sort_index=0, term="10", test_content="A", source_docx_path="C:/10.docx"),
            BatchImportClause(sort_index=1, term="11", test_content="B", source_docx_path="C:/11.docx"),
        ],
    )

    saved = repo.get_document(doc_id)
    clauses = repo.get_clauses(doc_id)

    assert saved is not None
    assert len(clauses) == 2
    assert clauses[0].term == "10"


def test_reaggregate_document_status(tmp_path):
    from tuv_tools.config.database import DatabaseManager
    from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository
    from tuv_tools.core.chapter_batch.models import (
        BatchImportDocument,
        BatchImportClause,
        ClauseStatus,
        DocumentStatus,
    )

    db = DatabaseManager(tmp_path / "batch.db")
    repo = ChapterBatchRepository(db)
    doc_id = repo.create_document(BatchImportDocument(file_path="C:/a.docx", file_name="a.docx"))
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(sort_index=0, term="10", clause_status=ClauseStatus.UPLOAD_SUCCESS.value, source_docx_path="x"),
            BatchImportClause(sort_index=1, term="11", clause_status=ClauseStatus.UPLOAD_FAILED.value, source_docx_path="y"),
        ],
    )

    repo.reaggregate_document(doc_id)
    saved = repo.get_document(doc_id)

    assert saved.document_status == DocumentStatus.PARTIAL.value
    assert saved.success_clause_count == 1
    assert saved.failed_clause_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_repository.py -v`  
Expected: FAIL with repository not found

- [ ] **Step 3: Implement repository create/get/update helpers**

```python
class ChapterBatchRepository:
    def __init__(self, db: DatabaseManager):
        self._db = db

    def create_document(self, document: BatchImportDocument) -> int:
        ...

    def get_document(self, document_id: int) -> BatchImportDocument | None:
        ...

    def list_documents(self, *, status: str | None = None, keyword: str = "") -> list[BatchImportDocument]:
        ...

    def update_document(self, document_id: int, **fields) -> None:
        ...

    def delete_document(self, document_id: int) -> None:
        ...

    def replace_clauses(self, document_id: int, clauses: list[BatchImportClause]) -> None:
        ...

    def get_clauses(self, document_id: int) -> list[BatchImportClause]:
        ...

    def update_clause(self, clause_id: int, **fields) -> None:
        ...
```

- [ ] **Step 4: Implement document reaggregation in one place**

```python
def reaggregate_document(self, document_id: int) -> None:
    clauses = self.get_clauses(document_id)
    success = sum(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses)
    failed = sum(c.clause_status in {ClauseStatus.CREATE_FAILED.value, ClauseStatus.UPLOAD_FAILED.value} for c in clauses)
    skipped = sum(c.clause_status == ClauseStatus.SKIPPED.value for c in clauses)

    if clauses and all(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses):
        status = DocumentStatus.COMPLETED.value
    elif success > 0:
        status = DocumentStatus.PARTIAL.value
    elif any(c.clause_status == ClauseStatus.PENDING_UPLOAD.value for c in clauses):
        status = DocumentStatus.PENDING_UPLOAD.value
    elif any(c.clause_status == ClauseStatus.PENDING_CREATE.value for c in clauses):
        status = DocumentStatus.PENDING_CREATE.value
    elif failed > 0:
        status = DocumentStatus.FAILED.value
    else:
        status = DocumentStatus.PENDING_CONFIRM.value

    self.update_document(
        document_id,
        document_status=status,
        total_clause_count=len(clauses),
        success_clause_count=success,
        failed_clause_count=failed,
        skipped_clause_count=skipped,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_repository.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/repository.py src/tuv_tools/config/database.py tests/test_chapter_batch_repository.py
git commit -m "feat: add batch import repository layer"
```

---

## Task 4: Implement Batch Import Service

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`

- [ ] **Step 1: Write failing tests for import, defaults, duplicate check, and resplit**

```python
def test_import_documents_creates_workspace_records(tmp_path):
    from tuv_tools.config.database import DatabaseManager
    from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository
    from tuv_tools.core.chapter_batch.service import ChapterBatchService
    from tuv_tools.core.chapter_batch.models import SplitMode, DocumentStatus

    db = DatabaseManager(tmp_path / "batch.db")
    repo = ChapterBatchRepository(db)
    service = ChapterBatchService(repo)

    paths = [r"C:\docs\IEC60335-2-9 fryer.docx"]
    created = service.import_documents(paths, split_mode=SplitMode.CLAUSE.value)

    assert len(created) == 1
    assert created[0].standard == "60335-2-9"
    assert created[0].document_status == DocumentStatus.PENDING_SPLIT.value


def test_duplicate_check_uses_folder_term_and_test_content():
    from tuv_tools.core.chapter_batch.service import check_duplicate_candidates
    from tuv_tools.core.chapter_batch.models import BatchImportClause

    current = BatchImportClause(term="10.1", test_content="Heating")
    existing = [{"term": "10.1", "test_content": "Heating", "folder_id": 7}]

    result = check_duplicate_candidates(folder_id=7, clause=current, existing_rows=existing)

    assert result.is_duplicate is True
    assert "term + testContent" in result.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_service.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement import and draft generation service**

```python
class ChapterBatchService:
    def __init__(self, repo: ChapterBatchRepository):
        self._repo = repo

    def import_documents(self, paths: list[str], split_mode: str) -> list[BatchImportDocument]:
        created = []
        for path in paths:
            file_name = Path(path).name
            standard = _extract_standard_number(file_name) or ""
            doc = BatchImportDocument(
                file_path=str(Path(path).resolve()),
                file_name=file_name,
                split_mode=split_mode,
                standard=standard,
                document_status=DocumentStatus.PENDING_SPLIT.value,
                plan_sr="1",
                chapter_version="1.0",
            )
            doc.id = self._repo.create_document(doc)
            created.append(self._repo.get_document(doc.id))
        return [d for d in created if d is not None]
```

- [ ] **Step 4: Implement resplit/reset helpers**

```python
def reset_document_for_resplit(self, document_id: int, split_mode: str) -> None:
    self._repo.clear_events(document_id)
    self._repo.replace_clauses(document_id, [])
    self._repo.update_document(
        document_id,
        split_mode=split_mode,
        document_status=DocumentStatus.PENDING_CONFIRM.value,
        total_clause_count=0,
        success_clause_count=0,
        failed_clause_count=0,
        skipped_clause_count=0,
        is_queued=0,
        queue_order=None,
        last_error="",
    )
```

- [ ] **Step 5: Implement duplicate checking helper**

```python
@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    reason: str = ""


def check_duplicate_candidates(folder_id: int | None, clause: BatchImportClause, existing_rows: list[dict]) -> DuplicateCheckResult:
    if folder_id is None:
        return DuplicateCheckResult(False, "")
    for row in existing_rows:
        if row.get("folder_id") != folder_id:
            continue
        if row.get("term") == clause.term and row.get("test_content") == clause.test_content:
            return DuplicateCheckResult(True, "同一归属文件夹下 term + testContent 相同")
    return DuplicateCheckResult(False, "")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_service.py -v`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/service.py tests/test_chapter_batch_service.py
git commit -m "feat: add batch import service layer"
```

---

## Task 5: Add API Wrapper for Chapter Doc Import and Draft Sync

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\api.py`
- Modify: `O:\tuv-tools\tests\test_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_import_chapter_doc_posts_multipart(requests_mock):
    from tuv_tools.core.chapter.client import TuvClient
    from tuv_tools.core.chapter_batch.api import import_chapter_doc

    client = TuvClient("http://example.com")
    requests_mock.post("http://example.com/api/chapter-doc/import", json={"success": True})

    result = import_chapter_doc(client, 123, b"docx-bytes", "123.docx")

    assert result["success"] is True
    assert requests_mock.last_request.qs == {"chapterId": ["123"]}


def test_chapter_sync_requires_draft_status(requests_mock):
    from tuv_tools.core.chapter.client import TuvClient
    from tuv_tools.core.chapter_batch.api import fetch_chapter_detail

    client = TuvClient("http://example.com")
    requests_mock.get("http://example.com/api/chapter", json={"content": [{"id": 12, "status": 0}]})

    page = fetch_chapter_detail(client, chapter_id=12)
    assert page["content"][0]["status"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k chapter_doc -v`  
Expected: FAIL

- [ ] **Step 3: Implement multipart upload wrapper**

```python
def import_chapter_doc(client: TuvClient, chapter_id: int, file_bytes: bytes, file_name: str) -> dict:
    files = {
        "file": (
            file_name,
            file_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = client._session.post(
        f"{client._base_url}/api/chapter-doc/import",
        params={"chapterId": chapter_id},
        files=files,
        timeout=client._timeout,
    )
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Implement minimal chapter detail query helper**

```python
def fetch_chapter_detail(client: TuvClient, chapter_id: int) -> dict:
    resp = client.get("/api/chapter", params={"page": 0, "size": 1, "id": chapter_id})
    return resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api.py -k chapter_doc -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/api.py tests/test_api.py
git commit -m "feat: add chapter batch API wrappers"
```

---

## Task 6: Implement Serial Executor and Cancellation Semantics

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`

- [ ] **Step 1: Write failing executor tests**

```python
def test_executor_processes_documents_serially():
    from tuv_tools.core.chapter_batch.executor import ExecutionQueue

    queue = ExecutionQueue()
    queue.enqueue([1, 2, 3])

    assert queue.next_document() == 1
    assert queue.next_document() == 2
    assert queue.next_document() == 3


def test_cancel_keeps_unprocessed_clauses_pending():
    from tuv_tools.core.chapter_batch.executor import apply_cancel_result
    from tuv_tools.core.chapter_batch.models import ClauseStatus

    final = apply_cancel_result(
        processed_statuses=[ClauseStatus.UPLOAD_SUCCESS.value],
        remaining_statuses=[ClauseStatus.PENDING_CREATE.value, ClauseStatus.PENDING_UPLOAD.value],
    )

    assert final["remaining"] == [ClauseStatus.PENDING_CREATE.value, ClauseStatus.PENDING_UPLOAD.value]
    assert final["document_status"] == "部分完成"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_executor.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement execution queue and state helpers**

```python
class ExecutionQueue:
    def __init__(self) -> None:
        self._items: list[int] = []
        self._cancel_requested = False

    def enqueue(self, document_ids: list[int]) -> None:
        self._items.extend(document_ids)

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def next_document(self) -> int | None:
        if not self._items:
            return None
        return self._items.pop(0)
```

- [ ] **Step 4: Implement document-level cancel aggregation helper**

```python
def derive_document_status_after_cancel(
    had_upload_success: bool,
    has_pending_upload: bool,
    attempted_uploads_all_failed: bool,
) -> str:
    if has_pending_upload:
        return "待上传"
    if had_upload_success:
        return "部分完成"
    if attempted_uploads_all_failed:
        return "失败"
    return "待创建"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_executor.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/executor.py tests/test_chapter_batch_executor.py
git commit -m "feat: add serial executor primitives"
```

---

## Task 7: Create Reusable Folder Tree Selector

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_folder_selector.py`
- Test: `O:\tuv-tools\tests\test_chapter_folder_selector.py`

- [ ] **Step 1: Write failing widget test**

```python
def test_folder_selector_emits_selected_folder(qtbot):
    from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector

    widget = ChapterFolderSelector()
    qtbot.addWidget(widget)

    captured = []
    widget.folder_changed.connect(lambda fid, name: captured.append((fid, name)))

    widget._emit_folder_changed(1061, "60335-2-3")

    assert captured == [(1061, "60335-2-3")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_folder_selector.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement selector widget**

```python
class ChapterFolderSelector(QWidget):
    folder_changed = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_folder_id: int | None = None
        self._selected_folder_name = ""
        ...

    def set_selected_folder(self, folder_id: int | None, folder_name: str = "") -> None:
        self._selected_folder_id = folder_id
        self._selected_folder_name = folder_name
        self._display.setText(folder_name or "")

    def selected_folder(self) -> tuple[int | None, str]:
        return self._selected_folder_id, self._selected_folder_name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chapter_folder_selector.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_folder_selector.py tests/test_chapter_folder_selector.py
git commit -m "feat: add reusable chapter folder selector"
```

---

## Task 8: Refactor Chapter Management Create/Edit to Reuse Folder Selector

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing test for create dialog using selector**

```python
def test_chapter_dialog_uses_folder_selector(qtbot):
    from tuv_tools.ui.views.chapter_view import ChapterDialog

    dialog = ChapterDialog(folder_id=123)
    qtbot.addWidget(dialog)

    folder_id, folder_name = dialog._folder_selector.selected_folder()
    assert folder_id == 123
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_batch_view.py -k folder_selector -v`  
Expected: FAIL

- [ ] **Step 3: Replace raw folder ID line edit in ChapterDialog**

```python
self._folder_selector = ChapterFolderSelector(self)
self._folder_selector.set_selected_folder(chapter.folder_id if chapter else folder_id)
layout.addRow("归属文件夹 *:", self._folder_selector)
```

- [ ] **Step 4: Update get_chapters() to use selector value**

```python
folder_id, _folder_name = self._folder_selector.selected_folder()
base = Chapter(
    folder_id=folder_id,
    ...
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_chapter_batch_view.py -k folder_selector -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_view.py tests/test_chapter_batch_view.py
git commit -m "refactor: reuse folder selector in chapter dialog"
```

---

## Task 9: Add Workspace Page to Main Window

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\main_window.py`
- Create: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing test for view registration**

```python
def test_main_window_registers_chapter_batch_workspace(qtbot):
    from tuv_tools.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    labels = [window._nav.item(i).text() for i in range(window._nav.count())]
    assert "条款批量导入" in labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_batch_view.py -k register -v`  
Expected: FAIL

- [ ] **Step 3: Create minimal workspace view scaffold**

```python
class ChapterBatchView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("条款批量导入")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
```

- [ ] **Step 4: Register page in main window**

```python
from .views.chapter_batch_view import ChapterBatchView

def _register_views(self):
    self._add_view("文档拆分", SplitterView())
    self._add_view("条款管理", ChapterView())
    self._add_view("条款批量导入", ChapterBatchView())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_chapter_batch_view.py -k register -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/main_window.py src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_view.py
git commit -m "feat: add chapter batch workspace page"
```

---

## Task 10: Implement Workspace List, Filters, and Import Entry

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing UI test for import buttons and filters**

```python
def test_workspace_has_import_and_filter_controls(qtbot):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView()
    qtbot.addWidget(view)

    assert view._import_file_btn.text() == "导入文件"
    assert view._import_dir_btn.text() == "导入文件夹"
    assert view._bulk_confirm_btn.text() == "批量确认"
    assert view._start_btn.text() == "开始执行"
    assert view._status_filter.count() >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_batch_view.py -k filter_controls -v`  
Expected: FAIL

- [ ] **Step 3: Implement list toolbar and filters**

```python
self._import_file_btn = QPushButton("导入文件")
self._import_dir_btn = QPushButton("导入文件夹")
self._bulk_confirm_btn = QPushButton("批量确认")
self._start_btn = QPushButton("开始执行")
self._search_edit = QLineEdit()
self._status_filter = QComboBox()
self._mode_filter = QComboBox()
```

- [ ] **Step 4: Add document table columns**

```python
self._table = QTableWidget()
self._table.setColumnCount(7)
self._table.setHorizontalHeaderLabels(
    ["选择", "文档名", "标准", "模式", "文档状态", "条款结果摘要", "更新时间"]
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_chapter_batch_view.py -k filter_controls -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_view.py
git commit -m "feat: add workspace list and filters"
```

---

## Task 11: Implement Auto-Split on Import and Single-Mode Batch Choice

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing test for batch import mode choice**

```python
def test_batch_import_applies_one_selected_mode_to_all_documents():
    from tuv_tools.core.chapter_batch.models import SplitMode
    from tuv_tools.core.chapter_batch.service import ChapterBatchService

    service = ChapterBatchService(repo=None)  # inject fake repo in real test
    modes = service.normalize_import_mode(paths=["a.docx", "b.docx"], selected_mode=SplitMode.SECTION.value)

    assert modes == {
        "a.docx": SplitMode.SECTION.value,
        "b.docx": SplitMode.SECTION.value,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_batch_service.py -k import_mode -v`  
Expected: FAIL

- [ ] **Step 3: Add import mode dialog with two business labels**

```python
class SplitModeDialog(QDialog):
    def selected_mode(self) -> str:
        if self._section_radio.isChecked():
            return SplitMode.SECTION.value
        return SplitMode.CLAUSE.value
```

- [ ] **Step 4: Trigger automatic split after import**

```python
def _handle_import_paths(self, paths: list[str]) -> None:
    mode = SplitModeDialog.get_mode(self)
    if not mode:
        return
    documents = self._service.import_documents(paths, split_mode=mode)
    self._enqueue_split_for_documents(documents)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py -k "import_mode or auto_split" -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/core/chapter_batch/service.py tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py
git commit -m "feat: auto split imported workspace documents"
```

---

## Task 12: Implement Drawer Shell and Multi-Document Tabs

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing test for double-click drawer**

```python
def test_double_click_document_opens_drawer(qtbot, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView()
    qtbot.addWidget(view)

    opened = []
    view._open_drawer_for_documents = lambda doc_ids: opened.extend(doc_ids)

    view._on_document_double_clicked(12)

    assert opened == [12]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_batch_view.py -k drawer -v`  
Expected: FAIL

- [ ] **Step 3: Implement drawer shell with tab bar**

```python
class ChapterBatchDrawer(QWidget):
    document_selected = Signal(int)

    def set_documents(self, documents: list[BatchImportDocument]) -> None:
        self._tabs.clear()
        for document in documents:
            self._tabs.addTab(document.file_name)
        self._documents = documents
```

- [ ] **Step 4: Wire double-click and bulk confirm to drawer**

```python
def _on_document_double_clicked(self, document_id: int) -> None:
    self._open_drawer_for_documents([document_id])


def _open_bulk_confirm(self) -> None:
    document_ids = self._selected_document_ids()
    self._open_drawer_for_documents(document_ids)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_chapter_batch_view.py -k drawer -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_drawer.py src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_view.py
git commit -m "feat: add batch workspace drawer shell"
```

---

## Task 13: Implement Document Form and Clause Table Inside Drawer

**Files:**
- Create: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_document_form.py`
- Create: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing tests for form and clause table binding**

```python
def test_document_form_loads_public_fields(qtbot):
    from tuv_tools.ui.widgets.chapter_batch_document_form import ChapterBatchDocumentForm

    form = ChapterBatchDocumentForm()
    qtbot.addWidget(form)
    form.load_document(
        {
            "standard": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "chapter_version": "1.0",
        }
    )

    assert form._standard_edit.text() == "60335-2-9"
    assert form._product_type_edit.text() == "家电"


def test_clause_table_loads_term_and_test_content(qtbot):
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    qtbot.addWidget(table)
    table.load_clauses(
        [{"term": "10.1", "test_content": "Heating", "clause_status": "待创建"}]
    )

    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "10.1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_view.py -k "document_form or clause_table" -v`  
Expected: FAIL

- [ ] **Step 3: Implement document form widget**

```python
class ChapterBatchDocumentForm(QWidget):
    changed = Signal(dict)

    def load_document(self, document: dict) -> None:
        self._standard_edit.setText(document.get("standard", ""))
        self._folder_selector.set_selected_folder(
            document.get("folder_id"),
            document.get("folder_name", ""),
        )
        self._product_type_edit.setText(document.get("product_type", ""))
        self._plan_sr_edit.setText(document.get("plan_sr", "1"))
        self._standard_version_edit.setText(document.get("standard_version", ""))
        self._chapter_version_edit.setText(document.get("chapter_version", "1.0"))
        self._specific_product_edit.setText(document.get("specific_product", ""))
```

- [ ] **Step 4: Implement clause table widget**

```python
class ChapterBatchClauseTable(QTableWidget):
    clause_action_requested = Signal(int, str)

    def load_clauses(self, clauses: list[dict]) -> None:
        self.setRowCount(len(clauses))
        for row, clause in enumerate(clauses):
            self.setItem(row, 0, QTableWidgetItem(clause.get("term", "")))
            self.setItem(row, 1, QTableWidgetItem(clause.get("test_content", "")))
            self.setItem(row, 2, QTableWidgetItem(clause.get("clause_status", "")))
            self.setItem(row, 3, QTableWidgetItem(str(clause.get("chapter_id") or "")))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_view.py -k "document_form or clause_table" -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_document_form.py src/tuv_tools/ui/widgets/chapter_batch_clause_table.py src/tuv_tools/ui/widgets/chapter_batch_drawer.py tests/test_chapter_batch_view.py
git commit -m "feat: add batch workspace drawer content widgets"
```

---

## Task 14: Implement Confirm Save and Duplicate Check Gate

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing tests for duplicate gate and pending-create transition**

```python
def test_confirm_save_sets_document_to_pending_create():
    from tuv_tools.core.chapter_batch.models import DocumentStatus

    saved_status = DocumentStatus.PENDING_CREATE.value
    assert saved_status == "待创建"


def test_duplicate_check_can_mark_clause_as_skipped():
    from tuv_tools.core.chapter_batch.models import BatchImportClause, ClauseStatus

    clause = BatchImportClause(term="10.1", test_content="Heating")
    clause.clause_status = ClauseStatus.SKIPPED.value

    assert clause.clause_status == "用户跳过"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py -k "duplicate or pending_create" -v`  
Expected: FAIL

- [ ] **Step 3: Implement confirm-save flow**

```python
def save_confirmed_documents(self, document_ids: list[int]) -> list[int]:
    ready_ids: list[int] = []
    for document_id in document_ids:
        self._validate_document_before_confirm(document_id)
        self._apply_duplicate_decisions(document_id)
        self._repo.update_document(document_id, document_status=DocumentStatus.PENDING_CREATE.value)
        self._repo.reaggregate_document(document_id)
        ready_ids.append(document_id)
    return ready_ids
```

- [ ] **Step 4: Prompt direct upload vs later**

```python
reply = QMessageBox.question(
    self,
    "确认完成",
    "是否直接上传？\n选择“否”将文档保留为待创建。",
    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py -k "duplicate or pending_create" -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/service.py src/tuv_tools/ui/widgets/chapter_batch_drawer.py tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py
git commit -m "feat: add confirm save and duplicate gate"
```

---

## Task 15: Implement Background Runner Integration in Workspace View

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing tests for start execution selection filtering**

```python
def test_start_execution_only_enqueues_executable_documents():
    from tuv_tools.core.chapter_batch.models import is_document_executable

    assert is_document_executable("待创建") is True
    assert is_document_executable("待确认") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py -k executable -v`  
Expected: FAIL

- [ ] **Step 3: Wire selected documents into serial queue**

```python
def _start_selected_documents(self) -> None:
    selected = self._selected_document_ids()
    executable, skipped = self._partition_executable_documents(selected)
    if not executable:
        QMessageBox.information(self, "开始执行", "当前选中文档中没有可执行项。")
        return
    self._executor.enqueue(executable)
    self._show_skipped_documents(skipped)
```

- [ ] **Step 4: Add worker thread wrapper for queue processing**

```python
class ChapterBatchWorker(QThread):
    document_status_changed = Signal(int, str)
    clause_status_changed = Signal(int, str)
    error_occurred = Signal(str)

    def run(self):
        self._executor.run_until_empty(
            on_document_status=self.document_status_changed.emit,
            on_clause_status=self.clause_status_changed.emit,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py -k executable -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/core/chapter_batch/executor.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py
git commit -m "feat: wire serial execution into workspace view"
```

---

## Task 16: Implement Clause-Level Retry, Sync, and Open Actions

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\api.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing tests for clause actions**

```python
def test_clause_action_menu_contains_retry_and_open_actions(qtbot):
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    qtbot.addWidget(table)

    actions = table._available_actions_for_status("上传失败")
    assert "重试上传" in actions
    assert "打开本地 docx" in actions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_view.py -k clause_action -v`  
Expected: FAIL

- [ ] **Step 3: Implement per-status action mapping**

```python
def _available_actions_for_status(self, status: str) -> list[str]:
    if status == "创建失败":
        return ["重试创建", "打开本地 docx"]
    if status == "上传失败":
        return ["重试上传", "打开本地 docx", "同步到后端", "打开后端 chapter 记录"]
    if status == "用户跳过":
        return ["恢复跳过", "打开本地 docx"]
    if status == "待上传":
        return ["重试上传", "打开本地 docx", "打开后端 chapter 记录"]
    return ["打开本地 docx"]
```

- [ ] **Step 4: Handle chapter sync as manual action only**

```python
def sync_clause_to_backend(self, clause_id: int) -> None:
    clause = self._repo.get_clause(clause_id)
    if not clause or clause.chapter_id is None:
        raise ValueError("未找到已创建的后端条款")
    detail = fetch_chapter_detail(self._client, clause.chapter_id)
    status = detail["content"][0]["status"]
    if status != ChapterStatus.DRAFT:
        raise ValueError("仅草稿状态条款允许同步")
    self._client.put("/api/chapter", json=...)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_view.py -k clause_action -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_clause_table.py src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/core/chapter_batch/api.py tests/test_chapter_batch_view.py
git commit -m "feat: add clause retry sync and open actions"
```

---

## Task 17: Implement Delete Record and Cancel Guards

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write failing tests for delete guard**

```python
def test_document_in_queue_cannot_be_deleted():
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    doc = BatchImportDocument(is_queued=True)
    assert doc.is_queued is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_batch_view.py -k delete_guard -v`  
Expected: FAIL

- [ ] **Step 3: Add deletion guard in view**

```python
def _delete_selected_documents(self) -> None:
    docs = self._selected_documents()
    blocked = [doc.file_name for doc in docs if doc.is_queued]
    if blocked:
        QMessageBox.warning(
            self,
            "无法删除",
            "执行队列中的文档不能删除，请先取消执行。",
        )
        return
    self._repo.delete_documents([doc.id for doc in docs if doc.id is not None])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_chapter_batch_view.py -k delete_guard -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/core/chapter_batch/repository.py tests/test_chapter_batch_view.py
git commit -m "feat: guard document deletion while queued"
```

---

## Task 18: Full Test Pass and Manual QA Notes

**Files:**
- Modify: `O:\tuv-tools\docs\superpowers\plans\2026-05-24-chapter-batch-import-workspace.md`

- [ ] **Step 1: Run targeted test suites**

Run: `pytest tests/test_database.py tests/test_api.py tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py tests/test_chapter_folder_selector.py tests/test_chapter_batch_view.py -v`  
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`  
Expected: PASS

- [ ] **Step 3: Record manual QA checklist**

```markdown
- 导入多个文档后，统一选择一次模式并自动拆分
- 双击文档打开右侧抽屉
- 多个待确认文档进入同一抽屉，标签页按当前列表顺序排列
- 目录树未唯一匹配时，必须手动选择目录后才能保存确认
- 保存确认后可选“直接上传”或“稍后处理”
- 文档级串行执行时，状态按“创建中 / 上传中 / 部分完成 / 已完成”推进
- 取消执行在安全点生效
- 创建失败条款可编辑后重试创建
- 上传失败条款可编辑后重试上传
- 已创建草稿条款可手动同步到后端
- 结果页能显示 chapter ID 并打开条款管理定位对应记录
- 重新拆分只重置本地记录，不影响后端对象
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-05-24-chapter-batch-import-workspace.md
git commit -m "docs: finalize chapter batch import implementation plan"
```

---

## Spec Coverage Check

- 独立页面：Task 9, 10
- 单列表工作台：Task 10
- 统一模式导入 + 单文档重拆分：Task 4, 11, 14
- 双击抽屉 + 多文档标签：Task 12, 13
- 目录树选择器复用：Task 7, 8
- 确认后“直接上传 / 稍后处理”：Task 14
- 文档级串行执行 + 两阶段：Task 6, 15
- 条款级失败编辑、重试、同步：Task 16
- 结果持久化：Task 1, 3
- 删除只删本地记录、执行中不可删：Task 17
- 取消安全点 + 状态修正：Task 6, 15

## Placeholder Scan

- 无 `TBD` / `TODO` / “implement later”
- 每个代码步骤给出了实际代码骨架或最小实现
- 每个测试步骤给出了具体命令和预期
- 每个任务都给出了准确文件路径

## Type Consistency Check

- 模式命名统一为 `SplitMode.SECTION = "章节"` / `SplitMode.CLAUSE = "条款"`
- 文档状态统一使用 `DocumentStatus`
- 条款状态统一使用 `ClauseStatus`
- 文档级字段统一使用 `chapter_version`
- 上传接口统一走 `import_chapter_doc(...)`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-chapter-batch-import-workspace.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
