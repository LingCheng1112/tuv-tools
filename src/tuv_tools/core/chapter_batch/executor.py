"""Chapter 批量导入工作台执行器基础原语。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tuv_tools.core.chapter.models import Chapter, ChapterStatus

from .models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
from .repository import ChapterBatchRepository


CreateChapterCallable = Callable[[Chapter], int]
UploadChapterDocCallable = Callable[[int, str], None]


@dataclass(slots=True)
class ExecutionQueue:
    """文档级串行执行队列。"""

    _items: list[int] = field(default_factory=list)
    _cancel_requested: bool = False

    def enqueue(self, document_ids: list[int]) -> None:
        self._items.extend(document_ids)

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def next_document(self) -> int | None:
        if not self._items:
            return None
        return self._items.pop(0)


class ChapterBatchExecutionController:
    """跨线程共享的执行取消控制器。"""

    def __init__(self):
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def cancel_requested(self) -> bool:
        return self._cancel_requested


def derive_document_status_after_cancel(
    *,
    had_upload_success: bool,
    has_pending_upload: bool,
    attempted_uploads_all_failed: bool,
) -> str:
    """根据取消时机和已有结果推导文档状态。"""
    if had_upload_success:
        return DocumentStatus.PARTIAL.value
    if has_pending_upload:
        return DocumentStatus.PENDING_UPLOAD.value
    if attempted_uploads_all_failed:
        return DocumentStatus.FAILED.value
    return DocumentStatus.PENDING_CREATE.value


def apply_cancel_result(
    *,
    processed_statuses: list[str],
    remaining_statuses: list[str],
) -> dict[str, object]:
    """根据条款已处理/未处理状态推导取消后的文档归档。"""
    had_upload_success = ClauseStatus.UPLOAD_SUCCESS.value in processed_statuses
    has_pending_upload = ClauseStatus.PENDING_UPLOAD.value in remaining_statuses
    attempted_uploads_all_failed = (
        not had_upload_success
        and bool(processed_statuses)
        and all(status == ClauseStatus.UPLOAD_FAILED.value for status in processed_statuses)
    )
    return {
        "remaining": remaining_statuses,
        "document_status": derive_document_status_after_cancel(
            had_upload_success=had_upload_success,
            has_pending_upload=has_pending_upload,
            attempted_uploads_all_failed=attempted_uploads_all_failed,
        ),
    }


class ChapterBatchExecutor:
    """执行文档级串行、条款级继续的创建和上传流程。"""

    def __init__(
        self,
        repo: ChapterBatchRepository,
        *,
        create_chapter: CreateChapterCallable,
        upload_chapter_doc: UploadChapterDocCallable,
        controller: ChapterBatchExecutionController | None = None,
    ):
        self._repo = repo
        self._create_chapter = create_chapter
        self._upload_chapter_doc = upload_chapter_doc
        self._queue = ExecutionQueue()
        self._controller = controller

    def request_cancel(self) -> None:
        self._queue.request_cancel()
        if self._controller is not None:
            self._controller.request_cancel()

    def _cancel_requested(self) -> bool:
        return self._queue.cancel_requested() or (
            self._controller is not None and self._controller.cancel_requested()
        )

    def run_documents(self, document_ids: list[int]) -> None:
        self._queue.enqueue(document_ids)
        while not self._cancel_requested():
            document_id = self._queue.next_document()
            if document_id is None:
                return
            self._run_document(document_id)
        self._clear_queued_flags()

    def _run_document(self, document_id: int) -> None:
        document = self._repo.get_document(document_id)
        if document is None:
            return
        clauses = self._repo.get_clauses(document_id)
        if not clauses:
            self._repo.update_document(
                document_id,
                document_status=DocumentStatus.FAILED.value,
                last_error="No clauses to execute",
                is_queued=0,
            )
            return

        self._repo.update_document(
            document_id,
            document_status=DocumentStatus.CREATING.value,
            is_queued=1,
            last_error="",
        )
        for clause in clauses:
            if self._cancel_requested():
                self._apply_cancel(document_id)
                return
            if clause.clause_status == ClauseStatus.SKIPPED.value:
                continue
            if clause.clause_status in {
                ClauseStatus.CREATE_FAILED.value,
                ClauseStatus.UPLOAD_FAILED.value,
            }:
                self._repo.update_clause(
                    clause.id,
                    clause_status=(
                        ClauseStatus.PENDING_UPLOAD.value
                        if clause.chapter_id
                        else ClauseStatus.PENDING_CREATE.value
                    ),
                    create_error="",
                    upload_error="",
                )
                clause = self._repo.get_clause(clause.id) if clause.id is not None else clause
                if clause is None:
                    continue
            if clause.clause_status == ClauseStatus.PENDING_UPLOAD.value and clause.chapter_id:
                continue
            if clause.clause_status != ClauseStatus.PENDING_CREATE.value:
                continue
            self._create_clause(document, clause)

        self._repo.update_document(document_id, document_status=DocumentStatus.UPLOADING.value)
        for clause in self._repo.get_clauses(document_id):
            if self._cancel_requested():
                self._apply_cancel(document_id)
                return
            if clause.clause_status == ClauseStatus.SKIPPED.value:
                continue
            if clause.clause_status != ClauseStatus.PENDING_UPLOAD.value or clause.chapter_id is None:
                continue
            self._upload_clause(clause)
            if self._cancel_requested():
                self._apply_cancel(document_id)
                return
        self._repo.update_document(document_id, is_queued=0)
        self._repo.reaggregate_document(document_id)

    def _create_clause(self, document: BatchImportDocument, clause: BatchImportClause) -> None:
        if clause.id is None:
            return
        try:
            chapter = self._build_chapter(document, clause)
            chapter_id = self._create_chapter(chapter)
            self._repo.update_clause(
                clause.id,
                chapter_id=chapter_id,
                backend_chapter_status=int(ChapterStatus.DRAFT),
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                create_error="",
                last_action="create",
            )
        except Exception as exc:
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.CREATE_FAILED.value,
                create_error=str(exc),
                last_action="create_failed",
            )

    def _upload_clause(self, clause: BatchImportClause) -> None:
        if clause.id is None or clause.chapter_id is None:
            return
        try:
            self._upload_chapter_doc(clause.chapter_id, clause.source_docx_path)
            if self._cancel_requested():
                return
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                upload_error="",
                last_action="upload",
            )
        except Exception as exc:
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                upload_error=str(exc),
                last_action="upload_failed",
            )

    def _build_chapter(self, document: BatchImportDocument, clause: BatchImportClause) -> Chapter:
        return Chapter(
            term=clause.term,
            test_content=clause.test_content,
            standard=document.standard,
            standard_version=document.standard_version,
            version=_safe_int(document.chapter_version, default=1),
            status=int(ChapterStatus.DRAFT),
            product_type=document.product_type,
            plan_sr=document.plan_sr,
            specific_product=document.specific_product,
            folder_id=document.folder_id,
        )

    def _apply_cancel(self, document_id: int) -> None:
        clauses = self._repo.get_clauses(document_id)
        processed_statuses: list[str] = []
        remaining_statuses: list[str] = []
        for clause in clauses:
            if clause.clause_status in {
                ClauseStatus.PENDING_CREATE.value,
                ClauseStatus.PENDING_UPLOAD.value,
            }:
                remaining_statuses.append(clause.clause_status)
                continue
            if clause.clause_status != ClauseStatus.SKIPPED.value:
                processed_statuses.append(clause.clause_status)
        self._repo.update_document(document_id, is_queued=0)
        result = apply_cancel_result(
            processed_statuses=processed_statuses,
            remaining_statuses=remaining_statuses,
        )
        self._repo.reaggregate_document(
            document_id,
            forced_status=result["document_status"],
        )
        self._clear_queued_flags()

    def _clear_queued_flags(self) -> None:
        for document in self._repo.list_documents():
            if document.is_queued:
                self._repo.update_document(document.id, is_queued=0)


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
