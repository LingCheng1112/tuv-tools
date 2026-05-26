# Chapter Batch Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变既定拆分规则和清洗效果的前提下，将现有 `chapter_batch` 工作台从“批量导入”语义重整为“批量上传”，实现自动预处理、上传前最终判重、保存/上传解耦、重复覆盖仅覆盖 docx、以及右侧抽屉滑入滑出交互。

**Architecture:** 保留现有 `chapter_batch` 单模块分层结构，不新增数据域和新模块。先用测试锁定新状态机和新流程，再按 `models -> repository -> service -> executor -> ui -> preparing integration` 顺序逐层收口，避免新文案覆盖旧状态机。所有重复规则、覆盖语义、状态回退语义都在本地层实现，后端接口只复用现有查询与上传能力。

**Tech Stack:** Python 3.10+, PySide6, SQLite (`sqlite3`), requests, pytest

---

## File Structure

### Primary Files To Modify

- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
  - 重定义文档级/条款级显式状态，移除旧 `待创建 / 创建中 / 创建失败 / 已跳过`
  - 重新定义可上传状态、运行态状态、条款编辑约束辅助函数
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
  - 重写 `reaggregate_document()`，去掉对 `PENDING_CREATE` 的主导依赖
  - 增加“全部重复跳过则回退待上传”的文档聚合规则
  - 增加旧状态兼容读取/聚合策略
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
  - 将重复判定从保存期移到上传前
  - 将保存语义改为“仅本地持久化确认数据”
  - 引入 `specific_product` 四态比较
  - 接入“导入后自动预处理 -> 预处理完成后自动拆分”
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
  - 将“创建 chapter”改成上传内部动作，不再作为外显状态
  - 增加重复覆盖、重复跳过、重复确认取消的上传路径
  - 修正取消后的状态回退逻辑
- `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
  - 将标题、按钮、操作节奏改为“上传”语义
  - 删除“批量确认 / 开始执行”的旧页面心智
  - 上传前收集最终参数并触发逐条判重
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
  - 增加右侧滑入/滑出动画
  - 加入 dirty 检测，约束“修改后必须先保存”
  - 统一遮罩 / X / Esc 的关闭 contract
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
  - 对齐新条款状态文案和右键动作
- `O:\tuv-tools\src\tuv_tools\ui\main_window.py`
  - 更新页面命名为 `条款批量上传`

### Supporting Files To Inspect During Implementation

- `O:\tuv-tools\src\tuv_tools\config\database.py`
  - 确认现有 `batch_import_documents / batch_import_clauses / batch_import_events` schema 是否已满足新状态和值兼容
- `O:\tuv-tools\src\tuv_tools\core\preparing\worker.py`
  - 复用现有预处理线程能力，不引入第二套 worker 语义
- `O:\tuv-tools\src\tuv_tools\core\chapter\api.py`
  - 复用现有 `get_chapters()` 作为上传前重复查询来源

### Test Files To Modify

- `O:\tuv-tools\tests\test_chapter_batch_models.py`
- `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- `O:\tuv-tools\tests\test_chapter_batch_service.py`
- `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- `O:\tuv-tools\tests\test_chapter_batch_view.py`

### Boundaries

- `models.py` 只定义状态和纯规则，不做 IO
- `repository.py` 只做持久化和聚合，不做 UI 判断
- `service.py` 负责保存、重拆、判重、预处理接线等本地业务
- `executor.py` 负责上传编排和取消安全点
- `view/drawer/clause_table` 只负责交互，不定义业务真相

---

## Task 1: Lock New State Vocabulary With Tests

**Files:**
- Modify: `O:\tuv-tools\tests\test_chapter_batch_models.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_executor.py`

- [ ] **Step 1: Rewrite model tests to target the new explicit statuses**

```python
def test_document_status_contains_upload_workspace_states():
    assert DocumentStatus.PENDING_CONFIRM.value == "待确认"
    assert DocumentStatus.PENDING_UPLOAD.value == "待上传"
    assert DocumentStatus.UPLOADING.value == "上传中"
    assert DocumentStatus.COMPLETED.value == "已完成"
    assert DocumentStatus.PARTIAL.value == "部分完成"
    assert DocumentStatus.FAILED.value == "失败"


