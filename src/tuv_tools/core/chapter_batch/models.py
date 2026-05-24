"""Chapter 批量导入工作台领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SplitMode(StrEnum):
    """文档拆分模式。"""

    SECTION = "章节"
    CLAUSE = "条款"


class DocumentStatus(StrEnum):
    """工作台文档级状态。"""

    PENDING_SPLIT = "待拆分"
    SPLITTING = "拆分中"
    PENDING_CONFIRM = "待确认"
    PENDING_CREATE = "待创建"
    CREATING = "创建中"
    PENDING_UPLOAD = "待上传"
    UPLOADING = "上传中"
    COMPLETED = "已完成"
    PARTIAL = "部分完成"
    SKIPPED = "已跳过"
    FAILED = "失败"


class ClauseStatus(StrEnum):
    """工作台条款级状态。"""

    PENDING_CREATE = "待创建"
    CREATE_FAILED = "创建失败"
    PENDING_UPLOAD = "待上传"
    UPLOAD_SUCCESS = "上传成功"
    UPLOAD_FAILED = "上传失败"
    SKIPPED = "用户跳过"


EXECUTABLE_DOCUMENT_STATUSES = {
    DocumentStatus.PENDING_CREATE.value,
    DocumentStatus.PENDING_UPLOAD.value,
    DocumentStatus.PARTIAL.value,
    DocumentStatus.FAILED.value,
}


def is_document_executable(status: str) -> bool:
    """判断文档是否允许进入执行队列。"""
    return status in EXECUTABLE_DOCUMENT_STATUSES


@dataclass(slots=True)
class BatchImportDocument:
    """批量导入工作台中的文档记录。"""

    id: int | None = None
    file_path: str = ""
    file_name: str = ""
    file_fingerprint: str = ""
    document_status: str = DocumentStatus.PENDING_SPLIT.value
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


@dataclass(slots=True)
class BatchImportClause:
    """批量导入工作台中的条款记录。"""

    id: int | None = None
    document_id: int | None = None
    sort_index: int = 0
    term: str = ""
    test_content: str = ""
    clause_status: str = ClauseStatus.PENDING_CREATE.value
    chapter_id: int | None = None
    backend_chapter_status: int | None = None
    source_docx_path: str = ""
    duplicate_flag: bool = False
    duplicate_reason: str = ""
    user_decision: str = ""
    create_error: str = ""
    upload_error: str = ""
    last_action: str = ""
