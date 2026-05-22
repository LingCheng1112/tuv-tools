# 文档拆分进度优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DOCX 批量拆分增加可解释的阶段进度、可及时响应的取消逻辑，以及取消/失败时不破坏上一次成功输出的文档级 partial 导出机制。

**Architecture:** splitter core 只暴露 `CoreProgressEvent`、取消检查和 partial 导出语义；`SplitWorker` 把 core 事件映射为 UI 批次进度事件；`SplitterView` 主线程负责表格、进度条、Toast 和 SQLite 状态更新。导出先写 `<output_root>/<base_name>.partial-<doc_id>/`，成功后再提升为正式 `<output_root>/<base_name>/`。

**Tech Stack:** Python 3.10+, PySide6, pytest, python-docx ZIP/XML 处理路径沿用当前 `zipfile` + `ElementTree`

---

## File Map

| 文件 | 职责 |
| --- | --- |
| `src/tuv_tools/core/splitter/models.py` | 增加 `CoreProgressEvent`、`SplitProgressEvent`、`SplitCancelled` 和 callback 类型 |
| `src/tuv_tools/core/splitter/parsing.py` | 给 DOCX 读取、块扫描、表格切片、去重增加可选进度和取消检查 |
| `src/tuv_tools/core/splitter/exporting.py` | 给条款/版本导出增加进度、取消检查、partial 目录清理和成功提升 |
| `src/tuv_tools/core/splitter/__init__.py` | 导出新增事件模型和取消异常 |
| `src/tuv_tools/ui/views/splitter_progress.py` | 新增纯 Python 的进度百分比映射和节流 helper，避免 UI 测试依赖 pytest-qt |
| `src/tuv_tools/ui/views/splitter_view.py` | 扩展 `SplitWorker` 信号、取消语义、底部进度 UI 和 Toast 统计 |
| `src/tuv_tools/ui/widgets/document_list.py` | 支持 `cancelled` 展示，并在 `section_count=None` 时保留旧条款数 |
| `src/tuv_tools/config/database.py` | 让 `processing`/`pending` 状态更新不清空上一次成功的条款数和完成时间 |
| `tests/test_splitter.py` | 增加 core 解析、导出、partial、取消测试 |
| `tests/test_splitter_progress.py` | 新增进度映射和节流 helper 测试 |
| `tests/test_database.py` | 增加取消恢复 pending 不破坏上次成功结果的状态测试 |

---

## Task 1: Core Progress Contract

**Files:**
- Modify: `src/tuv_tools/core/splitter/models.py`
- Modify: `src/tuv_tools/core/splitter/__init__.py`
- Create: `tests/test_splitter_progress.py`

- [ ] **Step 1: 写失败测试，锁定事件模型和进度映射**

Create `tests/test_splitter_progress.py`:

```python
"""测试文档拆分进度映射和节流 helper"""

from tuv_tools.core.splitter.models import CoreProgressEvent, SplitCancelled
from tuv_tools.ui.views.splitter_progress import ProgressThrottler, SplitProgressMapper


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TestProgressContracts:
    def test_core_progress_event_fields(self):
        event = CoreProgressEvent(
            phase="reading",
            phase_label="读取文档",
            current=1,
            total=1,
            message="读取 word/document.xml",
        )

        assert event.phase == "reading"
        assert event.phase_label == "读取文档"
        assert event.current == 1
        assert event.total == 1
        assert event.message == "读取 word/document.xml"

    def test_split_cancelled_is_exception(self):
        assert issubclass(SplitCancelled, Exception)


class TestSplitProgressMapper:
    def test_maps_first_document_phase_to_bounded_percent(self):
        mapper = SplitProgressMapper(doc_id=7, file_name="sample.docx", doc_index=1, doc_total=4)
        ui_event = mapper.to_ui_event(CoreProgressEvent(
            phase="exporting_clauses",
            phase_label="导出条款文件",
            current=5,
            total=10,
            message="导出条款文件 5/10",
        ))

        assert ui_event.doc_id == 7
        assert ui_event.file_name == "sample.docx"
        assert ui_event.doc_index == 1
        assert ui_event.doc_total == 4
        assert ui_event.phase == "exporting_clauses"
        assert ui_event.phase_current == 5
        assert ui_event.phase_total == 10
        assert 0 <= ui_event.overall_percent <= 100

    def test_completed_later_document_never_exceeds_100(self):
        mapper = SplitProgressMapper(doc_id=8, file_name="last.docx", doc_index=4, doc_total=4)
        ui_event = mapper.to_ui_event(CoreProgressEvent(
            phase="completed",
            phase_label="完成",
            current=1,
            total=1,
            message="当前文档完成",
        ))

        assert ui_event.overall_percent == 100


class TestProgressThrottler:
    def test_phase_change_is_emitted_immediately(self):
        clock = FakeClock()
        throttler = ProgressThrottler(clock=clock, min_interval_seconds=0.2, min_step=10)

        first = CoreProgressEvent("reading", "读取文档", 1, 1, "读取文档")
        second = CoreProgressEvent("parsing_blocks", "解析内容块", 1, 100, "解析内容块 1/100")

        assert throttler.should_emit(first) is True
        assert throttler.should_emit(second) is True

    def test_high_frequency_same_phase_is_throttled(self):
        clock = FakeClock()
        throttler = ProgressThrottler(clock=clock, min_interval_seconds=0.2, min_step=10)

        assert throttler.should_emit(CoreProgressEvent("parsing_blocks", "解析内容块", 1, 100, "1/100"))
        assert throttler.should_emit(CoreProgressEvent("parsing_blocks", "解析内容块", 2, 100, "2/100")) is False

    def test_interval_or_completion_forces_emit(self):
        clock = FakeClock()
        throttler = ProgressThrottler(clock=clock, min_interval_seconds=0.2, min_step=10)

        assert throttler.should_emit(CoreProgressEvent("parsing_blocks", "解析内容块", 1, 100, "1/100"))
        clock.advance(0.21)
        assert throttler.should_emit(CoreProgressEvent("parsing_blocks", "解析内容块", 2, 100, "2/100")) is True
        assert throttler.should_emit(CoreProgressEvent("parsing_blocks", "解析内容块", 100, 100, "100/100")) is True
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/test_splitter_progress.py -v`

