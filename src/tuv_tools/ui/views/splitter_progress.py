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
