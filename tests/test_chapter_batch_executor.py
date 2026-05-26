"""测试 Chapter 批量导入执行器基础语义。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.core.chapter_batch.models import ClauseStatus, DocumentStatus
from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument
from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository

UPLOAD_IN_PROGRESS = "上传中"


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


def test_cancel_keeps_remaining_clause_statuses_pending_upload():
    from tuv_tools.core.chapter_batch.executor import apply_cancel_result

    result = apply_cancel_result(
        processed_statuses=[ClauseStatus.UPLOAD_SUCCESS.value],
        remaining_statuses=[ClauseStatus.PENDING_UPLOAD.value, ClauseStatus.PENDING_UPLOAD.value],
    )

    assert result["remaining"] == [
        ClauseStatus.PENDING_UPLOAD.value,
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


def test_cancel_without_success_or_pending_upload_falls_back_to_pending_upload():
    from tuv_tools.core.chapter_batch.executor import derive_document_status_after_cancel

    status = derive_document_status_after_cancel(
        had_upload_success=False,
        has_pending_upload=False,
        attempted_uploads_all_failed=False,
    )

    assert status == DocumentStatus.PENDING_UPLOAD.value


def test_executor_uploads_document_serially_from_pending_upload(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a.docx",
            file_name="a.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
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
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=101,
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
    assert created_payloads == []
    assert uploaded == [(101, "C:/out/10_1.docx")]


def test_executor_uploads_document_serially_from_pending_confirm(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a_confirm.docx",
            file_name="a_confirm.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
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
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=102,
                source_docx_path="C:/out/10_1_confirm.docx",
            )
        ],
    )

    created_payloads = []
    uploaded = []

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: created_payloads.append(payload) or 102,
        upload_chapter_doc=lambda chapter_id, source_docx_path: uploaded.append((chapter_id, source_docx_path)),
    )
    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clause = repo.get_clauses(doc_id)[0]
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert clause.chapter_id == 102
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert created_payloads == []
    assert uploaded == [(102, "C:/out/10_1_confirm.docx")]


def test_executor_continues_after_upload_failure(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/b.docx",
            file_name="b.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
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
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=201,
                source_docx_path="C:/out/10_1.docx",
            ),
            BatchImportClause(
                sort_index=1,
                term="10.2",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=202,
                source_docx_path="C:/out/10_2.docx",
            ),
        ],
    )

    uploaded = []

    def upload_doc(chapter_id, path):
        uploaded.append((chapter_id, path))
        if chapter_id == 201:
            raise RuntimeError("upload failed")

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: 999,
        upload_chapter_doc=upload_doc,
    )
    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clauses = repo.get_clauses(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PARTIAL.value
    assert uploaded == [(201, "C:/out/10_1.docx"), (202, "C:/out/10_2.docx")]
    assert clauses[0].clause_status == ClauseStatus.UPLOAD_FAILED.value
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


def test_executor_all_pending_upload_document_falls_back_to_pending_upload_when_no_upload_done(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/c2.docx",
            file_name="c2.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="11.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=303,
                source_docx_path="C:/out/11_1.docx",
            ),
            BatchImportClause(
                sort_index=1,
                term="11.2",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=304,
                source_docx_path="C:/out/11_2.docx",
            ),
        ],
    )
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: 999,
        upload_chapter_doc=lambda chapter_id, path: None,
    )

    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert saved.skipped_clause_count == 0


def test_executor_retries_failed_upload_clauses_based_on_existing_chapter_id(tmp_path):
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
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
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


def test_executor_create_payload_keeps_string_version_for_backend(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/versioned.docx",
            file_name="versioned.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            standard="60335-2-9",
            standard_version="2020",
            folder_id=7,
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
            specific_product="Model A",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    created_payloads = []
    uploaded = []

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: created_payloads.append(payload) or 600,
        upload_chapter_doc=lambda chapter_id, source_docx_path: uploaded.append((chapter_id, source_docx_path)),
    )

    executor.run_documents([doc_id])

    assert len(created_payloads) == 1
    payload = created_payloads[0]
    assert payload.version == "1.0"
    assert payload.standard_version == "2020"
    assert payload.plan_sr == "1"
    assert payload.specific_product == "Model A"
    assert uploaded == [(600, "C:/out/10_1.docx")]


def test_executor_reuploads_success_clause_without_creating_new_chapter(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/reupload.docx",
            file_name="reupload.docx",
            document_status=DocumentStatus.COMPLETED.value,
            standard="60335-2-9",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="19.11",
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=808,
                source_docx_path="C:/out/19_11.docx",
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

    executor.run_clauses(doc_id, [repo.get_clauses(doc_id)[0].id])

    saved_clause = repo.get_clauses(doc_id)[0]
    saved_doc = repo.get_document(doc_id)
    assert created == []
    assert uploaded == [(808, "C:/out/19_11.docx")]
    assert saved_clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert saved_doc is not None
    assert saved_doc.document_status == DocumentStatus.COMPLETED.value


def test_executor_cancel_clears_remaining_queue_flags_and_keeps_pending_upload(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    first_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/e.docx", file_name="e.docx", document_status=DocumentStatus.PENDING_UPLOAD.value)
    )
    second_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/f.docx", file_name="f.docx", document_status=DocumentStatus.PENDING_UPLOAD.value, is_queued=True)
    )
    repo.replace_clauses(
        first_id,
        [BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.PENDING_UPLOAD.value, chapter_id=1, source_docx_path="C:/out/10_1.docx")],
    )
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 1,
        upload_chapter_doc=lambda _chapter_id, _path: executor.request_cancel(),
    )

    executor.run_documents([first_id, second_id])

    second = repo.get_document(second_id)
    first = repo.get_document(first_id)
    assert second is not None
    assert first is not None
    assert second.is_queued is False
    assert second.document_status == DocumentStatus.PENDING_UPLOAD.value
    assert first.document_status == DocumentStatus.COMPLETED.value


def test_executor_cancel_can_be_requested_by_worker(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/g.docx", file_name="g.docx", document_status=DocumentStatus.PENDING_UPLOAD.value)
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.PENDING_UPLOAD.value, chapter_id=1, source_docx_path="C:/out/10_1.docx")],
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


def test_cancel_after_successful_single_upload_marks_document_completed(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/h.docx",
            file_name="h.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.PENDING_UPLOAD.value, chapter_id=1, source_docx_path="C:/out/10_1.docx")],
    )
    controller = ChapterBatchExecutionController()
    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 1,
        upload_chapter_doc=lambda _chapter_id, _path: controller.request_cancel(),
        controller=controller,
    )

    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clause = repo.get_clauses(doc_id)[0]
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert saved.success_clause_count == 1
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value


def test_cancel_after_partial_upload_marks_document_partial(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/i.docx",
            file_name="i.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=1,
                source_docx_path="C:/out/10_1.docx",
            ),
            BatchImportClause(
                sort_index=1,
                term="10.2",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=2,
                source_docx_path="C:/out/10_2.docx",
            ),
            BatchImportClause(
                sort_index=2,
                term="10.3",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=3,
                source_docx_path="C:/out/10_3.docx",
            ),
        ],
    )
    calls = {"count": 0}
    executor: ChapterBatchExecutor | None = None

    def upload_doc(_chapter_id, _path):
        calls["count"] += 1
        if calls["count"] == 2 and executor is not None:
            executor.request_cancel()

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 999,
        upload_chapter_doc=upload_doc,
    )

    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clauses = repo.get_clauses(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PARTIAL.value
    assert saved.success_clause_count == 2
    assert clauses[0].clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert clauses[1].clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert clauses[2].clause_status == ClauseStatus.PENDING_UPLOAD.value


def test_cancel_on_last_upload_keeps_completed_result_without_forced_cancel_status(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/j.docx",
            file_name="j.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=1,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    forced_statuses = []
    original_reaggregate = repo.reaggregate_document

    def tracking_reaggregate(document_id, *, forced_status=None):
        forced_statuses.append(forced_status)
        return original_reaggregate(document_id, forced_status=forced_status)

    repo.reaggregate_document = tracking_reaggregate  # type: ignore[method-assign]
    executor: ChapterBatchExecutor | None = None

    def upload_doc(_chapter_id, _path):
        if executor is not None:
            executor.request_cancel()

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 999,
        upload_chapter_doc=upload_doc,
    )

    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clause = repo.get_clauses(doc_id)[0]
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert saved.success_clause_count == 1
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert forced_statuses == [None]


def test_cancel_after_successful_upload_keeps_success_status(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/success-cancel.docx",
            file_name="success-cancel.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=1,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    controller = ChapterBatchExecutionController()
    uploads = []

    def upload_doc(chapter_id, path):
        uploads.append((chapter_id, path))
        controller.request_cancel()

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda _payload: 999,
        upload_chapter_doc=upload_doc,
        controller=controller,
    )

    executor.run_documents([doc_id])

    saved = repo.get_document(doc_id)
    clause = repo.get_clauses(doc_id)[0]
    assert uploads == [(1, "C:/out/10_1.docx")]
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value
    assert saved.success_clause_count == 1
    assert saved.failed_clause_count == 0
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value


def test_executor_run_clauses_only_processes_selected_clause_ids(tmp_path):
    from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutor

    repo = _new_repo(tmp_path)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/k.docx",
            file_name="k.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
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
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=500,
                source_docx_path="C:/out/10_1.docx",
            ),
            BatchImportClause(
                sort_index=1,
                term="10.2",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=501,
                source_docx_path="C:/out/10_2.docx",
            ),
        ],
    )
    clause_ids = [clause.id for clause in repo.get_clauses(doc_id)]
    created = []
    uploaded = []

    executor = ChapterBatchExecutor(
        repo,
        create_chapter=lambda payload: created.append(payload.term) or 999,
        upload_chapter_doc=lambda chapter_id, path: uploaded.append((chapter_id, path)),
    )

    executor.run_clauses(doc_id, [clause_ids[1]])

    clauses = repo.get_clauses(doc_id)
    assert created == []
    assert uploaded == [(501, "C:/out/10_2.docx")]
    assert clauses[0].clause_status == ClauseStatus.PENDING_UPLOAD.value
    assert clauses[1].clause_status == ClauseStatus.UPLOAD_SUCCESS.value