Expected: FAIL，错误包含 `cannot import name 'CoreProgressEvent'` 或 `No module named 'tuv_tools.ui.views.splitter_progress'`。

- [ ] **Step 3: 实现 core 事件模型**

Modify `src/tuv_tools/core/splitter/models.py` by adding these imports and classes after the existing imports:

```python
from typing import Callable
```

Add after `ClauseMatch`:

```python
@dataclass(frozen=True)
class CoreProgressEvent:
    """splitter core 内部的阶段进度事件，不包含 UI 批次概念。"""
    phase: str
    phase_label: str
    current: int
    total: int
    message: str


@dataclass(frozen=True)
class SplitProgressEvent:
    """UI 使用的批次进度事件，由 SplitWorker 从 CoreProgressEvent 映射而来。"""
    doc_id: int
    file_name: str
    doc_index: int
    doc_total: int
    phase: str
    phase_label: str
    phase_current: int
    phase_total: int
    overall_percent: int
    message: str


class SplitCancelled(Exception):
    """用户取消文档拆分。"""


CoreProgressCallback = Callable[[CoreProgressEvent], None]
CancelCallback = Callable[[], bool]
```

- [ ] **Step 4: 实现 UI 纯 helper**

Create `src/tuv_tools/ui/views/splitter_progress.py`:

```python
"""文档拆分 UI 进度映射 helper。"""

from __future__ import annotations

import time
from collections.abc import Callable

from tuv_tools.core.splitter.models import CoreProgressEvent, SplitProgressEvent


PHASE_WEIGHTS: dict[str, int] = {
    "validating": 5,
    "reading": 5,
    "parsing_blocks": 20,
    "splitting_tables": 15,
    "deduplicating": 5,
    "exporting_clauses": 35,
    "exporting_versions": 15,
    "completed": 0,
    "failed": 0,
    "cancelled": 0,
}


class SplitProgressMapper:
    """把单文档 core 进度映射为批次整体百分比。"""

    def __init__(self, doc_id: int, file_name: str, doc_index: int, doc_total: int):
        self._doc_id = doc_id
        self._file_name = file_name
        self._doc_index = doc_index
        self._doc_total = max(doc_total, 1)

    def to_ui_event(self, event: CoreProgressEvent) -> SplitProgressEvent:
        completed_doc_fraction = max(self._doc_index - 1, 0) / self._doc_total
        current_doc_fraction = self._phase_fraction(event) / self._doc_total
        percent = int(round((completed_doc_fraction + current_doc_fraction) * 100))
        if event.phase == "completed":
            percent = int(round((self._doc_index / self._doc_total) * 100))
        percent = min(max(percent, 0), 100)

        return SplitProgressEvent(
            doc_id=self._doc_id,
            file_name=self._file_name,
            doc_index=self._doc_index,
            doc_total=self._doc_total,
            phase=event.phase,
            phase_label=event.phase_label,
            phase_current=event.current,
            phase_total=event.total,
            overall_percent=percent,
            message=event.message,
        )

    def _phase_fraction(self, event: CoreProgressEvent) -> float:
        prior_weight = 0
        for phase, weight in PHASE_WEIGHTS.items():
            if phase == event.phase:
                break
            prior_weight += weight

        weight = PHASE_WEIGHTS.get(event.phase, 0)
        if event.total <= 0:
            current_ratio = 0.0
        else:
            current_ratio = min(max(event.current / event.total, 0.0), 1.0)
        return (prior_weight + weight * current_ratio) / 100


class ProgressThrottler:
    """限制高频进度事件，阶段切换和完成事件始终放行。"""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        min_interval_seconds: float = 0.15,
        min_step: int = 20,
    ):
        self._clock = clock
        self._min_interval_seconds = min_interval_seconds
        self._min_step = min_step
        self._last_phase: str | None = None
        self._last_current = 0
        self._last_emit_at = 0.0

    def should_emit(self, event: CoreProgressEvent) -> bool:
        now = self._clock()
        phase_changed = event.phase != self._last_phase
        phase_complete = event.total > 0 and event.current >= event.total
        enough_time = now - self._last_emit_at >= self._min_interval_seconds
        enough_step = abs(event.current - self._last_current) >= self._min_step

        if phase_changed or phase_complete or enough_time or enough_step:
            self._last_phase = event.phase
            self._last_current = event.current
            self._last_emit_at = now
            return True
        return False
```

