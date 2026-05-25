# Chapter Batch Import Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 Chapter 批量导入工作台在确认分流、草稿态编辑约束和取消后续跑语义上的实现缺口，使当前模块与已确认业务规则一致。

**Architecture:** 继续沿用现有 `chapter_batch` 模块结构，不新增页面，不改后端接口。变更集中在 `models.py` 的规则判定、`chapter_batch_view.py` 的保存与执行编排、`chapter_batch_drawer.py` / `chapter_batch_document_form.py` / `chapter_batch_clause_table.py` 的只读控制，以及 `executor.py` / `repository.py` 的取消后状态聚合。

**Tech Stack:** Python 3.10+, PySide6, SQLite (`sqlite3`), requests, pytest

---

## File Structure

### Modified Files

- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
  - 维护文档运行状态、条款是否允许编辑、只读原因等纯规则函数
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
  - 负责文档级聚合状态回写，补充“取消后强制状态”这一落点
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
  - 负责执行取消后的显式状态收口，不再只依赖隐式重聚合
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
  - 抽屉底部按钮收口为 `保存确认`，暴露整页只读控制
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_document_form.py`
  - 提供文档级表单只读切换
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
  - 负责条款级单元格编辑性和只读原因展示
- `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
  - 负责保存确认后的二次分流弹窗、执行队列触发、抽屉只读状态同步
- `O:\tuv-tools\tests\test_chapter_batch_models.py`
  - 覆盖编辑性规则和运行状态判定
- `O:\tuv-tools\tests\test_chapter_batch_view.py`
  - 覆盖抽屉按钮收口、保存后分流、条款只读和执行中锁定行为
- `O:\tuv-tools\tests\test_chapter_batch_executor.py`
  - 覆盖取消执行后的文档状态落点
- `O:\tuv-tools\tests\test_chapter_batch_repository.py`
  - 覆盖 `forced_status` 聚合回写和计数一致性

### Responsibilities

- 规则判断全部放在 `models.py`，避免 UI 里散落条件分支。
- 抽屉组件只负责展示和发信号，不承担“直接上传 / 稍后处理”的分流判断。
- View 统一编排“保存 -> 重复处理 -> 二次分流 -> 入队/不入队”。
- 执行器只负责运行时状态推进；Repository 负责最终聚合回写。

---

### Task 1: Extract Editability and Running-State Rules

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`

- [ ] **Step 1: Write the failing rule tests**

```python
from tuv_tools.core.chapter.models import ChapterStatus
from tuv_tools.core.chapter_batch.models import (
    ClauseStatus,
    DocumentStatus,
    get_clause_edit_state,
    is_document_running,
)


def test_running_document_statuses_are_detected():
    assert is_document_running(DocumentStatus.CREATING.value) is True
    assert is_document_running(DocumentStatus.UPLOADING.value) is True
    assert is_document_running(DocumentStatus.PENDING_CREATE.value) is False


def test_clause_without_chapter_id_is_editable():
    editable, reason = get_clause_edit_state(
        clause_status=ClauseStatus.PENDING_CREATE.value,
        chapter_id=None,
        backend_chapter_status=None,
    )

    assert editable is True
    assert reason == ""


def test_clause_with_draft_backend_status_is_editable():
    editable, reason = get_clause_edit_state(
        clause_status=ClauseStatus.PENDING_UPLOAD.value,
        chapter_id=101,
        backend_chapter_status=int(ChapterStatus.DRAFT),
    )

    assert editable is True
    assert reason == ""


def test_clause_with_unknown_backend_status_is_readonly():
    editable, reason = get_clause_edit_state(
        clause_status=ClauseStatus.UPLOAD_FAILED.value,
        chapter_id=101,
        backend_chapter_status=None,
    )

    assert editable is False
    assert reason == "后端状态未知，禁止编辑"


def test_clause_with_non_draft_backend_status_is_readonly():
    editable, reason = get_clause_edit_state(
        clause_status=ClauseStatus.PENDING_UPLOAD.value,
        chapter_id=101,
        backend_chapter_status=2,
    )

    assert editable is False
    assert reason == "后端非草稿，禁止编辑"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_chapter_batch_models.py -k "running or editable or readonly" -v
