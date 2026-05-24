"""测试 Chapter 批量导入执行器基础语义。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.core.chapter_batch.models import ClauseStatus, DocumentStatus
from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument
from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository


def _new_repo(tmp_path):
    return ChapterBatchRepository(DatabaseManager(tmp_path / "executor.db"))


def test_execution_queue_processes_documents_serially():
    from tuv_tools.core.chapter_batch.executor import ExecutionQueue

    queue = ExecutionQueue()
    queue.enqueue([1, 2, 3])

    assert queue.next_document() == 1
    assert queue.next_document() == 2
    assert queue.next_document() == 3
    assert queue.next_document() is None


def test_cancel_keeps_remaining_clause_statuses_pending():
    from tuv_tools.core.chapter_batch.executor import apply_cancel_result

    result = apply_cancel_result(
        processed_statuses=[ClauseStatus.UPLOAD_SUCCESS.value],
        remaining_statuses=[ClauseStatus.PENDING_CREATE.value, ClauseStatus.PENDING_UPLOAD.value],
    )

    assert result["remaining"] == [
        ClauseStatus.PENDING_CREATE.value,
        ClauseStatus.PENDING_UPLOAD.value,
    ]
    assert result["document_status"] == DocumentStatus.PARTIAL.value


def test_cancel_after_create_before_upload_keeps_document_pending_upload():
    from tuv_tools.core.chapter_batch.executor import derive_document_status_after_cancel

    status = derive_document_status_after_cancel(
        had_upload_success=False,
        has_pending_upload=True,
        attempted_uploads_all_failed=False,
    )

    assert status == DocumentStatus.PENDING_UPLOAD.value


def test_cancel_with_failed_uploads_and_no_success_marks_failed():
    from tuv_tools.core.chapter_batch.executor import derive_document_status_after_cancel

    status = derive_document_status_after_cancel(
        had_upload_success=False,
        has_pending_upload=False,
        attempted_uploads_all_failed=True,
    )

    assert status == DocumentStatus.FAILED.value


def test_executor_creates_then_uploads_document_serially(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a.docx",
            file_name="a.docx",
            document_status=DocumentStatus.PENDING_CREATE.value,
            standard="60335-2-9",
            folder_id=7,
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    created_payloads = []
    uploaded = []

    def create_chapter(payload):
        created_payloads.append(payload)
        return 101

    def upload_doc(chapter_id, source_docx_path):
        uploaded.append((chapter_id, source_docx_path))

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=create_chapter,
        upload_chapter_doc=upload_doc,
    )
    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clause = repo.get_clauses(doc_id)[0]
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert clause.chapter_id == 101
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert created_payloads[0].term == "10.1"
    assert uploaded == [(101, "C:/out/10_1.docx")]


def test_executor_continues_after_clause_create_failure(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/b.docx",
            file_name="b.docx",
            document_status=DocumentStatus.PENDING_CREATE.value,
            standard="60335-2-9",
            folder_id=7,
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(sort_index=0, term="10.1", source_docx_path="C:/out/10_1.docx"),
            BatchImportClause(sort_index=1, term="10.2", source_docx_path="C:/out/10_2.docx"),
        ],
    )

    def create_chapter(payload):
        if payload.term == "10.1":
            raise RuntimeError("create failed")
        return 202

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=create_chapter,
        upload_chapter_doc=lambda _chapter_id, _path: None,
    )
    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clauses = repo.get_clauses(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PARTIAL.value
    assert clauses[0].clause_status == ClauseStatus.CREATE_FAILED.value
    assert clauses[1].clause_status == ClauseStatus.UPLOAD_SUCCESS.value


def test_executor_uploads_pending_upload_without_recreating(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/c.docx",
            file_name="c.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="11",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=303,
                source_docx_path="C:/out/11.docx",
            )
        ],
    )
    created = []
    uploaded = []

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: created.append(payload) or 999,
        upload_chapter_doc=lambda chapter_id, path: uploaded.append((chapter_id, path)),
    )
    executor.run_documents([doc_id])

    assert created == []
    assert uploaded == [(303, "C:/out/11.docx")]
    assert repo.get_clauses(doc_id)[0].clause_status == ClauseStatus.UPLOAD_SUCCESS.value


def test_executor_retries_failed_clause_statuses(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/d.docx",
            file_name="d.docx",
            document_status=DocumentStatus.FAILED.value,
            standard="60335-2-9",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.CREATE_FAILED.value,
                source_docx_path="C:/out/10_1.docx",
            ),
            BatchImportClause(
                sort_index=1,
                term="10.2",
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=404,
                source_docx_path="C:/out/10_2.docx",
            ),
        ],
    )
    created = []
    uploaded = []

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: created.append(payload.term) or 405,
        upload_chapter_doc=lambda chapter_id, path: uploaded.append((chapter_id, path)),
    )
    executor.run_documents([doc_id])

    clauses = repo.get_clauses(doc_id)
    assert created == ["10.1"]
    assert uploaded == [(405, "C:/out/10_1.docx"), (404, "C:/out/10_2.docx")]
    assert all(clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for clause in clauses)


def test_executor_cancel_clears_remaining_queue_flags(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    first_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/e.docx", file_name="e.docx", document_status=DocumentStatus.PENDING_CREATE.value)
    )
    second_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/f.docx", file_name="f.docx", document_status=DocumentStatus.PENDING_CREATE.value, is_queued=True)
    )
    repo.replace_clauses(
        first_id,
        [BatchImportClause(sort_index=0, term="10.1", source_docx_path="C:/out/10_1.docx")],
    )
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 1,
        upload_chapter_doc=lambda _chapter_id, _path: executor.request_cancel(),
    )

    executor.run_documents([first_id, second_id])

    second = repo.get_document(second_id)
    assert second is not None
    assert second.is_queued is False
    assert second.document_status == DocumentStatus.PENDING_CREATE.value


def test_executor_cancel_can_be_requested_by_worker(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/g.docx", file_name="g.docx", document_status=DocumentStatus.PENDING_CREATE.value)
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", source_docx_path="C:/out/10_1.docx")],
    )
    controller = ChapterBatchExecutionController()
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 1,
        upload_chapter_doc=lambda _chapter_id, _path: controller.request_cancel(),
        controller=controller,
    )

    executor.run_documents([doc_id])

    assert controller.cancel_requested() is True