- [ ] **Step 5: 导出新增符号**

Modify `src/tuv_tools/core/splitter/__init__.py`:

```python
"""DOCX 测试模板拆分模块"""

from .exporting import export_docx_outputs
from .models import CoreProgressEvent, SplitCancelled, SplitProgressEvent
from .parsing import build_sections
from .utils import CleanPatterns

__all__ = [
    "build_sections",
    "export_docx_outputs",
    "CleanPatterns",
    "CoreProgressEvent",
    "SplitProgressEvent",
    "SplitCancelled",
]
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_splitter_progress.py -v`

Expected: PASS。

- [ ] **Step 7: Commit**

Commit only these files with a Lore-style message:

```powershell
git add src/tuv_tools/core/splitter/models.py src/tuv_tools/core/splitter/__init__.py src/tuv_tools/ui/views/splitter_progress.py tests/test_splitter_progress.py
git commit -m "feat(splitter): 定义拆分进度事件模型"
```

---

## Task 2: Parser Progress And Cancellation

**Files:**
- Modify: `src/tuv_tools/core/splitter/parsing.py`
- Modify: `tests/test_splitter.py`

- [ ] **Step 1: 写解析进度和取消测试**

Add imports in `tests/test_splitter.py`:

```python
from tuv_tools.core.splitter.models import CoreProgressEvent, SplitCancelled
```

Add tests under `class TestBuildSections`:

```python
    def test_emits_progress_events(self):
        events: list[CoreProgressEvent] = []

        sections = build_sections(FIXTURE, progress=events.append)

        assert sections
        phases = [event.phase for event in events]
        assert "reading" in phases
        assert "parsing_blocks" in phases
        assert "deduplicating" in phases
        assert all(event.current >= 0 for event in events)
        assert all(event.total >= 0 for event in events)

    def test_progress_callback_error_does_not_break_parsing(self):
        def broken_progress(_event: CoreProgressEvent) -> None:
            raise RuntimeError("ui callback failed")

        sections = build_sections(FIXTURE, progress=broken_progress)

        assert sections

    def test_cancel_during_build_sections_raises_split_cancelled(self):
        def should_cancel() -> bool:
            return True

        with pytest.raises(SplitCancelled):
            build_sections(FIXTURE, should_cancel=should_cancel)
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/test_splitter.py::TestBuildSections -v`

Expected: FAIL，错误说明 `build_sections()` 不接受 `progress` 或 `should_cancel`。

- [ ] **Step 3: 给 parsing.py 增加安全回调 helper**

Modify imports in `src/tuv_tools/core/splitter/parsing.py`:

```python
from .models import (
    Block,
    CancelCallback,
    ClauseMatch,
    CoreProgressCallback,
    CoreProgressEvent,
    Section,
    SplitCancelled,
    TableSlice,
)
```

Add helper functions near the top:

```python
def _emit_progress(
    progress: CoreProgressCallback | None,
    phase: str,
    phase_label: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress is None:
        return
    try:
        progress(CoreProgressEvent(phase, phase_label, current, total, message))
    except Exception:
        return


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise SplitCancelled("Document split cancelled")
```

- [ ] **Step 4: 扩展 parse_document 签名并加入读取/块扫描进度**

Change signature:

```python
def parse_document(
    docx_path: Path,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[Block]:
```

Add checks and events:

```python
    _check_cancel(should_cancel)
    _emit_progress(progress, "reading", "读取文档", 0, 1, f"读取 {docx_path.name}")
    try:
        with zipfile.ZipFile(docx_path) as archive:
            _check_cancel(should_cancel)
            if "word/document.xml" not in archive.namelist():
                raise ValueError(f"Invalid DOCX: missing word/document.xml in {docx_path.name}")
            root = ET.fromstring(archive.read("word/document.xml"))
            _emit_progress(progress, "reading", "读取文档", 1, 1, "已读取 word/document.xml")
```

Before iterating body blocks:

```python
    body_blocks = list(iter_body_blocks(body))
    total_blocks = len(body_blocks)
    for block_index, element in enumerate(body_blocks, 1):
        _check_cancel(should_cancel)
        _emit_progress(
            progress,
            "parsing_blocks",
            "解析内容块",
            block_index,
            total_blocks,
            f"解析内容块 {block_index}/{total_blocks}",
        )
```

- [ ] **Step 5: 扩展表格切片函数取消检查**

Change `_split_table_into_sections` signature:

```python
def _split_table_into_sections(
    block: Block,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[tuple[ClauseMatch, TableSlice]]:
```

Inside the row loop:

```python
    total_rows = len(rows)
    for idx, row in enumerate(rows):
        _check_cancel(should_cancel)
        _emit_progress(
            progress,
            "splitting_tables",
            "拆分表格",
            idx + 1,
            total_rows,
            f"解析表格行 {idx + 1}/{total_rows}",
        )
```

- [ ] **Step 6: 扩展 build_sections 签名并串接回调**

Change signature:

```python
def build_sections(
    docx_path: Path,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[Section]:
```

Change the first line:

```python
    blocks = parse_document(docx_path, progress=progress, should_cancel=should_cancel)
```

Inside the main block loop, before branch handling:

```python
        _check_cancel(should_cancel)
```

Change table slicing call:

```python
        table_sections = _split_table_into_sections(
            block,
            progress=progress,
            should_cancel=should_cancel,
        )
```

Before final filtering:

```python
    _emit_progress(
        progress,
        "deduplicating",
        "整理条款",
        0,
        1,
        "整理条款并移除重复结果",
    )
    sections = [s for s in sections if s.major_version != "1"]
    result = _deduplicate_sections(sections)
    _emit_progress(progress, "deduplicating", "整理条款", 1, 1, f"识别到 {len(result)} 个条款")
    return result
```

- [ ] **Step 7: 运行解析相关测试**

Run: `pytest tests/test_splitter.py::TestParseDocument tests/test_splitter.py::TestBuildSections -v`

Expected: PASS。

- [ ] **Step 8: Commit**

```powershell
git add src/tuv_tools/core/splitter/parsing.py tests/test_splitter.py
git commit -m "feat(splitter): 增加解析进度和取消检查"
```

---

## Task 3: Export Progress And Partial Output Promotion

**Files:**
- Modify: `src/tuv_tools/core/splitter/exporting.py`
- Modify: `tests/test_splitter.py`

- [ ] **Step 1: 写导出进度、取消和 partial 测试**

Add imports in `tests/test_splitter.py`:

```python
import shutil
from tuv_tools.core.splitter.models import SplitCancelled
```

Add tests under `class TestExportIntegration`:

```python
    def test_export_emits_clause_and_version_progress(self, tmp_path):
        events = []
        sections = build_sections(FIXTURE)

        export_docx_outputs(FIXTURE, sections, tmp_path / "output", [], progress=events.append)

        phases = [event.phase for event in events]
        assert "exporting_clauses" in phases
        assert "exporting_versions" in phases
        assert phases[-1] == "completed"

    def test_export_callback_error_does_not_break_export(self, tmp_path):
        sections = build_sections(FIXTURE)

        def broken_progress(_event):
            raise RuntimeError("ui callback failed")

        export_docx_outputs(FIXTURE, sections, tmp_path / "output", [], progress=broken_progress)

        assert any((tmp_path / "output").rglob("*.docx"))

    def test_export_cancel_cleans_partial_and_keeps_previous_output(self, tmp_path):
        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        base_name = safe_name(extract_standard_number(FIXTURE.stem) or FIXTURE.stem)
        final_dir = output_root / base_name
        partial_dir = output_root / f"{base_name}.partial-42"

        export_docx_outputs(FIXTURE, sections[:1], output_root, [])
        marker = final_dir / "marker.txt"
        marker.write_text("previous output", encoding="utf-8")

        def should_cancel() -> bool:
            return True

        with pytest.raises(SplitCancelled):
            export_docx_outputs(
                FIXTURE,
                sections,
                output_root,
                [],
                should_cancel=should_cancel,
                staging_root=partial_dir,
            )

        assert marker.read_text(encoding="utf-8") == "previous output"
        assert not partial_dir.exists()

    def test_export_success_promotes_partial_directory(self, tmp_path):
        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        base_name = safe_name(extract_standard_number(FIXTURE.stem) or FIXTURE.stem)
        final_dir = output_root / base_name
        partial_dir = output_root / f"{base_name}.partial-99"

        export_docx_outputs(
            FIXTURE,
            sections[:2],
            output_root,
            [],
            staging_root=partial_dir,
        )

        assert final_dir.exists()
        assert not partial_dir.exists()
        assert any((final_dir / "clauses_docx").glob("*.docx"))
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/test_splitter.py::TestExportIntegration -v`

Expected: FAIL，错误说明 `export_docx_outputs()` 不接受 `progress`、`should_cancel` 或 `staging_root`。

