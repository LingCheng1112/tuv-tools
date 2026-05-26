"""Chapter 批量上传执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tuv_tools.core.chapter.models import Chapter, ChapterStatus

from .models import (
    BatchImportClause,
    BatchImportDocument,
    ChapterBatchProgressEvent,
    ClauseStatus,
    DocumentStatus,
)
from .repository import ChapterBatchRepository


CreateChapterCallable = Callable[[Chapter], int]
UploadChapterDocCallable = Callable[[int, str], None]
ProgressCallback = Callable[[ChapterBatchProgressEvent], None]


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
    return DocumentStatus.PENDING_UPLOAD.value


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
    """执行文档级串行、条款级续跑的上传流程。"""

    def __init__(
        self,
        repo: ChapterBatchRepository,
        *,
        create_chapter: CreateChapterCallable,
        upload_chapter_doc: UploadChapterDocCallable,
        controller: ChapterBatchExecutionController | None = None,
        progress: ProgressCallback | None = None,
    ):
        self._repo = repo
        self._create_chapter = create_chapter
        self._upload_chapter_doc = upload_chapter_doc
        self._queue = ExecutionQueue()
        self._controller = controller
        self._progress = progress

    def _emit_progress(
        self,
        *,
        document_id: int,
        percent: int,
        message: str,
        current_index: int = 0,
        total_count: int = 0,
        current_clause_term: str = "",
        action: str = "",
    ) -> None:
        if self._progress is None:
            return
        self._progress(
            ChapterBatchProgressEvent(
                document_id=document_id,
                phase="uploading",
                percent=max(0, min(percent, 100)),
                message=message,
                current_index=current_index,
                total_count=total_count,
                current_clause_term=current_clause_term,
                action=action,
            )
        )

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
                self._clear_queued_flags()
                return
            self._run_document(document_id)
        self._clear_queued_flags()

    def run_clauses(self, document_id: int, clause_ids: list[int]) -> None:
        document = self._repo.get_document(document_id)
        if document is None:
            return
        clause_id_set = {int(clause_id) for clause_id in clause_ids}
        if not clause_id_set:
            return
        clauses = [clause for clause in self._repo.get_clauses(document_id) if clause.id in clause_id_set]
        if not clauses:
            return
        self._execute_document(document_id, clause_id_set=clause_id_set)

    def _run_document(self, document_id: int) -> None:
        clauses = self._repo.get_clauses(document_id)
        if not clauses:
            self._repo.update_document(
                document_id,
                document_status=DocumentStatus.FAILED.value,
                last_error="No clauses to execute",
                is_queued=0,
            )
            return
        self._execute_document(document_id, clause_id_set=None)

    def _execute_document(self, document_id: int, clause_id_set: set[int] | None) -> None:
        document = self._repo.get_document(document_id)
        if document is None:
            return

        self._repo.update_document(
            document_id,
            document_status=DocumentStatus.UPLOADING.value,
            is_queued=1,
            last_error="",
        )

        clauses = self._repo.get_clauses(document_id)
        target_clauses = [
            clause for clause in clauses if clause_id_set is None or clause.id in clause_id_set
        ]
        total_count = len(target_clauses)
        self._emit_progress(
            document_id=document_id,
            percent=0,
            message="准备上传",
            current_index=0,
            total_count=total_count,
            action="prepare",
        )
        for index, original_clause in enumerate(target_clauses, start=1):
            if clause_id_set is not None and original_clause.id not in clause_id_set:
                continue
            if self._cancel_requested():
                self._apply_cancel(document_id)
                return

            self._emit_progress(
                document_id=document_id,
                percent=self._progress_percent(index - 1, total_count, 0.0),
                message=f"校验条款 {original_clause.term}",
                current_index=index,
                total_count=total_count,
                current_clause_term=original_clause.term,
                action="duplicate_check",
            )
            clause = self._prepare_clause_for_execution(original_clause)
            if clause is None:
                continue
            if (
                clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
                and clause.chapter_id is not None
                and clause_id_set is not None
            ):
                completed = self._upload_clause(
                    clause,
                    document_id=document_id,
                    clause_index=index,
                    total_count=total_count,
                    action_name="reupload",
                )
                if self._cancel_requested():
                    if index < total_count:
                        self._apply_cancel(document_id)
                        return
                if not completed:
                    continue
                continue
            if clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value:
                continue
            if clause.clause_status != ClauseStatus.PENDING_UPLOAD.value:
                continue

            if clause.chapter_id is None:
                clause = self._create_clause(
                    document,
                    clause,
                    document_id=document_id,
                    clause_index=index,
                    total_count=total_count,
                )
                if clause is None:
                    continue
                if self._cancel_requested():
                    self._apply_cancel(document_id)
                    return
                if clause.clause_status != ClauseStatus.PENDING_UPLOAD.value or clause.chapter_id is None:
                    continue

            if self._cancel_requested():
                self._apply_cancel(document_id)
                return

            completed = self._upload_clause(
                clause,
                document_id=document_id,
                clause_index=index,
                total_count=total_count,
                action_name="upload",
            )
            if self._cancel_requested():
                if index < total_count:
                    self._apply_cancel(document_id)
                    return
            if not completed:
                continue

        self._repo.update_document(document_id, is_queued=0)
        self._repo.reaggregate_document(document_id)
        self._emit_progress(
            document_id=document_id,
            percent=100,
            message="上传完成",
            current_index=total_count,
            total_count=total_count,
            action="completed",
        )

    def _prepare_clause_for_execution(self, clause: BatchImportClause) -> BatchImportClause | None:
        if clause.id is None:
            return None
        if clause.clause_status == ClauseStatus.UPLOADING.value:
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                upload_error="",
            )
        elif clause.clause_status == ClauseStatus.UPLOAD_FAILED.value:
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                create_error="",
                upload_error="",
            )
        return self._repo.get_clause(clause.id)

    def _create_clause(
        self,
        document: BatchImportDocument,
        clause: BatchImportClause,
        *,
        document_id: int,
        clause_index: int,
        total_count: int,
    ) -> BatchImportClause | None:
        if clause.id is None:
            return None
        try:
            self._emit_progress(
                document_id=document_id,
                percent=self._progress_percent(clause_index - 1, total_count, 0.2),
                message=f"创建条款 {clause.term}",
                current_index=clause_index,
                total_count=total_count,
                current_clause_term=clause.term,
                action="create",
            )
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
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                create_error=str(exc),
                last_action="create_failed",
            )
        return self._repo.get_clause(clause.id)

    def _upload_clause(
        self,
        clause: BatchImportClause,
        *,
        document_id: int,
        clause_index: int,
        total_count: int,
        action_name: str,
    ) -> bool:
        if clause.id is None or clause.chapter_id is None:
            return False
        self._repo.update_clause(
            clause.id,
            clause_status=ClauseStatus.UPLOADING.value,
            upload_error="",
            last_action="uploading",
        )
        try:
            self._emit_progress(
                document_id=document_id,
                percent=self._progress_percent(clause_index - 1, total_count, 0.65),
                message=f"{'重新上传' if action_name == 'reupload' else '上传'}条款 {clause.term}",
                current_index=clause_index,
                total_count=total_count,
                current_clause_term=clause.term,
                action=action_name,
            )
            self._upload_chapter_doc(clause.chapter_id, clause.source_docx_path)
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                upload_error="",
                last_action="upload",
            )
            if self._cancel_requested():
                return True
            self._emit_progress(
                document_id=document_id,
                percent=self._progress_percent(clause_index, total_count, 0.0),
                message=f"条款 {clause.term} 已完成",
                current_index=clause_index,
                total_count=total_count,
                current_clause_term=clause.term,
                action="completed",
            )
            return True
        except Exception as exc:
            self._repo.update_clause(
                clause.id,
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                upload_error=str(exc),
                last_action="upload_failed",
            )
            return False

    @staticmethod
    def _progress_percent(completed_count: int, total_count: int, step_ratio: float) -> int:
        if total_count <= 0:
            return 0
        normalized_completed = max(completed_count, 0)
        normalized_step = min(max(step_ratio, 0.0), 1.0)
        return int(round(((normalized_completed + normalized_step) / total_count) * 100))

    def _build_chapter(self, document: BatchImportDocument, clause: BatchImportClause) -> Chapter:
        return Chapter(
            term=clause.term,
            test_content=clause.test_content,
            standard=document.standard,
            standard_version=document.standard_version,
            version=(document.chapter_version or "").strip(),
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
            if clause.id is None:
                continue
            if clause.clause_status == ClauseStatus.UPLOADING.value:
                self._repo.update_clause(
                    clause.id,
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    last_action="upload_cancelled",
                )
                remaining_statuses.append(ClauseStatus.PENDING_UPLOAD.value)
                continue
            if clause.clause_status == ClauseStatus.PENDING_UPLOAD.value:
                remaining_statuses.append(clause.clause_status)
                continue
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
        self._repo.clear_queued_flags()
