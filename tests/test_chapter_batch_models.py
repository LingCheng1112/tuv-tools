"""测试 Chapter 批量导入工作台领域模型。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.core.chapter_batch.models import (
    BatchImportClause,
    BatchImportDocument,
    ClauseStatus,
    DocumentStatus,
    SplitMode,
    is_document_executable,
)


class TestSplitMode:
    def test_labels_are_business_friendly(self):
        assert SplitMode.SECTION.value == "章节"
        assert SplitMode.CLAUSE.value == "条款"


class TestDocumentStatus:
    def test_contains_workspace_states(self):
        assert DocumentStatus.PENDING_CONFIRM.value == "待确认"
        assert DocumentStatus.PENDING_CREATE.value == "待创建"
        assert DocumentStatus.PARTIAL.value == "部分完成"
        assert DocumentStatus.PENDING_UPLOAD.value == "待上传"

    def test_executable_states_match_agreed_policy(self):
        assert is_document_executable(DocumentStatus.PENDING_CREATE.value) is True
        assert is_document_executable(DocumentStatus.PENDING_UPLOAD.value) is True
        assert is_document_executable(DocumentStatus.PARTIAL.value) is True
        assert is_document_executable(DocumentStatus.FAILED.value) is True
        assert is_document_executable(DocumentStatus.PENDING_CONFIRM.value) is False
        assert is_document_executable(DocumentStatus.CREATING.value) is False
        assert is_document_executable(DocumentStatus.UPLOADING.value) is False
        assert is_document_executable(DocumentStatus.COMPLETED.value) is False
        assert is_document_executable(DocumentStatus.SKIPPED.value) is False


class TestClauseStatus:
    def test_contains_retryable_states(self):
        assert ClauseStatus.CREATE_FAILED.value == "创建失败"
        assert ClauseStatus.PENDING_UPLOAD.value == "待上传"
        assert ClauseStatus.UPLOAD_FAILED.value == "上传失败"
        assert ClauseStatus.SKIPPED.value == "用户跳过"


class TestBatchImportDocument:
    def test_defaults_match_workspace_spec(self):
        doc = BatchImportDocument(file_path="C:/a.docx", file_name="a.docx")

        assert doc.document_status == DocumentStatus.PENDING_SPLIT.value
        assert doc.split_mode == SplitMode.CLAUSE.value
        assert doc.plan_sr == "1"
        assert doc.chapter_version == "1.0"
        assert doc.is_queued is False
        assert doc.total_clause_count == 0


class TestBatchImportClause:
    def test_defaults_match_workspace_spec(self):
        clause = BatchImportClause(term="10.1", source_docx_path="C:/10_1.docx")

        assert clause.clause_status == ClauseStatus.PENDING_CREATE.value
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