- [ ] **Step 3: 增加 exporting.py helper 和 imports**

Modify imports:

```python
import os
import shutil
```

Modify model imports:

```python
from .models import CancelCallback, CoreProgressCallback, CoreProgressEvent, Section, SplitCancelled, TableSlice
```

Add helpers after imports:

```python
def _emit_progress(
    progress: CoreProgressCallback | None,
    phase: str,
    phase_label: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress is None:
        return
    try:
        progress(CoreProgressEvent(phase, phase_label, current, total, message))
    except Exception:
        return


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise SplitCancelled("Document split cancelled")
```

- [ ] **Step 4: 公开输出基础目录名 helper**

Replace `_get_output_base_dir_name` with:

```python
def get_output_base_dir_name(docx_path: Path) -> str:
    standard_number = extract_standard_number(docx_path.stem)
    return safe_name(standard_number or docx_path.stem)


def _get_output_base_dir_name(docx_path: Path) -> str:
    return get_output_base_dir_name(docx_path)
```

- [ ] **Step 5: 给单个 DOCX 写入增加取消检查**

Change `_write_docx_from_template` signature:

```python
def _write_docx_from_template(
    template_docx: Path,
    output_docx: Path,
    sections: list[Section],
    inline_clean_patterns: CleanPatterns,
    collapse_shared_tables: bool = False,
    should_cancel: CancelCallback | None = None,
) -> None:
```

Add checks before expensive steps and inside ZIP copy loop:

```python
    _check_cancel(should_cancel)
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    if collapse_shared_tables:
        sections = _collapse_sections_for_version(sections)
    _check_cancel(should_cancel)
    document_xml = _build_document_xml(sections, inline_clean_patterns)
    with zipfile.ZipFile(template_docx, "r") as src, \
         zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            _check_cancel(should_cancel)
            if item.filename == "word/document.xml":
                dst.writestr(item, document_xml)
            else:
                dst.writestr(item, src.read(item.filename))
```

- [ ] **Step 6: 增加 partial 提升 helper**

Add near export function:

```python
def _promote_staging_directory(staging_dir: Path, final_dir: Path) -> None:
    backup_dir = final_dir.with_name(f"{final_dir.name}.previous-{os.getpid()}")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    moved_existing = False
    if final_dir.exists():
        final_dir.rename(backup_dir)
        moved_existing = True

    try:
        staging_dir.rename(final_dir)
    except OSError:
        if moved_existing and backup_dir.exists() and not final_dir.exists():
            backup_dir.rename(final_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
```

- [ ] **Step 7: 扩展 export_docx_outputs 签名和写入目录**

Change signature:

```python
def export_docx_outputs(
    docx_path: Path,
    sections: list[Section],
    output_root: Path,
    inline_clean_patterns: CleanPatterns,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    staging_root: Path | None = None,
) -> None:
```

At the beginning:

```python
    _check_cancel(should_cancel)
    final_base_dir = output_root / get_output_base_dir_name(docx_path)
    base_dir = staging_root if staging_root is not None else final_base_dir
    if staging_root is not None:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        staging_root.parent.mkdir(parents=True, exist_ok=True)
```

Wrap the existing export logic:

```python
    try:
        clause_docx_dir = base_dir / "clauses_docx"
        version_docx_dir = base_dir / "versions_docx"
        # existing duplicate-name setup stays here
        # clause loop and version loop emit progress events
        if staging_root is not None:
            _promote_staging_directory(staging_root, final_base_dir)
    except Exception:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise
```

In the clause loop, emit progress and pass cancellation:

```python
        total_clauses = len(sections)
        for index, section in enumerate(sections, 1):
            _check_cancel(should_cancel)
            _emit_progress(
                progress,
                "exporting_clauses",
                "导出条款文件",
                index,
                total_clauses,
                f"导出条款文件 {index}/{total_clauses}",
            )
            # existing export_stem code stays here
            _write_docx_from_template(
                docx_path,
                clause_docx_file,
                [section],
                inline_clean_patterns,
                should_cancel=should_cancel,
            )
```

In the version loop:

```python
        total_versions = len(grouped)
        for index, (major_version, group_sections) in enumerate(grouped.items(), 1):
            _check_cancel(should_cancel)
            _emit_progress(
                progress,
                "exporting_versions",
                "导出版本文件",
                index,
                total_versions,
                f"导出版本文件 {index}/{total_versions}",
            )
            _write_docx_from_template(
                docx_path,
                version_docx_file,
                group_sections,
                inline_clean_patterns,
                collapse_shared_tables=True,
                should_cancel=should_cancel,
            )
```

At the end:

```python
    _emit_progress(progress, "completed", "完成", 1, 1, "当前文档导出完成")
```

- [ ] **Step 8: 运行导出相关测试**

Run: `pytest tests/test_splitter.py::TestExportIntegration -v`

Expected: PASS。

- [ ] **Step 9: Commit**

