# Checkbox Replacement Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 导入 DOCX 时后台执行复选框统一替换预处理（VBA → win32com），列表中新增 `preparing` 状态且该状态下禁止拆分。

**Architecture:** 新增 `PreparingWorker`(QThread) 在 `_add_paths()` 中启动，通过 win32com 调用 Word 逐文档处理。遵循现有 `SplitWorker` 模式——QThread + Signal + 列表持有防 GC。`finally` 块确保 Word 进程不会泄漏。

**Tech Stack:** Python 3.10+, PySide6, pywin32 (win32com), SQLite

**Spec:** `docs/superpowers/specs/2026-05-24-checkbox-replacement-design.md`

**Files changed (5 total):**
- Create: `resources/unify_checkboxes.bas`, `src/tuv_tools/core/preparing/__init__.py`, `tests/test_preparing.py`
- Modify: `pyproject.toml`, `src/tuv_tools/ui/widgets/document_list.py`, `src/tuv_tools/ui/views/splitter_view.py`, `tests/test_splitter.py`

---

### Task 1: Copy and localize VBA script

**Files:**
- Create: `resources/unify_checkboxes.bas`

- [ ] **Step 1: Copy .bas from source**

```bash
cp "D:\\Data\\统一替换复选框.bas" resources/unify_checkboxes.bas
```

- [ ] **Step 2: Replace Chinese identifiers with English**

Three replacements in `resources/unify_checkboxes.bas`:
- `统一替换复选框` (module name) → `UnifyCheckboxes`
- `批量替换全部复选框` (procedure name) → `ReplaceAllCheckboxes`
- `替换失败：` (error message) → `Replacement failed: `

- [ ] **Step 3: Commit**

```bash
git add resources/unify_checkboxes.bas
git commit -m "feat(preparing): add VBA checkbox replacement reference script"
```

---

### Task 2: Add pywin32 dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pywin32 to dependencies**

In `pyproject.toml`, add `"pywin32>=305",` to the `dependencies` list.

- [ ] **Step 2: Install pywin32**

```bash
pip install pywin32>=305
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add pywin32 for Word COM automation"
```

---

### Task 3: Create PreparingWorker module (TDD)

**Files:**
- Create: `src/tuv_tools/core/preparing/__init__.py`
- Test: `tests/test_preparing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_preparing.py`:

```python
"""Tests for preparing module — win32com Word automation for checkbox replacement"""

from unittest.mock import MagicMock, patch
import pytest

from tuv_tools.core.preparing import prepare_document, PreparingWorker


class TestPrepareDocument:
    """Test VBA-to-win32com port correctness"""

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_opens_document_saves_and_quits_word(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_docs = MagicMock()
        mock_app.Documents = mock_docs
        mock_docs.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_win32com.client.Dispatch.assert_called_once_with("Word.Application")
        mock_docs.Open.assert_called_once_with("C:\\docs\\test.docx")
        mock_doc.Save.assert_called_once()
        mock_doc.Close.assert_called_once()
        mock_app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_unprotects_if_document_is_protected(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ProtectionType = 2
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_called_once()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_no_unprotect_when_not_protected(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # wdNoProtection
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_not_called()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_replaces_plain_text_checkbox_symbols(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        # Find.Execute was called (at minimum for the two checkbox symbols)
        execute_calls = mock_doc.Content.Find.Execute.call_args_list
        assert len(execute_calls) >= 2

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_converts_legacy_formfield_checkboxes(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_ff = MagicMock()
        mock_ff.Type = 71  # wdFieldFormCheckBox
        mock_ff.CheckBox.Value = True
        mock_doc.FormFields.Count = 1
        mock_doc.FormFields.side_effect = lambda i: mock_ff if i == 1 else None
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        assert mock_doc.ContentControls.Add.called

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_quits_word_on_error_to_prevent_zombie_process(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_app.Documents.Open.return_value = mock_doc
        mock_doc.Content.side_effect = RuntimeError("COM failure")
        mock_win32com.client.Dispatch.return_value = mock_app

        with pytest.raises(RuntimeError, match="COM failure"):
            prepare_document("C:\\docs\\test.docx")

        # Must quit even on error -- no zombie Word process
        mock_app.Quit.assert_called_once()


class TestPreparingWorker:
    """Test PreparingWorker QThread signal emission"""

    def test_emits_doc_prepared_on_success(self, qtbot):
        with patch("tuv_tools.core.preparing.prepare_document") as mock_prepare:
            worker = PreparingWorker([(1, "C:\\a.docx")])
            results = []

            worker.doc_prepared.connect(lambda did: results.append(did))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert results == [1]
            mock_prepare.assert_called_once_with("C:\\a.docx")

    def test_emits_doc_error_on_failure(self, qtbot):
        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=RuntimeError("Word crash")):
            worker = PreparingWorker([(2, "C:\\bad.docx")])
            errors = []

            worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert len(errors) == 1
            assert errors[0] == (2, "Word crash")

    def test_processes_multiple_items_sequentially(self, qtbot):
        results = []
        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=lambda p: results.append(p)):
            worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert results == ["C:\\a.docx", "C:\\b.docx"]

    def test_continues_after_one_failure(self, qtbot):
        call_count = [0]

        def failing_prepare(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=failing_prepare):
            worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])
            errors = []
            successes = []
            worker.doc_error.connect(lambda did, msg: errors.append(did))
            worker.doc_prepared.connect(lambda did: successes.append(did))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert errors == [1]
            assert successes == [2]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_preparing.py -v
```