def test_document_status_does_not_expose_create_phase_states():
    values = {status.value for status in DocumentStatus}
    assert "待创建" not in values
    assert "创建中" not in values
    assert "已跳过" not in values


def test_clause_status_contains_upload_only_states():
    values = {status.value for status in ClauseStatus}
    assert values == {"待上传", "上传中", "上传成功", "上传失败", "重复跳过"}
```

- [ ] **Step 2: Rewrite executable/running-state policy tests**

```python
def test_pending_confirm_is_executable_for_direct_upload():
    assert is_document_executable(DocumentStatus.PENDING_CONFIRM.value) is True


def test_running_states_only_expose_preparing_split_upload():
    assert is_document_running(DocumentStatus.UPLOADING.value) is True
    assert is_document_running(DocumentStatus.PENDING_UPLOAD.value) is False
    assert is_document_running(DocumentStatus.PENDING_CONFIRM.value) is False
```

- [ ] **Step 3: Rewrite repository/service/executor tests that currently assert `PENDING_CREATE`**

```python
def test_save_confirmed_documents_sets_pending_upload():
    saved = repo.get_document(doc_id)
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value


def test_cancel_without_success_returns_pending_upload_instead_of_pending_create():
    assert status == DocumentStatus.PENDING_UPLOAD.value
```

- [ ] **Step 4: Run the targeted tests and confirm they fail for the right reason**

Run: `pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py -q`

Expected:
- FAIL because current code still exposes `待创建 / 创建中 / 创建失败`
- FAIL because save still returns `PENDING_CREATE`
- FAIL because cancel fallback still returns `PENDING_CREATE`

- [ ] **Step 5: Commit the failing-test checkpoint**

```bash
git add tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py
git commit -m "test: lock batch upload state vocabulary"
```

---

## Task 2: Rewrite Status Enums And Pure Status Helpers

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`

- [ ] **Step 1: Replace document and clause enums with upload-oriented values**

```python
class DocumentStatus(StrEnum):
    PREPARING = "预处理中"
    SPLITTING = "拆分中"
    PENDING_CONFIRM = "待确认"
    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    COMPLETED = "已完成"
    PARTIAL = "部分完成"
    FAILED = "失败"


class ClauseStatus(StrEnum):
    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    UPLOAD_SUCCESS = "上传成功"
    UPLOAD_FAILED = "上传失败"
    DUPLICATE_SKIPPED = "重复跳过"
```

- [ ] **Step 2: Update executable/running state helpers**

```python
EXECUTABLE_DOCUMENT_STATUSES = {
    DocumentStatus.PENDING_CONFIRM.value,
    DocumentStatus.PENDING_UPLOAD.value,
    DocumentStatus.PARTIAL.value,
    DocumentStatus.FAILED.value,
}

RUNNING_DOCUMENT_STATUSES = {
    DocumentStatus.PREPARING.value,
    DocumentStatus.SPLITTING.value,
    DocumentStatus.UPLOADING.value,
}
```

- [ ] **Step 3: Update dataclass defaults to match the new semantics**

```python
document_status: str = DocumentStatus.SPLITTING.value
clause_status: str = ClauseStatus.PENDING_UPLOAD.value
```

Implementation note:
- `BatchImportDocument.document_status` 不能默认成 `待拆分`，因为该值不在新显式状态集中
- 如果需要保留导入瞬时态，用 `PREPARING` / `SPLITTING` 表达

- [ ] **Step 4: Run model tests**

Run: `pytest tests/test_chapter_batch_models.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/models.py tests/test_chapter_batch_models.py
git commit -m "refactor: switch chapter batch models to upload states"
```

---