```powershell
git add src/tuv_tools/core/splitter/exporting.py tests/test_splitter.py
git commit -m "feat(splitter): 使用 partial 目录保护导出结果"
```

---

## Task 4: Worker Signals And Progress UI

**Files:**
- Modify: `src/tuv_tools/ui/views/splitter_view.py`
- Modify: `tests/test_splitter_progress.py`

- [ ] **Step 1: 写 worker/UI helper 测试**

Add to `tests/test_splitter_progress.py`:

```python
from tuv_tools.ui.views.splitter_view import build_split_summary


class TestSplitSummary:
    def test_success_summary(self):
        assert build_split_summary(success=3, failed=0, cancelled=False, total=3) == "拆分完成：成功 3 个，失败 0 个"

    def test_partial_failure_summary(self):
        assert build_split_summary(success=2, failed=1, cancelled=False, total=3) == "拆分完成：成功 2 个，失败 1 个"

    def test_all_failed_summary(self):
        assert build_split_summary(success=0, failed=3, cancelled=False, total=3) == "拆分失败：3 个文档未完成"

    def test_cancelled_summary(self):
        assert build_split_summary(success=1, failed=0, cancelled=True, total=4) == "已取消拆分：完成 1 个，剩余 3 个"
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/test_splitter_progress.py -v`

Expected: FAIL，错误说明 `build_split_summary` 不存在。

- [ ] **Step 3: 修改 SplitWorker 信号和 run 流程**

Modify imports in `src/tuv_tools/ui/views/splitter_view.py`:

```python
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget

from tuv_tools.core.splitter.exporting import get_output_base_dir_name
from tuv_tools.core.splitter.models import CoreProgressEvent, SplitCancelled
from tuv_tools.ui.views.splitter_progress import ProgressThrottler, SplitProgressMapper
```

Add summary helper near `resolve_output_root`:

```python
def build_split_summary(success: int, failed: int, cancelled: bool, total: int) -> str:
    if cancelled:
        remaining = max(total - success - failed, 0)
        return f"已取消拆分：完成 {success} 个，剩余 {remaining} 个"
    if success == 0 and failed > 0:
        return f"拆分失败：{failed} 个文档未完成"
    return f"拆分完成：成功 {success} 个，失败 {failed} 个"
```

Change `SplitWorker` signals:

```python
    doc_started = Signal(int)
    progress_detail = Signal(object)
    doc_done = Signal(int, str, int)
    doc_error = Signal(int, str)
    doc_cancelled = Signal(int)
    batch_cancelled = Signal()
```

Change `run()` structure:

```python
    def run(self):
        total = len(self._items)
        for idx, (doc_id, file_path, output_subdir) in enumerate(self._items, 1):
            if self._cancelled:
                self.batch_cancelled.emit()
                break

            docx_path = Path(file_path)
            self.doc_started.emit(doc_id)
            mapper = SplitProgressMapper(doc_id, docx_path.name, idx, total)
            throttler = ProgressThrottler()

            def should_cancel() -> bool:
                return self._cancelled

            def on_core_progress(event: CoreProgressEvent) -> None:
                if self._cancelled:
                    raise SplitCancelled("Document split cancelled")
                if throttler.should_emit(event):
                    self.progress_detail.emit(mapper.to_ui_event(event))

            try:
                on_core_progress(CoreProgressEvent("validating", "校验文件", 0, 1, f"校验 {docx_path.name}"))
                if not docx_path.exists():
                    self.doc_error.emit(doc_id, f"文件不存在: {file_path}")
                    continue
                on_core_progress(CoreProgressEvent("validating", "校验文件", 1, 1, "文件存在"))
                sections = build_sections(docx_path, progress=on_core_progress, should_cancel=should_cancel)
                if sections:
                    output_path = resolve_output_root(docx_path, self._output_root, output_subdir)
                    base_name = get_output_base_dir_name(docx_path)
                    staging_root = output_path / f"{base_name}.partial-{doc_id}"
                    export_docx_outputs(
                        docx_path,
                        sections,
                        output_path,
                        self._patterns,
                        progress=on_core_progress,
                        should_cancel=should_cancel,
                        staging_root=staging_root,
                    )
                self.doc_done.emit(doc_id, "completed", len(sections))
            except SplitCancelled:
                self.doc_cancelled.emit(doc_id)
                self.batch_cancelled.emit()
                break
            except Exception as exc:
                self.doc_error.emit(doc_id, str(exc))
```

- [ ] **Step 4: 扩展进度 UI 控件**

In `_setup_ui`, before the existing `QProgressBar`, add two labels:

```python
        self._progress_title = QLabel("")
        self._progress_title.setVisible(False)
        self._progress_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._progress_detail = QLabel("")
        self._progress_detail.setVisible(False)
        self._progress_detail.setStyleSheet("color: #999; font-size: 12px;")
        layout.addWidget(self._progress_title)
        layout.addWidget(self._progress_detail)
```