Expected: FAIL — module `tuv_tools.core.preparing` not found

- [ ] **Step 3: Write PreparingWorker module**

Create `src/tuv_tools/core/preparing/__init__.py`:

```python
"""DOCX 预处理：win32com Word 自动化执行复选框统一替换"""

from __future__ import annotations

import win32com.client  # type: ignore[import-untyped]

from PySide6.QtCore import QThread, Signal


def prepare_document(docx_path: str) -> None:
    """对指定 DOCX 执行复选框统一替换预处理

    将旧式表单域复选框和纯文本符号（☒/☐）统一转换为
    ContentControl 复选框。修改直接写入原文件。
    """
    app = None
    doc = None
    try:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = False
        app.ScreenUpdating = False

        doc = app.Documents.Open(docx_path)
        if doc.ProtectionType != -1:  # wdNoProtection
            doc.Unprotect()

        _replace_plain_checkbox_symbols(doc)
        _replace_legacy_formfield_checkboxes(doc)
        _replace_markers_with_content_controls(doc)

        doc.Save()
    finally:
        if doc is not None:
            try:
                doc.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass


def _replace_plain_checkbox_symbols(doc) -> None:
    """Step 1: 将纯文本复选框符号替换为临时标记"""
    symbol_map = [
        (chr(0x2612), "@@CHECKED_BOX@@"),   # U+2612 checked box
        (chr(0x2610), "@@UNCHECKED_BOX@@"),  # U+2610 unchecked box
    ]
    for find_text, replace_text in symbol_map:
        rng = doc.Content
        find = rng.Find
        find.ClearFormatting()
        find.Replacement.ClearFormatting()
        find.Text = find_text
        find.Replacement.Text = replace_text
        find.Forward = True
        find.Wrap = 0  # wdFindStop
        find.Format = False
        find.Execute(Replace=2)  # wdReplaceAll


def _replace_legacy_formfield_checkboxes(doc) -> None:
    """Step 2: 将旧式表单域复选框替换为 ContentControl 复选框"""
    for i in range(doc.FormFields.Count, 0, -1):
        ff = doc.FormFields(i)
        if ff.Type != 71:  # wdFieldFormCheckBox
            continue
        target_range = ff.Range.Duplicate
        is_checked = ff.CheckBox.Value
        ff.Delete()
        cc = doc.ContentControls.Add(8, target_range)  # wdContentControlCheckBox
        cc.Checked = is_checked
        _normalize_checkbox_font(cc)


def _replace_markers_with_content_controls(doc) -> None:
    """Step 3: 将临时标记替换为 ContentControl 复选框"""
    markers = [
        ("@@CHECKED_BOX@@", True),
        ("@@UNCHECKED_BOX@@", False),
    ]
    for marker_text, is_checked in markers:
        rng = doc.Content
        find = rng.Find
        find.ClearFormatting()
        find.Text = marker_text
        find.Forward = True
        find.Wrap = 0  # wdFindStop
        find.Format = False

        while find.Execute():
            found_range = rng.Duplicate
            found_range.Delete()
            found_range.Collapse(1)  # wdCollapseStart

            try:
                cc = doc.ContentControls.Add(8, found_range)
                cc.Checked = is_checked
                _normalize_checkbox_font(cc)
                rng.SetRange(cc.Range.End, doc.Content.End)
            except Exception:
                found_range.Text = marker_text
                rng.SetRange(found_range.End, doc.Content.End)


def _normalize_checkbox_font(cc) -> None:
    """Step 4: 清除复选框字体样式"""
    cc.Range.Font.Italic = False
    cc.Range.Font.Bold = False


class PreparingWorker(QThread):
    """后台预处理工作线程：逐个文档执行复选框统一替换"""

    doc_prepared = Signal(int)
    doc_error = Signal(int, str)

    def __init__(self, items: list[tuple[int, str]]):
        """items: [(doc_id, file_path), ...]"""
        super().__init__()
        self._items = items

    def run(self) -> None:
        for doc_id, file_path in self._items:
            try:
                prepare_document(file_path)
                self.doc_prepared.emit(doc_id)
            except Exception as exc:
                self.doc_error.emit(doc_id, str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_preparing.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/tuv_tools/core/preparing/__init__.py tests/test_preparing.py
git commit -m "feat(preparing): add PreparingWorker for DOCX checkbox replacement"
```