```

Expected:

```text
FAIL with ImportError or AttributeError for is_document_running/get_clause_edit_state
```

- [ ] **Step 3: Implement the minimal rule helpers**

```python
from tuv_tools.core.chapter.models import ChapterStatus


RUNNING_DOCUMENT_STATUSES = {
    DocumentStatus.CREATING.value,
    DocumentStatus.UPLOADING.value,
    DocumentStatus.SPLITTING.value,
}


def is_document_running(status: str) -> bool:
    return status in RUNNING_DOCUMENT_STATUSES


def get_clause_edit_state(
    *,
    clause_status: str,
    chapter_id: int | None,
    backend_chapter_status: int | None,
) -> tuple[bool, str]:
    if chapter_id is None:
        return True, ""
    if backend_chapter_status == int(ChapterStatus.DRAFT):
        return True, ""
    if backend_chapter_status is None:
        return False, "后端状态未知，禁止编辑"
    return False, "后端非草稿，禁止编辑"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_chapter_batch_models.py -k "running or editable or readonly" -v
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit the rule helpers**

```bash
git add src/tuv_tools/core/chapter_batch/models.py tests/test_chapter_batch_models.py
git commit -m "refactor(chapter-batch): 提取编辑性判定规则" ^
  -m "把文档运行状态和条款草稿态编辑性收口为纯规则函数，避免后续在 UI 里重复散落条件分支。" ^
  -m "Constraint: 仅根据本地 chapter_id 和 backend_chapter_status 判定，不额外新增后端查询" ^
  -m "Rejected: 在表格组件内部硬编码编辑规则 | 会让 View 和 Widget 同时维护状态条件" ^
  -m "Confidence: high" ^
  -m "Scope-risk: narrow" ^
  -m "Directive: 后端状态未知必须保持只读，不要回退为可编辑默认值" ^
  -m "Tested: pytest tests/test_chapter_batch_models.py -k \"running or editable or readonly\" -v" ^
  -m "Not-tested: full UI integration" ^
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 2: Collapse Drawer Actions to a Single Save Button

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write the failing drawer button test**

```python
from PySide6.QtWidgets import QPushButton

from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer


def test_drawer_only_exposes_save_confirm_button(qapp):
    drawer = ChapterBatchDrawer()
    button_texts = [button.text() for button in drawer.findChildren(QPushButton)]

    assert "保存确认" in button_texts
    assert "直接上传" not in button_texts
    assert "稍后处理" not in button_texts
```

- [ ] **Step 2: Run the focused UI test to verify it fails**

Run:

```bash
pytest tests/test_chapter_batch_view.py::test_drawer_only_exposes_save_confirm_button -v
```

Expected:

```text
FAIL because "直接上传" and "稍后处理" are still present
```

- [ ] **Step 3: Remove the pseudo-branch buttons from the drawer**

```python
button_row = QHBoxLayout()
self._save_btn = QPushButton("保存确认")
self._save_btn.clicked.connect(self._emit_save_confirm)
button_row.addWidget(self._save_btn)
button_row.addStretch()
layout.addLayout(button_row)
```

- [ ] **Step 4: Run the focused UI test to verify it passes**

Run:

```bash
pytest tests/test_chapter_batch_view.py::test_drawer_only_exposes_save_confirm_button -v
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit the drawer simplification**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_drawer.py tests/test_chapter_batch_view.py
git commit -m "refactor(chapter-batch): 收口抽屉确认按钮" ^
  -m "移除抽屉内并列的直接上传和稍后处理按钮，只保留保存确认，把执行分流交给后续弹窗处理。" ^
  -m "Constraint: 必须回到既定的保存后分流流程，不在抽屉底部并列承担两级决策" ^
  -m "Rejected: 保留三个按钮并修正点击分支 | 会继续让抽屉承担确认和执行两个层级的职责" ^
  -m "Confidence: high" ^
  -m "Scope-risk: narrow" ^
  -m "Directive: Drawer 只发出保存确认信号，不要在组件内判断上传时机" ^
  -m "Tested: pytest tests/test_chapter_batch_view.py::test_drawer_only_exposes_save_confirm_button -v" ^
  -m "Not-tested: save flow integration" ^
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 3: Implement Save-Then-Branch Post-Confirm Flow

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write the failing save-branch tests**