## Task 3: Rebuild Repository Aggregation And Legacy Status Compatibility

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`

- [ ] **Step 1: Add tests for new aggregation outcomes**

```python
def test_reaggregate_document_returns_pending_upload_when_all_clauses_duplicate_skipped():
    repo.reaggregate_document(doc_id)
    saved = repo.get_document(doc_id)
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value


def test_reaggregate_document_returns_partial_when_success_and_duplicate_skipped_mix():
    repo.reaggregate_document(doc_id)
    saved = repo.get_document(doc_id)
    assert saved.document_status == DocumentStatus.PARTIAL.value
```

- [ ] **Step 2: Add tests for old-state compatibility reads**

```python
def test_legacy_pending_create_document_can_still_be_loaded_as_pending_upload():
    repo._conn.execute(
        "UPDATE batch_import_documents SET document_status = ? WHERE id = ?",
        ("待创建", doc_id),
    )
    repo._conn.commit()

    saved = repo.get_document(doc_id)
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value
```

- [ ] **Step 3: Implement normalization helpers inside repository**

```python
LEGACY_DOCUMENT_STATUS_MAP = {
    "待创建": DocumentStatus.PENDING_UPLOAD.value,
    "创建中": DocumentStatus.UPLOADING.value,
    "已跳过": DocumentStatus.PENDING_UPLOAD.value,
}

LEGACY_CLAUSE_STATUS_MAP = {
    "待创建": ClauseStatus.PENDING_UPLOAD.value,
    "创建失败": ClauseStatus.UPLOAD_FAILED.value,
    "用户跳过": ClauseStatus.DUPLICATE_SKIPPED.value,
}
```

- [ ] **Step 4: Rewrite `reaggregate_document()` around the new status truth table**

```python
if clauses and all(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses):
    status = DocumentStatus.COMPLETED.value
elif success > 0 and (failed > 0 or duplicate_skipped > 0 or pending_upload > 0):
    status = DocumentStatus.PARTIAL.value
elif duplicate_skipped == len(clauses) and clauses:
    status = DocumentStatus.PENDING_UPLOAD.value
elif pending_upload > 0:
    status = DocumentStatus.PENDING_UPLOAD.value
elif failed > 0:
    status = DocumentStatus.FAILED.value
else:
    status = DocumentStatus.PENDING_CONFIRM.value
```

- [ ] **Step 5: Run repository tests**

Run: `pytest tests/test_chapter_batch_repository.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/repository.py tests/test_chapter_batch_repository.py
git commit -m "refactor: update batch upload aggregation rules"
```

---

## Task 4: Move Duplicate Detection To Upload Time And Fix Save Semantics

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`

- [ ] **Step 1: Replace duplicate-check tests with final-parameter upload-time semantics**

```python
def test_duplicate_check_uses_folder_term_test_content_and_specific_product():
    result = check_duplicate_candidates(folder_id=7, clause=current, existing_rows=existing)
    assert result.is_duplicate is True


def test_duplicate_check_treats_blank_and_non_blank_specific_product_as_non_duplicate():
    result = check_duplicate_candidates(folder_id=7, clause=current, existing_rows=existing)
    assert result.is_duplicate is False
```

- [ ] **Step 2: Add tests for save behavior**

```python
def test_save_confirmed_documents_sets_pending_upload_instead_of_pending_create():
    ready = service.save_confirmed_documents({...})
    saved = repo.get_document(doc_id)
    assert ready == [doc_id]
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value


def test_save_confirmed_documents_skips_running_document():
    ready = service.save_confirmed_documents({...})
    assert ready == []
```

- [ ] **Step 3: Rewrite `check_duplicate_candidates()` to compare the fourth dimension**

```python
def _same_specific_product(left: str, right: str) -> bool:
    left_value = (left or "").strip()
    right_value = (right or "").strip()
    if not left_value and not right_value:
        return True
    if not left_value or not right_value:
        return False
    return left_value == right_value
```

- [ ] **Step 4: Remove save-time duplicate marking from the mandatory save path**

```python
def save_confirmed_documents(...):
    ...
    payload = {
        ...
        "document_status": DocumentStatus.PENDING_UPLOAD.value,
    }
```