---

### Task 4: Update DocumentTable for preparing status

**Files:**
- Modify: `src/tuv_tools/ui/widgets/document_list.py`
- Test: `tests/test_splitter.py` (extend existing)

- [ ] **Step 1: Add preparing status label**

In `document_list.py`, add to `STATUS_LABELS` dict (insert before the closing `}`):

```python
    "preparing": "⟳ 预处理中",
```

- [ ] **Step 2: Disable checkbox for preparing/processing documents**

In `_build_row()`, after `self.setCellWidget(row, self.COL_CHECK, cb)` (line 132), add:

```python
        can_select = doc["status"] not in ("preparing", "processing")
        cb.setEnabled(can_select)
```

- [ ] **Step 3: Hide "Split" context menu for preparing/processing documents**

In `_show_context_menu()`, wrap lines 196-198 with a condition. Replace:

```python
        split_action = QAction("拆分此文档", self)
        split_action.triggered.connect(lambda: self.split_requested.emit(doc["id"]))
        menu.addAction(split_action)
```

With:

```python
        if doc["status"] not in ("preparing", "processing"):
            split_action = QAction("拆分此文档", self)
            split_action.triggered.connect(lambda: self.split_requested.emit(doc["id"]))
            menu.addAction(split_action)
```

- [ ] **Step 4: Add test for preparing status label**

In `tests/test_splitter.py`, add to `TestSplitterUiHelpers` class:

```python
    def test_preparing_status_label_exists(self):
        from tuv_tools.ui.widgets.document_list import STATUS_LABELS
        assert STATUS_LABELS["preparing"] == "⟳ 预处理中"
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_splitter.py::TestSplitterUiHelpers -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tuv_tools/ui/widgets/document_list.py tests/test_splitter.py
git commit -m "feat(preparing): add preparing status to document list with disabled split"
```

---

### Task 5: Update SplitterView import flow

**Files:**
- Modify: `src/tuv_tools/ui/views/splitter_view.py`

- [ ] **Step 1: Import PreparingWorker**

Add after line 30 (the Toast import):

```python
from tuv_tools.core.preparing import PreparingWorker
```

- [ ] **Step 2: Initialize _preparing_workers list in __init__**

After line 146:

```python
        self._preparing_workers: list[PreparingWorker] = []
```

- [ ] **Step 3: Modify _add_paths to launch PreparingWorker**

Replace the `_add_paths` method (lines 284-298):

```python
    def _add_paths(self, paths: list[str]) -> None:
        db = self._db
        added = 0
        new_items: list[tuple[int, str]] = []
        for fp in paths:
            try:
                before = len(db.get_documents())
                doc_id = db.add_document(fp)
                after = len(db.get_documents())
                if after > before:
                    added += 1
                    db.update_document_status(doc_id, "preparing")
                    new_items.append((doc_id, fp))
            except Exception:
                pass
        self._load_documents()
        if new_items:
            worker = PreparingWorker(new_items)
            worker.doc_prepared.connect(self._on_doc_prepared)
            worker.doc_error.connect(self._on_prepare_error)
            worker.finished.connect(
                lambda w=worker: self._cleanup_preparing_worker(w)
            )
            self._preparing_workers.append(worker)
            worker.start()
            Toast(self, f"已导入 {added} 个文档，正在后台预处理...")
        elif added > 0:
            Toast(self, f"已导入 {added} 个文档")
```

- [ ] **Step 4: Add signal handler methods**

Add three new methods to `SplitterView` (after `_cancel_split` method, around line 418):

```python
    def _on_doc_prepared(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "pending")
        self._table.update_row_status(doc_id, "pending")

    def _on_prepare_error(self, doc_id: int, error: str) -> None:
        self._db.update_document_status(doc_id, "failed", error=error)
        self._table.update_row_status(doc_id, "failed")
        Toast(self, f"预处理失败: {error}")

    def _cleanup_preparing_worker(self, worker: PreparingWorker) -> None:
        try:
            self._preparing_workers.remove(worker)
        except ValueError:
            pass
```

- [ ] **Step 5: Update closeEvent**

Replace `closeEvent` (lines 486-492):

```python
    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.wait(3000)
        for w in self._preparing_workers:
            if w.isRunning():
                w.wait(3000)
        super().closeEvent(event)
```

- [ ] **Step 6: Run existing tests to verify no regression**

```bash
pytest tests/test_splitter.py tests/test_splitter_progress.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/tuv_tools/ui/views/splitter_view.py
git commit -m "feat(preparing): launch PreparingWorker on document import"
```

---

### Task 6: Final verification

- [ ] **Step 1: Install all dependencies**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 3: Verify clean git status**

```bash
git status
```
