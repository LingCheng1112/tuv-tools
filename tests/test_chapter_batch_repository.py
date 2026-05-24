"""测试 Chapter 批量导入工作台 repository。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

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
                document_status=DocumentStatus.PENDING_CREATE.value,
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