Implementation note:
- `mark_duplicate_candidates()` 可以保留为临时 UI 辅助能力，但不能再作为上传前唯一真相
- 如果保留 `duplicate_flag / duplicate_reason`，它们必须被视作临时缓存

- [ ] **Step 5: Run service tests**

Run: `pytest tests/test_chapter_batch_service.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/service.py tests/test_chapter_batch_service.py
git commit -m "refactor: move batch upload duplicate logic to final params"
```

---

## Task 5: Introduce Upload-Only Executor Paths

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`

- [ ] **Step 1: Add failing tests for overwrite and duplicate-skip paths**

```python
def test_executor_overwrite_duplicate_reuses_existing_chapter_id(tmp_path):
    assert created_ids == []
    assert uploaded_ids == [existing_chapter_id]


def test_executor_marks_duplicate_skipped_and_continues_next_clause(tmp_path):
    assert first_clause.clause_status == ClauseStatus.DUPLICATE_SKIPPED.value
    assert second_clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
```

- [ ] **Step 2: Add failing tests for cancel fallback and no-create external state**

```python
def test_cancel_without_success_returns_pending_upload():
    status = derive_document_status_after_cancel(...)
    assert status == DocumentStatus.PENDING_UPLOAD.value


def test_executor_only_exposes_uploading_document_state(tmp_path):
    saved = repo.get_document(doc_id)
    assert saved.document_status != "创建中"
```

- [ ] **Step 3: Replace create/upload two-phase visible flow with internal branching**

```python
if clause.user_decision == "overwrite" and clause.chapter_id is not None:
    self._upload_existing_clause_doc(clause)
elif clause.user_decision == "skip":
    self._repo.update_clause(clause.id, clause_status=ClauseStatus.DUPLICATE_SKIPPED.value)
else:
    chapter_id = self._create_chapter(...)
    self._upload_chapter_doc(chapter_id, clause.source_docx_path)
```

- [ ] **Step 4: Rewrite cancel fallback**

```python
if had_upload_success:
    return DocumentStatus.PARTIAL.value
if has_pending_upload:
    return DocumentStatus.PENDING_UPLOAD.value
if attempted_uploads_all_failed:
    return DocumentStatus.FAILED.value
return DocumentStatus.PENDING_UPLOAD.value
```

- [ ] **Step 5: Run executor tests**

Run: `pytest tests/test_chapter_batch_executor.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/executor.py tests/test_chapter_batch_executor.py
git commit -m "refactor: make chapter batch executor upload-oriented"
```

---

## Task 6: Rename Page Semantics And Decouple Save From Upload

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\main_window.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Rewrite page-level UI text tests**

```python
def test_workspace_has_upload_title_and_actions(qapp):
    assert view.windowTitle() == ""
    assert view._title_label.text() == "条款批量上传"
    assert view._upload_btn.text() == "批量上传"
    assert "批量确认" not in all_button_texts
    assert "开始执行" not in all_button_texts
```

- [ ] **Step 2: Add tests for upload without edits and upload blocked when dirty**

```python
def test_upload_requested_uses_current_saved_document_without_forced_save(qapp, monkeypatch):
    view._on_upload_requested(doc_id, [clause_id])
    assert saved_calls == []
    assert started_upload_ids == [doc_id]


def test_upload_requested_blocks_when_drawer_has_unsaved_edits(qapp, monkeypatch):
    view._on_upload_requested(doc_id, [clause_id])
    assert started_upload_ids == []
    assert warnings == ["请先保存修改后再上传"]
```

- [ ] **Step 3: Rename page actions and replace old footer semantics**

```python
title = QLabel("条款批量上传")
self._upload_selected_btn = QPushButton("批量上传")
self._delete_btn = QPushButton("删除记录")
```

- [ ] **Step 4: Split save and upload execution paths**

```python
def _on_upload_requested(self, document_id: int, clause_ids: list[int]) -> None:
    if self._drawer.is_dirty(document_id):
        QMessageBox.warning(self, "提示", "请先保存修改后再上传")
        return
    if not self._resolve_upload_duplicates(document_id, clause_ids):
        return
    self._start_clause_upload(document_id, clause_ids)
