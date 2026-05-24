# Preparing Recovery and Progress Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复预处理停止语义、补齐残留 `preparing` 恢复交互与 `prepare_paused` 状态流、消除多表文档拆分进度回退，并将 `pywin32` 调整为平台条件依赖。

**Architecture:** 继续沿用现有 `QThread + Signal + DatabaseManager + DocumentTable + SplitterView` 结构，不引入新表或任务系统。核心变化分为四层：`PreparingWorker` 停止控制、数据库/状态 helper、表格与视图交互信号、splitter core 进度事件语义。

**Tech Stack:** Python 3.10+, PySide6, SQLite, pywin32, pytest

**Spec:** [2026-05-24-preparing-recovery-and-progress-fix-design.md](</O:/tuv-tools/docs/superpowers/specs/2026-05-24-preparing-recovery-and-progress-fix-design.md>)

**Files expected to change (11 total):**

- Modify: `pyproject.toml`
- Modify: `src/tuv_tools/config/database.py`
- Modify: `src/tuv_tools/core/preparing/worker.py`
- Modify: `src/tuv_tools/core/splitter/parsing.py`
- Modify: `src/tuv_tools/core/splitter/ui_helpers.py`
- Modify: `src/tuv_tools/ui/views/splitter_progress.py`
- Modify: `src/tuv_tools/ui/views/splitter_view.py`
- Modify: `src/tuv_tools/ui/widgets/document_list.py`
- Modify: `tests/test_preparing_worker.py`
- Modify: `tests/test_document_table.py`
- Modify: `tests/test_splitter_view.py`
- Modify: `tests/test_splitter_progress.py`

---

### Task 1: Lock the failing behavior with regression tests

**Files:**

- Modify: `tests/test_preparing_worker.py`
- Modify: `tests/test_document_table.py`
- Modify: `tests/test_splitter_view.py`
- Modify: `tests/test_splitter_progress.py`

- [ ] **Step 1: Add worker stop semantics tests**

Add tests that fail against current behavior:

- stop after queueing multiple items only allows the current document to finish
- stop while idle wakes the worker without waiting the full idle timeout

- [ ] **Step 2: Add paused-state UI contract tests**

Add tests for:

- `prepare_paused` is non-selectable
- `DocumentTable` emits `resume_preparing_requested(doc_id)`
- `DocumentTable` emits `skip_preparing_split_requested(doc_id)`
- paused documents are excluded from normal batch split entry

- [ ] **Step 3: Add splitter view recovery flow tests**

Add view-level tests for:

- no modal when no residual `preparing` documents exist
- modal shown once when residual `preparing` documents exist
- accept path resumes queueing
- reject path moves docs to `prepare_paused`
- skip-and-split requires explicit confirmation

- [ ] **Step 4: Add monotonic progress regression tests**

Extend progress tests so a multi-table sequence cannot decrease `overall_percent`.

- [ ] **Step 5: Run the targeted regression suite and capture expected failures**

```bash
pytest tests/test_preparing_worker.py tests/test_document_table.py tests/test_splitter_view.py tests/test_splitter_progress.py -q
```

Expected at this stage: failures that prove the current code does not yet satisfy the new spec.

---

### Task 2: Narrow the dependency change

**Files:**

- Modify: `pyproject.toml`

- [ ] **Step 1: Change pywin32 to a platform-gated dependency**

Replace the unconditional dependency with:

```toml
"pywin32>=305; platform_system == 'Windows'"
```

- [ ] **Step 2: Sanity-check packaging syntax**

Run a lightweight packaging validation if available, or at minimum re-run tests in this repo after all changes land.

---

### Task 3: Add explicit database helpers for residual preparing recovery

**Files:**

- Modify: `src/tuv_tools/config/database.py`

- [ ] **Step 1: Add query helper for residual preparing documents**

Implement a focused helper, e.g.:

- `get_preparing_documents() -> list[dict[str, Any]]`

This keeps `SplitterView` from embedding raw status-filter SQL.

- [ ] **Step 2: Add small batch status update helper**

Implement a helper for uniform state transitions during recovery, e.g.:

- `update_documents_status(doc_ids: list[int], status: str, error: str | None = None) -> None`

If batch update turns out noisier than useful, keep the query helper and a narrow single-row helper extension, but do not push SQL into the view.

- [ ] **Step 3: Preserve existing success metadata semantics**

Any new helper must respect the existing `update_document_status()` behavior that preserves `last_section_count` / `last_split_at` for non-`completed` transitions.

---

### Task 4: Fix PreparingWorker stop semantics without regressing queue behavior

**Files:**

- Modify: `src/tuv_tools/core/preparing/worker.py`

- [ ] **Step 1: Introduce explicit stop state**

Add `_stop_requested` and keep `_STOP` as a wake-up sentinel, not as a normal queue item.

- [ ] **Step 2: Make stop wake idle workers immediately**

`stop()` should:

- set `_stop_requested = True`
- enqueue `_STOP` only to wake `queue.get(...)`

- [ ] **Step 3: Exit after the current document**

Adjust `run()` so:

- already-started document finishes
- once that document completes, no further queued docs are consumed
- receiving `_STOP` exits immediately when idle

- [ ] **Step 4: Keep the current guarantees**

Preserve:

- one `Dispatch("Word.Application")` per worker run
- one `Quit()` in `finally`
- best-effort `doc.Close()` per opened document
- continued processing after per-document errors when stop was not requested

---

### Task 5: Extend status helpers and table interaction contracts

**Files:**

- Modify: `src/tuv_tools/core/splitter/ui_helpers.py`
- Modify: `src/tuv_tools/ui/widgets/document_list.py`

- [ ] **Step 1: Add `prepare_paused` to status labels and non-selectable set**

Update helper contracts first so the widget behavior stays centralized.

- [ ] **Step 2: Add explicit table signals**

Add:

- `resume_preparing_requested`
- `skip_preparing_split_requested`

- [ ] **Step 3: Wire right-click actions through signals only**

`DocumentTable` should emit intent upward, not touch DB or view internals directly.

- [ ] **Step 4: Keep batch selection behavior conservative**

Ensure:

- `set_all_checked()` skips `prepare_paused`
- `set_single_checked()` skips `prepare_paused`
- row status refresh correctly disables/re-enables checkboxes

---

### Task 6: Implement residual preparing recovery flow in SplitterView

**Files:**

- Modify: `src/tuv_tools/ui/views/splitter_view.py`

- [ ] **Step 1: Add one-time recovery check after document load**

Introduce `_resume_preparing_if_needed()` and call it after the initial `_load_documents()`.

- [ ] **Step 2: Build the confirmation dialog**

Dialog requirements:

- title: `检测到未完成的预处理任务`
- show count
- show first 5 filenames max
- append “以及另外 N 个文件” when needed
- buttons: `继续处理` / `暂不处理`

- [ ] **Step 3: Implement accept path**

For accepted recovery:

- keep docs in `preparing`
- filter out missing source files into `failed`
- ensure worker exists
- requeue remaining files

- [ ] **Step 4: Implement reject path**

For rejected recovery:

- move residual `preparing` docs to `prepare_paused`
- refresh rows without kicking off background work

- [ ] **Step 5: Implement explicit paused actions**

Hook new table signals to:

- continue preparing
- skip preparing and split with confirmation

- [ ] **Step 6: Keep skip-and-split outside batch logic**

Do not add hidden branches in `_start_batch_split()` that special-case paused docs.  
Use a dedicated single-document path.

- [ ] **Step 7: Preserve shutdown ordering**

`closeEvent()` should still:

- cancel split worker
- wait parse worker
- stop preparing worker

But now the preparing worker must reliably wake and exit.

---

### Task 7: Fix core progress semantics before UI smoothing

**Files:**

- Modify: `src/tuv_tools/core/splitter/parsing.py`
- Modify: `src/tuv_tools/ui/views/splitter_progress.py`

- [ ] **Step 1: Define a global splitting_tables progress context**

In `build_sections()`, precompute:

- total scanned table rows across all table blocks that `_split_table_into_sections()` will actually scan

- [ ] **Step 2: Emit cumulative progress from core**

Refactor `_split_table_into_sections()` so emitted `CoreProgressEvent("splitting_tables", ...)` uses:

- `current = cumulative scanned rows so far`
- `total = total scanned rows in this document`

- [ ] **Step 3: Add UI-side monotonic guard**

In `SplitProgressMapper`, track the last emitted `overall_percent` and clamp new values so they never decrease.

- [ ] **Step 4: Preserve existing phase semantics**

Keep:

- `completed` => exact document completion percentage
- bounded 0-100 values
- existing throttling behavior

---

### Task 8: Verify targeted suites, then full regression

**Files:**

- No source changes expected unless verification exposes gaps

- [ ] **Step 1: Run targeted suites**

```bash
pytest tests/test_preparing_worker.py tests/test_document_table.py tests/test_splitter_view.py tests/test_splitter_progress.py -q
```

- [ ] **Step 2: Run broader affected regression**

```bash
pytest tests/test_preparing.py tests/test_splitter.py tests/test_database.py -q
```

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```

- [ ] **Step 4: Manual QA pass**

Minimum manual checks:

- import several docs, close app before queue drains, relaunch and confirm recovery dialog
- reject recovery and confirm paused rows cannot be batch-split
- use “继续预处理” on one paused doc
- use “跳过预处理并拆分” on one paused doc and confirm warning path
- run a multi-table sample and watch progress remain monotonic

---

### Task 9: Clean handoff and commit

**Files:**

- Modified code and tests from Tasks 2-8

- [ ] **Step 1: Review diff for blast-radius creep**

Ensure the implementation stayed within the files and contracts defined by the spec.

- [ ] **Step 2: Summarize remaining risk**

Call out any residual limits, especially:

- runtime still Windows-only for actual Word automation
- paused-state discoverability if the first version keeps right-click as the only entry

- [ ] **Step 3: Commit with Lore trailers**

Commit only after tests pass and manual QA is complete.