Change progress bar setup at batch start:

```python
        self._progress_title.setVisible(True)
        self._progress_title.setText("准备拆分文档...")
        self._progress_detail.setVisible(True)
        self._progress_detail.setText("")
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("取消")
        self._split_btn.setEnabled(False)
        self._split_success = 0
        self._split_failed = 0
        self._split_cancelled = False
        self._split_total = len(items)
```

Connect new signals:

```python
        self._worker.doc_started.connect(self._on_doc_started)
        self._worker.progress_detail.connect(self._on_progress_detail)
        self._worker.doc_done.connect(self._on_doc_done)
        self._worker.doc_error.connect(self._on_doc_error)
        self._worker.doc_cancelled.connect(self._on_doc_cancelled)
        self._worker.batch_cancelled.connect(self._on_batch_cancelled)
        self._worker.finished.connect(self._on_all_done)
```

- [ ] **Step 5: 添加 UI slots**

Add methods to `SplitterView`:

```python
    def _on_doc_started(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "processing")
        self._table.update_row_status(doc_id, "processing")

    def _on_progress_detail(self, event) -> None:
        title = f"第 {event.doc_index}/{event.doc_total} 个文档 | {event.file_name}"
        self._progress_title.setText(title)
        self._progress_title.setToolTip(event.file_name)
        self._progress_detail.setText(event.message)
        self._progress.setValue(event.overall_percent)
```

Update existing slots:

```python
    def _on_doc_done(self, doc_id: int, status: str, section_count: int) -> None:
        self._split_success += 1
        self._db.update_document_status(doc_id, status, section_count)
        self._table.update_row_status(doc_id, status, section_count)

    def _on_doc_error(self, doc_id: int, error: str) -> None:
        self._split_failed += 1
        self._db.update_document_status(doc_id, "failed", error=error)
        self._table.update_row_status(doc_id, "failed")

    def _on_doc_cancelled(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "pending")
        self._table.update_row_status(doc_id, "cancelled")

    def _on_batch_cancelled(self) -> None:
        self._split_cancelled = True
```

Update `_on_all_done`:

```python
    def _on_all_done(self) -> None:
        self._progress_title.setVisible(False)
        self._progress_detail.setVisible(False)
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._split_btn.setEnabled(True)
        self._load_documents()
        Toast(self, build_split_summary(
            success=self._split_success,
            failed=self._split_failed,
            cancelled=self._split_cancelled,
            total=self._split_total,
        ))
```

Update `_cancel_split`:

```python
    def _cancel_split(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setText("正在取消...")
            self._progress_detail.setText("正在取消，等待当前安全检查点...")
```

- [ ] **Step 6: 运行 helper 测试**

Run: `pytest tests/test_splitter_progress.py -v`

Expected: PASS。

- [ ] **Step 7: Commit**

```powershell
git add src/tuv_tools/ui/views/splitter_view.py tests/test_splitter_progress.py
git commit -m "feat(splitter): 展示批次阶段进度"
```

---

## Task 5: Status Persistence And Table Semantics

**Files:**
- Modify: `src/tuv_tools/config/database.py`
- Modify: `src/tuv_tools/ui/widgets/document_list.py`
- Modify: `tests/test_database.py`
- Modify: `tests/test_splitter.py`

- [ ] **Step 1: 写数据库状态语义测试**

Add to `tests/test_database.py` under the document-related test class:

```python
    def test_processing_status_preserves_previous_success_result(self, db):
        doc_id = db.add_document(str(Path(__file__).resolve()))
        db.update_document_status(doc_id, "completed", section_count=12)
        completed = db.get_document(doc_id)

        db.update_document_status(doc_id, "processing")
        processing = db.get_document(doc_id)

        assert processing["status"] == "processing"
        assert processing["last_section_count"] == 12
        assert processing["last_split_at"] == completed["last_split_at"]

    def test_pending_status_after_cancel_preserves_previous_success_result_and_clears_error(self, db):
        doc_id = db.add_document(str(Path(__file__).resolve()))
        db.update_document_status(doc_id, "completed", section_count=9)
        completed = db.get_document(doc_id)
        db.update_document_status(doc_id, "failed", error="old error")

        db.update_document_status(doc_id, "pending")
        pending = db.get_document(doc_id)

        assert pending["status"] == "pending"
        assert pending["last_section_count"] == 9
        assert pending["last_split_at"] == completed["last_split_at"]
        assert pending["error_message"] is None
```

- [ ] **Step 2: 写表格 helper 测试**

Add to `class TestSplitterUiHelpers` in `tests/test_splitter.py`:

```python
    def test_document_table_cancelled_status_label_exists(self):
        from tuv_tools.ui.widgets.document_list import STATUS_LABELS

        assert STATUS_LABELS["cancelled"]
```

- [ ] **Step 3: 运行失败测试**

Run: `pytest tests/test_database.py tests/test_splitter.py::TestSplitterUiHelpers -v`