```

- [ ] **Step 5: Run view tests that cover page semantics and upload/save decoupling**

Run: `pytest tests/test_chapter_batch_view.py -k "upload or save or title or start" -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/ui/main_window.py tests/test_chapter_batch_view.py
git commit -m "refactor: switch chapter batch view to upload semantics"
```

---

## Task 7: Add Drawer Slide Animation And Dirty-State Contract

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Add tests for slide-in / slide-out contract**

```python
def test_double_click_document_opens_drawer_with_slide_in_contract(qapp):
    view._open_document_drawer(doc_id)
    assert drawer.isVisible() is True
    assert drawer.is_animating() is True


def test_mask_close_x_close_and_escape_use_slide_out_contract(qapp):
    drawer.request_close()
    assert drawer.is_animating() is True
```

- [ ] **Step 2: Add tests for dirty-state save gating**

```python
def test_drawer_save_button_enabled_only_when_dirty(qapp):
    assert drawer.save_button().isEnabled() is False
    drawer.mark_dirty()
    assert drawer.save_button().isEnabled() is True
```

- [ ] **Step 3: Implement animated open/close helpers**

```python
self._slide_animation = QPropertyAnimation(self, b"geometry")
self._slide_animation.setDuration(180)
self._slide_animation.setEasingCurve(QEasingCurve.OutCubic)
```

- [ ] **Step 4: Route all close paths through one animated close method**

```python
def request_close(self) -> None:
    if self._is_closing:
        return
    self._play_close_animation()
```

- [ ] **Step 5: Run targeted drawer/view tests**

Run: `pytest tests/test_chapter_batch_view.py -k "drawer or close or opaque or wider" -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_drawer.py tests/test_chapter_batch_view.py
git commit -m "feat: animate chapter batch drawer transitions"
```

---

## Task 8: Update Clause Table Statuses And Right-Click Actions

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Replace old clause-status tests**

```python
def test_clause_table_actions_follow_upload_statuses(qapp):
    assert "标记待创建" not in actions
    assert "上传条款" in actions
    assert "查看错误原因" in actions
```

- [ ] **Step 2: Implement new status-to-action mapping**

```python
UPLOAD_ACTIONABLE_STATUSES = {
    ClauseStatus.PENDING_UPLOAD.value,
    ClauseStatus.UPLOAD_FAILED.value,
    ClauseStatus.DUPLICATE_SKIPPED.value,
}
```

- [ ] **Step 3: Keep duplicate/error details in context menu, not the main table**

```python
if clause.duplicate_reason:
    menu.addAction("查看重复原因", ...)
if clause.upload_error or clause.create_error:
    menu.addAction("查看错误原因", ...)
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_chapter_batch_view.py -k "clause_table or duplicate or readonly action" -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/ui/widgets/chapter_batch_clause_table.py tests/test_chapter_batch_view.py
git commit -m "refactor: align clause table with upload workflow"
```

---

## Task 9: Integrate Automatic Preparing Pipeline

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Inspect: `O:\tuv-tools\src\tuv_tools\core\preparing\worker.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Add service tests for `import -> preparing -> split`**

```python
def test_import_and_split_documents_runs_preparing_before_split(monkeypatch):
    calls = []
    ...
    assert calls == ["import", "prepare", "split"]


def test_preparing_failure_marks_document_failed(monkeypatch):
    saved = repo.get_document(doc_id)
    assert saved.document_status == DocumentStatus.FAILED.value
```

- [ ] **Step 2: Add view tests for auto-processing status progression**

```python
def test_import_selected_paths_enters_preparing_then_splitting(qapp, monkeypatch):
    assert observed_statuses == ["预处理中", "拆分中", "待确认"]
```

- [ ] **Step 3: Reuse existing preparing worker integration instead of creating new worker semantics**