```python
from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView


def test_save_confirm_direct_upload_starts_ready_documents(qapp, monkeypatch):
    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/direct.docx",
            file_name="direct.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    started = []
    monkeypatch.setattr(view, "_ask_post_confirm_action", lambda: "upload")
    monkeypatch.setattr(view, "_start_documents", lambda document_ids: started.append(document_ids))

    view._on_save_confirm_requested([doc_id])

    assert started == [[doc_id]]
    assert repo.get_document(doc_id).is_queued is True


def test_save_confirm_cancel_keeps_saved_data_without_queue(qapp, monkeypatch):
    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/cancel.docx",
            file_name="cancel.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    monkeypatch.setattr(view, "_ask_post_confirm_action", lambda: "cancel")

    view._on_save_confirm_requested([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved.is_queued is False
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_chapter_batch_view.py -k "direct_upload_starts_ready_documents or cancel_keeps_saved_data_without_queue" -v
```

Expected:

```text
FAIL because ChapterBatchView has no _ask_post_confirm_action helper and current flow only handles Yes/No
```

- [ ] **Step 3: Add an explicit post-confirm branch helper and wire it into save flow**

```python
def _ask_post_confirm_action(self) -> str:
    reply = QMessageBox.question(
        self,
        "确认完成",
        "请选择下一步操作：\n是：直接上传\n否：稍后处理\n取消：只保留本地保存结果",
        QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No
        | QMessageBox.StandardButton.Cancel,
    )
    if reply == QMessageBox.StandardButton.Yes:
        return "upload"
    if reply == QMessageBox.StandardButton.No:
        return "later"
    return "cancel"


def _on_save_confirm_requested(self, document_ids: list[int]) -> None:
    ...
    ready_ids = self._service.save_confirmed_documents(document_updates)
    self._load_documents()
    action = self._ask_post_confirm_action()
    if action == "upload":
        for document_id in ready_ids:
            self._repo.update_document(document_id, is_queued=1)
        self._load_documents()
        self._start_documents(ready_ids)
        return
    for document_id in ready_ids:
        self._repo.update_document(document_id, is_queued=0)
    self._load_documents()
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
pytest tests/test_chapter_batch_view.py -k "direct_upload_starts_ready_documents or cancel_keeps_saved_data_without_queue" -v
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit the post-confirm branching flow**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_view.py
git commit -m "feat(chapter-batch): 补齐确认后的分流弹窗" ^
  -m "把保存确认后的下一步决策统一收口为二次弹窗，支持直接上传、稍后处理和取消，同时保留已保存的本地表单修改。" ^
  -m "Constraint: 取消只能取消入队，不得回滚已经保存的本地确认结果" ^
  -m "Rejected: 继续用抽屉底部多按钮表达执行分流 | 与既定交互不一致，且职责边界混乱" ^
  -m "Confidence: high" ^
  -m "Scope-risk: moderate" ^
  -m "Directive: 后续任何立即执行入口都必须经过保存后的统一分流 helper，不要复制弹窗逻辑" ^
  -m "Tested: pytest tests/test_chapter_batch_view.py -k \"direct_upload_starts_ready_documents or cancel_keeps_saved_data_without_queue\" -v" ^
  -m "Not-tested: full regression suite" ^
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 4: Enforce Draft-Only Editing and Running-Document Locking

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_document_form.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Write the failing readonly tests**

```python
from tuv_tools.core.chapter.models import ChapterStatus
from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView


def test_clause_with_unknown_backend_status_is_readonly_in_table(qapp):
    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/a.docx", file_name="a.docx", document_status=DocumentStatus.PENDING_UPLOAD.value)
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=100,
                backend_chapter_status=None,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    view._load_drawer_clauses(doc_id)

    term_item = view._drawer._clause_table.item(0, 0)
    reason_item = view._drawer._clause_table.item(0, 5)
    assert not (term_item.flags() & term_item.flags().ItemIsEditable)
    assert reason_item.text() == "后端状态未知，禁止编辑"


