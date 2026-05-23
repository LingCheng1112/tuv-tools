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
