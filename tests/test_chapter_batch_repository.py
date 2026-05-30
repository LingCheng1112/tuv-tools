"""测试 Chapter 批量导入工作台 repository。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter_batch.models import (
    BatchImportClause,
    BatchImportDocument,
    ClauseStatus,
    DocumentStatus,
)

def _new_repo():
    from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository

    tmp = tempfile.mkdtemp()
    db = DatabaseManager(Path(tmp) / "batch.db")
    return ChapterBatchRepository(db)


class TestChapterBatchRepository:
    def test_create_document_and_replace_clauses(self):
        repo = _new_repo()

        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/a.docx",
                file_name="a.docx",
                standard="60335-2-9",
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
                ),
                BatchImportClause(
                    sort_index=1,
                    term="10.2",
                    test_content="Abnormal",
                    source_docx_path="C:/out/10_2.docx",
                ),
            ],
        )

        saved = repo.get_document(doc_id)
        clauses = repo.get_clauses(doc_id)

        assert saved is not None
        assert saved.standard == "60335-2-9"
        assert len(clauses) == 2
        assert clauses[0].term == "10.1"
        assert clauses[1].sort_index == 1

    def test_reaggregate_document_to_partial(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/a.docx",
                file_name="a.docx",
                document_status=DocumentStatus.PENDING_UPLOAD.value,
            )
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="10.1",
                    clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                    source_docx_path="C:/out/10_1.docx",
                ),
                BatchImportClause(
                    sort_index=1,
                    term="10.2",
                    clause_status=ClauseStatus.UPLOAD_FAILED.value,
                    source_docx_path="C:/out/10_2.docx",
                ),
            ],
        )

        repo.reaggregate_document(doc_id)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PARTIAL.value
        assert doc.success_clause_count == 1
        assert doc.failed_clause_count == 1

    def test_reaggregate_document_to_pending_upload_when_has_uploadable_clause(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(file_path="C:/docs/b.docx", file_name="b.docx")
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="8",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    source_docx_path="C:/out/8.docx",
                )
            ],
        )

        repo.reaggregate_document(doc_id)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_UPLOAD.value

    def test_reaggregate_document_to_pending_upload_when_all_clauses_are_pending_upload(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/b2.docx",
                file_name="b2.docx",
                document_status=DocumentStatus.UPLOADING.value,
            )
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="8.1",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    source_docx_path="C:/out/8_1.docx",
                ),
                BatchImportClause(
                    sort_index=1,
                    term="8.2",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    source_docx_path="C:/out/8_2.docx",
                ),
            ],
        )

        repo.reaggregate_document(doc_id)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_UPLOAD.value
        assert doc.total_clause_count == 2
        assert doc.success_clause_count == 0
        assert doc.failed_clause_count == 0
        assert doc.skipped_clause_count == 0

    def test_reaggregate_document_ignores_skip_like_decisions(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/skip.docx",
                file_name="skip.docx",
                document_status=DocumentStatus.UPLOADING.value,
            )
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="8.1",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    duplicate_flag=True,
                    user_decision="skip_duplicate",
                    source_docx_path="C:/out/8_1.docx",
                ),
                BatchImportClause(
                    sort_index=1,
                    term="8.2",
                    clause_status=ClauseStatus.UPLOAD_FAILED.value,
                    duplicate_flag=True,
                    user_decision="skip_duplicate_all",
                    source_docx_path="C:/out/8_2.docx",
                ),
            ],
        )

        repo.reaggregate_document(doc_id)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_UPLOAD.value
        assert doc.success_clause_count == 0
        assert doc.failed_clause_count == 1
        assert doc.skipped_clause_count == 0

    def test_list_documents_pending_upload_includes_pending_confirm(self):
        repo = _new_repo()
        repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/pending-upload.docx",
                file_name="pending-upload.docx",
                document_status=DocumentStatus.PENDING_UPLOAD.value,
            )
        )
        repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/pending-confirm.docx",
                file_name="pending-confirm.docx",
                document_status=DocumentStatus.PENDING_CONFIRM.value,
            )
        )

        documents = repo.list_documents(status=DocumentStatus.PENDING_UPLOAD.value)

        assert len(documents) == 2
        assert {document.document_status for document in documents} == {
            DocumentStatus.PENDING_UPLOAD.value,
            DocumentStatus.PENDING_CONFIRM.value,
        }

    def test_repository_normalizes_legacy_statuses_on_read(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/legacy.docx",
                file_name="legacy.docx",
                document_status=DocumentStatus.PENDING_UPLOAD.value,
            )
        )

        repo.update_document(doc_id, document_status="待创建")
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="9.1",
                    clause_status="用户跳过",
                    source_docx_path="C:/out/9_1.docx",
                ),
                BatchImportClause(
                    sort_index=1,
                    term="9.2",
                    clause_status="创建失败",
                    source_docx_path="C:/out/9_2.docx",
                ),
            ],
        )

        doc = repo.get_document(doc_id)
        clauses = repo.get_clauses(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_UPLOAD.value
        assert [clause.clause_status for clause in clauses] == [
            ClauseStatus.PENDING_UPLOAD.value,
            ClauseStatus.UPLOAD_FAILED.value,
        ]

    def test_clear_clauses_removes_previous_results(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(file_path="C:/docs/c.docx", file_name="c.docx")
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="9.1",
                    source_docx_path="C:/out/9_1.docx",
                )
            ],
        )

        repo.replace_clauses(doc_id, [])
        clauses = repo.get_clauses(doc_id)

        assert clauses == []

    def test_reaggregate_document_accepts_forced_status(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/d.docx",
                file_name="d.docx",
                document_status=DocumentStatus.UPLOADING.value,
            )
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="10.1",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    source_docx_path="C:/out/10_1.docx",
                )
            ],
        )

        repo.reaggregate_document(doc_id, forced_status=DocumentStatus.FAILED.value)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.FAILED.value
        assert doc.total_clause_count == 1
        assert doc.success_clause_count == 0
        assert doc.failed_clause_count == 0
        assert doc.skipped_clause_count == 0

    def test_reaggregate_document_forced_status_preserves_aggregate_counts(self):
        repo = _new_repo()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/e.docx",
                file_name="e.docx",
                document_status=DocumentStatus.UPLOADING.value,
            )
        )
        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="10.1",
                    clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                    source_docx_path="C:/out/10_1.docx",
                ),
                BatchImportClause(
                    sort_index=1,
                    term="10.2",
                    clause_status=ClauseStatus.UPLOAD_FAILED.value,
                    source_docx_path="C:/out/10_2.docx",
                ),
                BatchImportClause(
                    sort_index=2,
                    term="10.3",
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    source_docx_path="C:/out/10_3.docx",
                ),
            ],
        )

        repo.reaggregate_document(doc_id, forced_status=DocumentStatus.PENDING_UPLOAD.value)
        doc = repo.get_document(doc_id)

        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_UPLOAD.value
        assert doc.total_clause_count == 3
        assert doc.success_clause_count == 1
        assert doc.failed_clause_count == 1
        assert doc.skipped_clause_count == 0

    def test_clear_queued_flags_resets_all_queued_documents(self):
        repo = _new_repo()
        first_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/queued-a.docx",
                file_name="queued-a.docx",
                is_queued=True,
            )
        )
        second_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/queued-b.docx",
                file_name="queued-b.docx",
                is_queued=True,
            )
        )
        third_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/not-queued.docx",
                file_name="not-queued.docx",
                is_queued=False,
            )
        )

        repo.clear_queued_flags()

        first = repo.get_document(first_id)
        second = repo.get_document(second_id)
        third = repo.get_document(third_id)
        assert first is not None
        assert second is not None
        assert third is not None
        assert first.is_queued is False
        assert second.is_queued is False
        assert third.is_queued is False

    def test_repository_resolves_legacy_absolute_clause_paths_under_current_data_root(self, tmp_path):
        from tuv_tools.config import AppSettings
        from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository

        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        data_root = project_root / ".tuv-tools"
        chapter_batch_root = data_root / "chapter-batch"
        settings = AppSettings(project_root=project_root)
        settings.set_app_data_root(data_root)

        db = DatabaseManager(data_root / "batch.db")
        repo = ChapterBatchRepository(db)
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/a.docx",
                file_name="a.docx",
            )
        )
        legacy_root = tmp_path / "legacy-home" / ".tuv-tools" / "chapter-batch"
        expected_runtime_path = chapter_batch_root / "14" / "clauses_docx" / "13.2.docx"
        expected_runtime_path.parent.mkdir(parents=True, exist_ok=True)
        expected_runtime_path.write_text("docx", encoding="utf-8")

        repo.replace_clauses(
            doc_id,
            [
                BatchImportClause(
                    sort_index=0,
                    term="13.2",
                    source_docx_path=str(legacy_root / "14" / "clauses_docx" / "13.2.docx"),
                )
            ],
        )

        clause = repo.get_clauses(doc_id)[0]

        assert clause.source_docx_path == str(expected_runtime_path.resolve())

    def test_repository_resolves_clause_paths_under_configured_output_root_for_active_db(self, tmp_path):
        from tuv_tools.config import AppSettings
        from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository

        project_root = tmp_path / "repo"
        project_root.mkdir(parents=True)
        settings = AppSettings(project_root=project_root)
        db_path = settings.get_database_path()
        db = DatabaseManager(db_path)
        db.set_config("splitter.output_path", "custom-output")

        expected_runtime_path = project_root / "custom-output" / "chapter-batch" / "14" / "clauses_docx" / "13.2.docx"
        expected_runtime_path.parent.mkdir(parents=True, exist_ok=True)
        expected_runtime_path.write_text("docx", encoding="utf-8")

        with patch("tuv_tools.core.chapter_batch.repository.AppSettings", return_value=settings):
            repo = ChapterBatchRepository(db)
            doc_id = repo.create_document(
                BatchImportDocument(
                    file_path="C:/docs/a.docx",
                    file_name="a.docx",
                )
            )

            repo.replace_clauses(
                doc_id,
                [
                    BatchImportClause(
                        sort_index=0,
                        term="13.2",
                        source_docx_path=str(expected_runtime_path),
                    )
                ],
            )

            clause = repo.get_clauses(doc_id)[0]

        assert clause.source_docx_path == str(expected_runtime_path.resolve())