Expected: FAIL，数据库会清空上一次成功字段，`cancelled` label 不存在。

- [ ] **Step 4: 修改数据库状态更新语义**

Modify `DatabaseManager.update_document_status()`:

```python
    def update_document_status(
        self, doc_id: int, status: str,
        section_count: int | None = None,
        error: str | None = None,
    ) -> None:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if status in {"processing", "pending"} and section_count is None:
            self._conn.execute(
                """UPDATE imported_documents
                   SET status = ?, error_message = ?, updated_at = ?
                   WHERE id = ?""",
                (status, error, now, doc_id),
            )
        else:
            self._conn.execute(
                """UPDATE imported_documents
                   SET status = ?, last_section_count = ?, last_split_at = ?,
                       error_message = ?, updated_at = ?
                   WHERE id = ?""",
                (status, section_count, now, error, now, doc_id),
            )
        self._conn.commit()
```

- [ ] **Step 5: 修改 DocumentTable 状态展示**

Add to `STATUS_LABELS`:

```python
    "cancelled": "已取消",
```

Change `update_row_status()` count update block:

```python
                if section_count is not None:
                    doc["last_section_count"] = section_count
                    count_text = str(section_count) if section_count else "-"
                    self.setItem(row, self.COL_COUNT, self._make_item(count_text))
                label = STATUS_LABELS.get(status, status)
                self.setItem(row, self.COL_STATUS, self._make_item(label, label))
                if section_count is None:
                    existing_count = doc.get("last_section_count")
                    count_text = str(existing_count) if existing_count else "-"
                    self.setItem(row, self.COL_COUNT, self._make_item(count_text))
```

- [ ] **Step 6: 运行状态相关测试**

Run: `pytest tests/test_database.py tests/test_splitter.py::TestSplitterUiHelpers -v`

Expected: PASS。

- [ ] **Step 7: Commit**

```powershell
git add src/tuv_tools/config/database.py src/tuv_tools/ui/widgets/document_list.py tests/test_database.py tests/test_splitter.py
git commit -m "fix(splitter): 取消时保留上次成功状态"
```

---

## Task 6: Full Regression And Manual Verification

**Files:**
- No required source changes unless verification finds a bug.

- [ ] **Step 1: 运行完整测试**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 2: 运行拆分集成测试的高信号子集**

Run:

```powershell
pytest tests/test_splitter.py::TestBuildSections tests/test_splitter.py::TestExportIntegration tests/test_splitter_progress.py -v
```

Expected: all tests pass.

- [ ] **Step 3: 手动启动应用做 UI smoke test**

Run: `python main.py`

Manual checklist:

1. 导入一个 DOCX 后点击“开始拆分选中”。
2. 底部显示当前文档序号、文件名、阶段详情和 0-100 百分比。
3. 当前文档表格状态先变为 `processing`，成功后变为 `completed`。
4. 点击取消后按钮文案变为“正在取消...”，Toast 显示 `已取消拆分：完成 N 个，剩余 M 个`。
5. 取消后当前文档数据库状态恢复 `pending`，上一次成功的条款数和完成时间不被清空。
6. 输出目录不存在 `<base_name>.partial-<doc_id>` 残留；正式 `<base_name>` 仍可打开。

- [ ] **Step 4: 检查 Git diff**

Run: `git --no-pager diff --stat`

Expected: only planned splitter/UI/database/test files changed.

- [ ] **Step 5: 最终 Commit**

Use a Lore-style commit message that records verification:

```powershell
git add src/tuv_tools/core/splitter src/tuv_tools/ui/views src/tuv_tools/ui/widgets src/tuv_tools/config tests
git commit -m "feat(splitter): 优化拆分进度和取消语义"
```

---

## Self-Review

Spec coverage:

| 规格要求 | 覆盖任务 |
| --- | --- |
| 批次整体 0-100 进度 | Task 1, Task 4 |
| 当前文件名、序号、阶段、计数可见 | Task 4 |
| 大文档解析和导出期间持续变化 | Task 2, Task 3 |
| 取消在解析块、表格行、ZIP entry、导出文件之间生效 | Task 2, Task 3, Task 4 |
| 不传回调时保持兼容 | Task 2, Task 3 regression tests |
| 取消不显示“拆分完成” | Task 4 |
| partial 目录保护上一次成功输出 | Task 3 |
| 高频事件节流，阶段切换不丢 | Task 1 |
| 进度回调异常不影响拆分 | Task 2, Task 3 |
| 不新增任务队列、历史页、断点续跑、pytest-qt | All tasks |

Placeholder scan:

No task relies on placeholders. Each code-changing step includes concrete signatures, helper bodies, or exact slot logic.

Type consistency:

`CoreProgressEvent` is created only in core and worker validation glue. `SplitProgressEvent` is created only by `SplitProgressMapper`. `SplitCancelled` is raised by core/export and caught by `SplitWorker`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-splitter-progress.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
