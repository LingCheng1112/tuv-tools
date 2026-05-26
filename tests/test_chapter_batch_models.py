"""测试 Chapter 批量导入工作台领域模型。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.core.chapter.models import ChapterStatus
from tuv_tools.core.chapter_batch.models import (
    BACKEND_NOT_DRAFT_REASON,
    BACKEND_STATUS_UNKNOWN_REASON,
    BatchImportClause,
    BatchImportDocument,
    CLAUSE_STATUS_UNKNOWN_REASON,
    ClauseStatus,
    DocumentStatus,
    SplitMode,
    get_clause_edit_state,
    is_document_executable,
    is_document_running,
)

UPLOAD_IN_PROGRESS = "上传中"
PREPARING = "预处理中"


class TestSplitMode:
    def test_labels_are_business_friendly(self):
        assert SplitMode.SECTION.value == "章节"
        assert SplitMode.CLAUSE.value == "条款"


class TestDocumentStatus:
    def test_exposes_exactly_upload_facing_document_states(self):
        assert {status.value for status in DocumentStatus} == {
            PREPARING,
            DocumentStatus.SPLITTING.value,
            DocumentStatus.PENDING_CONFIRM.value,
            DocumentStatus.PENDING_UPLOAD.value,
            UPLOAD_IN_PROGRESS,
            DocumentStatus.COMPLETED.value,
            DocumentStatus.PARTIAL.value,
            DocumentStatus.FAILED.value,
        }

    def test_executable_states_allow_pending_confirm_upload(self):
        assert is_document_executable(DocumentStatus.PENDING_CONFIRM.value) is True
        assert is_document_executable(DocumentStatus.PENDING_UPLOAD.value) is True
        assert is_document_executable(DocumentStatus.PARTIAL.value) is True
        assert is_document_executable(DocumentStatus.FAILED.value) is True
        assert is_document_executable(DocumentStatus.UPLOADING.value) is False
        assert is_document_executable(DocumentStatus.COMPLETED.value) is False

    def test_running_document_statuses_use_upload_as_only_explicit_execution_state(self):
        assert is_document_running(PREPARING) is True
        assert is_document_running(DocumentStatus.SPLITTING.value) is True
        assert is_document_running(DocumentStatus.UPLOADING.value) is True
        assert is_document_running(DocumentStatus.PENDING_CONFIRM.value) is False
        assert is_document_running(DocumentStatus.PENDING_UPLOAD.value) is False
        assert is_document_running(DocumentStatus.PARTIAL.value) is False


class TestClauseStatus:
    def test_exposes_exactly_four_stable_upload_facing_states(self):
        assert {status.value for status in ClauseStatus} == {
            ClauseStatus.PENDING_UPLOAD.value,
            UPLOAD_IN_PROGRESS,
            ClauseStatus.UPLOAD_SUCCESS.value,
            ClauseStatus.UPLOAD_FAILED.value,
        }


class TestBatchImportDocument:
    def test_defaults_match_workspace_spec(self):
        doc = BatchImportDocument(file_path="C:/a.docx", file_name="a.docx")

        assert doc.document_status == DocumentStatus.PREPARING.value
        assert doc.split_mode == SplitMode.CLAUSE.value
        assert doc.plan_sr == "1"
        assert doc.chapter_version == "1.0"
        assert doc.is_queued is False
        assert doc.total_clause_count == 0


class TestBatchImportClause:
    def test_defaults_match_upload_workspace_spec(self):
        clause = BatchImportClause(term="10.1", source_docx_path="C:/10_1.docx")

        assert clause.clause_status == ClauseStatus.PENDING_UPLOAD.value
        assert clause.term == "10.1"
        assert clause.source_docx_path == "C:/10_1.docx"
        assert clause.duplicate_flag is False
        assert clause.chapter_id is None

    def test_clause_can_hold_failure_and_duplicate_metadata(self):
        clause = BatchImportClause(
            term="10.2",
            test_content="Heating",
            clause_status=ClauseStatus.UPLOAD_FAILED.value,
            duplicate_flag=True,
            duplicate_reason="同一归属文件夹下 term + testContent 相同",
            upload_error="remote upload failed",
        )

        assert clause.clause_status == "上传失败"
        assert clause.duplicate_flag is True
        assert "term + testContent" in clause.duplicate_reason
        assert clause.upload_error == "remote upload failed"

    def test_clause_without_chapter_id_is_editable(self):
        assert get_clause_edit_state(
            clause_status=ClauseStatus.PENDING_UPLOAD.value,
            chapter_id=None,
            backend_chapter_status=None,
        ) == (True, "")
        assert get_clause_edit_state(
            clause_status=ClauseStatus.UPLOAD_FAILED.value,
            chapter_id=None,
            backend_chapter_status=int(ChapterStatus.VALID),
        ) == (True, "")

    def test_clause_with_draft_backend_status_is_editable(self):
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=123,
                backend_chapter_status=int(ChapterStatus.DRAFT),
            )
            == (True, "")
        )
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=456,
                backend_chapter_status=int(ChapterStatus.DRAFT),
            )
            == (True, "")
        )

    def test_clause_with_unknown_backend_status_is_readonly(self):
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=123,
                backend_chapter_status=None,
            )
            == (False, BACKEND_STATUS_UNKNOWN_REASON)
        )
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=123,
                backend_chapter_status=999,
            )
            == (False, BACKEND_STATUS_UNKNOWN_REASON)
        )

    def test_clause_with_non_draft_backend_status_is_readonly(self):
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=123,
                backend_chapter_status=int(ChapterStatus.VALID),
            )
            == (False, BACKEND_NOT_DRAFT_REASON)
        )
        assert (
            get_clause_edit_state(
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=456,
                backend_chapter_status=int(ChapterStatus.IN_REVIEW),
            )
            == (False, BACKEND_NOT_DRAFT_REASON)
        )

    def test_unknown_clause_status_is_readonly(self):
        assert (
            get_clause_edit_state(
                clause_status="未知状态",
                chapter_id=None,
                backend_chapter_status=None,
            )
            == (False, CLAUSE_STATUS_UNKNOWN_REASON)
        )