```python
def import_and_split_documents(...):
    documents = self.import_documents(paths, split_mode)
    for document in documents:
        self._repo.update_document(document.id, document_status=DocumentStatus.PREPARING.value)
        prepared_path = self._prepare_document(document.file_path)
        self._split_prepared_document(document.id, prepared_path)
```

Implementation note:
- 这里必须复用已有 `preparing` 处理能力
- 不允许在 `chapter_batch` 内再复制一套独立 Word worker 逻辑

- [ ] **Step 4: Run service + view tests**

Run: `pytest tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py -k "prepare or import_selected_paths or split" -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/chapter_batch/service.py src/tuv_tools/ui/views/chapter_batch_view.py tests/test_chapter_batch_service.py tests/test_chapter_batch_view.py
git commit -m "feat: auto-run preparing pipeline before batch split"
```

---

## Task 10: End-To-End Regression Sweep

**Files:**
- Modify if needed: all touched files above
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] **Step 1: Run the full chapter batch suite**

Run:

```powershell
pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py -q
```

Expected:
- PASS
- No assertion still depends on `待创建 / 创建中 / 创建失败`

- [ ] **Step 2: Run the broader splitter/preparing safety net**

Run:

```powershell
pytest tests/test_preparing.py tests/test_preparing_worker.py tests/test_splitter.py -q
```

Expected:
- PASS
- 本轮没有改变拆分和清洗效果

- [ ] **Step 3: Manual verification checklist**

```text
1. 导入文档后自动进入“预处理中”再进入“拆分中”
2. 拆分完成后文档进入“待确认”
3. 未修改参数时，双击抽屉可直接上传
4. 修改参数后，上传被阻止并提示先保存
5. 重复条款逐条弹窗：
   - 覆盖 -> 只覆盖 docx
   - 跳过 -> 当前条款重复跳过，后续继续
6. 一个文档所有条款都被跳过时，文档回退“待上传”
7. 抽屉从右侧滑入，遮罩/X/Esc 均滑出关闭
```

- [ ] **Step 4: Final commit**

```bash
git add src/tuv_tools/core/chapter_batch src/tuv_tools/ui/views/chapter_batch_view.py src/tuv_tools/ui/widgets/chapter_batch_drawer.py src/tuv_tools/ui/widgets/chapter_batch_clause_table.py src/tuv_tools/ui/main_window.py tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py
git commit -m "feat: align chapter batch workflow with upload semantics"
```

---

## Spec Coverage Check

- “更名为批量上传”:
  - Task 6
- “抽屉右侧滑动出现和消失”:
  - Task 7
- “取消待创建、创建中状态”:
  - Task 1, Task 2, Task 3, Task 5
- “导入 -> 预处理 -> 拆分 -> 核对 -> 保存(可选) -> 上传”:
  - Task 4, Task 6, Task 9
- “未修改可直接上传，修改后必须先保存”:
  - Task 6, Task 7
- “上传时判重，不是保存时判重”:
  - Task 4, Task 6
- “specific_product 判重规则”:
  - Task 4
- “重复覆盖只覆盖 docx，不改元数据”:
  - Task 5
- “不覆盖则只跳过当前条款，继续后续条款”:
  - Task 5
- “全部重复跳过回退待上传”:
  - Task 3, Task 5
- “不改变拆分规则和清洗效果”:
  - Task 10

## Placeholder Scan

- 本计划不使用 `TBD` / `TODO` / “后续实现”
- 每个 Task 都给出明确文件、命令、预期结果
- 每个关键行为改动都绑定了至少一条测试或校验动作

## Type And Naming Consistency

- 文档级新状态统一使用：
  - `PREPARING`
  - `SPLITTING`
  - `PENDING_CONFIRM`
  - `PENDING_UPLOAD`
  - `UPLOADING`
  - `COMPLETED`
  - `PARTIAL`
  - `FAILED`
- 条款级新状态统一使用：
  - `PENDING_UPLOAD`
  - `UPLOADING`
  - `UPLOAD_SUCCESS`
  - `UPLOAD_FAILED`
  - `DUPLICATE_SKIPPED`