def test_running_document_disables_form_and_save_button(qapp):
    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.UPLOADING.value,
            standard="60335-2-9",
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None

    view._open_drawer_for_documents([doc])

    assert view._drawer._save_btn.isEnabled() is False
    assert view._drawer._document_form._standard_edit.isReadOnly() is True
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_chapter_batch_view.py -k "readonly_in_table or disables_form_and_save_button" -v
```

Expected:

```text
FAIL because the table cells are still editable and the drawer has no running-state lock
```

- [ ] **Step 3: Apply readonly plumbing through the form, table, drawer, and view**

```python
# chapter_batch_document_form.py
def set_readonly(self, locked: bool) -> None:
    self._standard_edit.setReadOnly(locked)
    self._product_type_edit.setReadOnly(locked)
    self._plan_sr_edit.setReadOnly(locked)
    self._standard_version_edit.setReadOnly(locked)
    self._chapter_version_edit.setReadOnly(locked)
    self._specific_product_edit.setReadOnly(locked)
    self._folder_selector.setEnabled(not locked)


# chapter_batch_clause_table.py
def load_clauses(self, clauses: list[dict]) -> None:
    ...
    editable = clause.get("editable", True)
    readonly_reason = clause.get("readonly_reason", "")
    if not editable:
        term_item.setFlags(term_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        content_widget = self.item(row, 1)
        if content_widget is not None:
            content_widget.setFlags(content_widget.flags() & ~Qt.ItemFlag.ItemIsEditable)
    error_text = clause.get("create_error") or clause.get("upload_error") or clause.get("duplicate_reason") or readonly_reason or ""


# chapter_batch_drawer.py
def set_edit_locked(self, locked: bool) -> None:
    self._save_btn.setEnabled(not locked)
    self._document_form.set_readonly(locked)


# chapter_batch_view.py
from tuv_tools.core.chapter_batch.models import get_clause_edit_state, is_document_running

def _open_drawer_for_documents(self, documents) -> None:
    ...
    current = documents[0] if documents else None
    self._drawer.set_edit_locked(bool(current and is_document_running(current.document_status)))

def _load_drawer_clauses(self, document_id: int) -> None:
    document = self._repo.get_document(document_id)
    locked = bool(document and is_document_running(document.document_status))
    ...
    editable, readonly_reason = get_clause_edit_state(
        clause_status=clause.clause_status,
        chapter_id=clause.chapter_id,
        backend_chapter_status=clause.backend_chapter_status,
    )
    editable = editable and not locked
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
pytest tests/test_chapter_batch_view.py -k "readonly_in_table or disables_form_and_save_button" -v
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit the readonly enforcement**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_drawer.py src/tuv_tools/ui/widgets/chapter_batch_document_form.py src/tuv_tools/ui/widgets/chapter_batch_clause_table.py src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_view.py
git commit -m "feat(chapter-batch): 限制草稿态条款编辑" ^
  -m "把条款编辑权限收口为未创建或后端草稿可编辑，并在文档执行中锁定整页编辑入口。" ^
  -m "Constraint: 后端状态未知必须按只读处理，不能因为本地上传失败而默认重新开放编辑" ^
  -m "Rejected: 仅在右键菜单限制重试动作 | 不能阻止用户直接在表格里改字段" ^
  -m "Confidence: high" ^
  -m "Scope-risk: moderate" ^
  -m "Directive: 所有条款编辑性都必须经过 get_clause_edit_state，不要在 UI 层复制草稿判断" ^
  -m "Tested: pytest tests/test_chapter_batch_view.py -k \"readonly_in_table or disables_form_and_save_button\" -v" ^
  -m "Not-tested: full executor regression" ^
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 5: Make Cancel Aggregation Explicit and Regression-Test the Queue Resume States

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`

- [ ] **Step 1: Write the failing cancel aggregation tests**

```python
from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor
from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus


def test_cancel_after_create_before_upload_marks_document_pending_upload(tmp_path):
    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a.docx",
            file_name="a.docx",
            document_status=DocumentStatus.PENDING_CREATE.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", source_docx_path="C:/out/10_1.docx")],
    )
    controller = ChapterBatchExecutionController()
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 1,
        upload_chapter_doc=lambda _chapter_id, _path: controller.request_cancel(),
        controller=controller,
    )

    executor.run_documents([doc_id])

    assert repo.get_document(doc_id).document_status == DocumentStatus.PENDING_UPLOAD.value


