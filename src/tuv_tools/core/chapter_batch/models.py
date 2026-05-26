"""Chapter 批量导入工作台领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tuv_tools.core.chapter.models import ChapterStatus


class SplitMode(StrEnum):
    """文档拆分模式。"""

    SECTION = "章节"
    CLAUSE = "条款"


class DocumentStatus(StrEnum):
    """工作台文档级状态。"""

    PREPARING = "预处理中"
    SPLITTING = "拆分中"
    PENDING_CONFIRM = "待确认"
    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    COMPLETED = "已完成"
    PARTIAL = "部分完成"
    FAILED = "失败"


class ClauseStatus(StrEnum):
    """工作台条款级状态。"""

    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    UPLOAD_SUCCESS = "上传成功"
    UPLOAD_FAILED = "上传失败"


@dataclass(frozen=True, slots=True)
class ChapterBatchProgressEvent:
    """工作台运行时进度事件，仅用于 UI 内存态展示。"""

    document_id: int
    phase: str
    percent: int
    message: str = ""
    current_index: int = 0
    total_count: int = 0
    current_clause_term: str = ""
    action: str = ""


KNOWN_CLAUSE_STATUSES = {status.value for status in ClauseStatus}
KNOWN_BACKEND_CHAPTER_STATUSES = {int(status) for status in ChapterStatus}

CLAUSE_STATUS_UNKNOWN_REASON = "条款状态未知，禁止编辑"
BACKEND_STATUS_UNKNOWN_REASON = "后端状态未知，禁止编辑"
BACKEND_NOT_DRAFT_REASON = "后端非草稿，禁止编辑"

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


def is_document_executable(status: str) -> bool:
    """判断文档是否允许进入执行队列。"""
    return status in EXECUTABLE_DOCUMENT_STATUSES


def is_document_running(status: str) -> bool:
    """判断文档是否处于执行中状态。"""
    return status in RUNNING_DOCUMENT_STATUSES


def get_clause_edit_state(
    *,
    clause_status: str,
    chapter_id: int | None,
    backend_chapter_status: int | None,
) -> tuple[bool, str]:
    """返回条款是否可编辑及对应原因。"""
    if clause_status not in KNOWN_CLAUSE_STATUSES:
        return False, CLAUSE_STATUS_UNKNOWN_REASON
    if chapter_id is None:
        return True, ""
    if backend_chapter_status is None:
        return False, BACKEND_STATUS_UNKNOWN_REASON
    if backend_chapter_status not in KNOWN_BACKEND_CHAPTER_STATUSES:
        return False, BACKEND_STATUS_UNKNOWN_REASON
    if backend_chapter_status == int(ChapterStatus.DRAFT):
        return True, ""
    return False, BACKEND_NOT_DRAFT_REASON


@dataclass(slots=True)
class BatchImportDocument:
    """批量导入工作台中的文档记录。"""

    id: int | None = None
    file_path: str = ""
    file_name: str = ""
    file_fingerprint: str = ""
    document_status: str = DocumentStatus.PREPARING.value
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
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class BatchImportClause:
    """批量导入工作台中的条款记录。"""

    id: int | None = None
    document_id: int | None = None
    sort_index: int = 0
    term: str = ""
    test_content: str = ""
    clause_status: str = ClauseStatus.PENDING_UPLOAD.value
    chapter_id: int | None = None
    backend_chapter_status: int | None = None
    source_docx_path: str = ""
    duplicate_flag: bool = False
    duplicate_reason: str = ""
    user_decision: str = ""
    create_error: str = ""
    upload_error: str = ""
    last_action: str = ""