def test_cancel_after_partial_upload_marks_document_partial(tmp_path):
    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/b.docx",
            file_name="b.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.PENDING_UPLOAD.value, chapter_id=1, source_docx_path="C:/out/10_1.docx"),
            BatchImportClause(sort_index=1, term="10.2", clause_status=ClauseStatus.PENDING_UPLOAD.value, chapter_id=2, source_docx_path="C:/out/10_2.docx"),
        ],
    )
    calls = {"count": 0}

    def upload_doc(_chapter_id, _path):
        calls["count"] += 1
        if calls["count"] == 2:
            executor.request_cancel()

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 999,
        upload_chapter_doc=upload_doc,
    )

    executor.run_documents([doc_id])

    assert repo.get_document(doc_id).document_status == DocumentStatus.PARTIAL.value
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_chapter_batch_executor.py -k "cancel_after_create_before_upload or cancel_after_partial_upload" -v
```

Expected:

```text
FAIL if _apply_cancel does not explicitly preserve the desired post-cancel status
```

- [ ] **Step 3: Add a forced-status path in repository aggregation and use it from executor cancel**

```python
# repository.py
def reaggregate_document(self, document_id: int, *, forced_status: str | None = None) -> None:
    clauses = self.get_clauses(document_id)
    ...
    if forced_status is not None:
        status = forced_status
    self.update_document(
        document_id,
        document_status=status,
        total_clause_count=len(clauses),
        success_clause_count=success,
        failed_clause_count=failed,
        skipped_clause_count=skipped,
    )


# executor.py
def _apply_cancel(self, document_id: int) -> None:
    clauses = self._repo.get_clauses(document_id)
    processed_statuses = []
    remaining_statuses = []
    for clause in clauses:
        if clause.clause_status in {
            ClauseStatus.PENDING_CREATE.value,
            ClauseStatus.PENDING_UPLOAD.value,
        }:
            remaining_statuses.append(clause.clause_status)
            continue
        if clause.clause_status != ClauseStatus.SKIPPED.value:
            processed_statuses.append(clause.clause_status)
    result = apply_cancel_result(
        processed_statuses=processed_statuses,
        remaining_statuses=remaining_statuses,
    )
    self._repo.update_document(document_id, is_queued=0)
    self._repo.reaggregate_document(
        document_id,
        forced_status=result["document_status"],
    )
    self._clear_queued_flags()
```

- [ ] **Step 4: Run focused cancel tests and then the full regression suite**

Run:

```bash
pytest tests/test_chapter_batch_executor.py -k "cancel_after_create_before_upload or cancel_after_partial_upload" -v
pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_view.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_repository.py -v
pytest -q
```

Expected:

```text
Focused cancel tests: PASS
chapter_batch regression subset: PASS
full suite: PASS
```

- [ ] **Step 5: Commit the cancel-state closure**

```bash
git add src/tuv_tools/core/chapter_batch/repository.py src/tuv_tools/core/chapter_batch/executor.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_repository.py
git commit -m "fix(chapter-batch): 明确取消后的聚合状态" ^
  -m "为文档重聚合增加强制状态入口，并在执行取消时显式落到待上传、部分完成或失败等可续跑状态。" ^
  -m "Constraint: 取消不是新终态，取消后必须保持从当前状态继续可执行" ^
  -m "Rejected: 继续完全依赖隐式 reaggregate 推导取消结果 | 对创建中和上传中取消的语义不够明确" ^
  -m "Confidence: high" ^
  -m "Scope-risk: moderate" ^
  -m "Directive: executor cancel path 和 repository 聚合规则必须一起改动并一起回归测试" ^
  -m "Tested: pytest tests/test_chapter_batch_executor.py -k \"cancel_after_create_before_upload or cancel_after_partial_upload\" -v; pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_view.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_repository.py -v; pytest -q" ^
  -m "Not-tested: real backend create/upload side effects" ^
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

## Self-Review

### Spec Coverage

- 保存确认后的二次分流：Task 2, Task 3
- 仅草稿可编辑：Task 1, Task 4
- 执行中文档整体只读：Task 4
- 取消后续跑状态明确：Task 5
- 删除语义保持不变：无需代码变更，本轮不触碰删除逻辑

### Placeholder Scan

- 无 `TODO` / `TBD` / 模糊占位语
- 每个任务都包含测试、命令、代码片段和提交点

### Type Consistency

- 规则 helper 名称统一为 `is_document_running` / `get_clause_edit_state`
- 取消后聚合参数统一为 `forced_status`
- 后续 UI 锁定入口统一为 `set_edit_locked`
