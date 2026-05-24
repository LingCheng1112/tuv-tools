"""测试 Chapter 批量导入工作台 service。"""

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
    SplitMode,
)
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository


def _new_service():
    from tuv_tools.core.chapter_batch.service import ChapterBatchService

    tmp = tempfile.mkdtemp()
    db = DatabaseManager(Path(tmp) / "batch.db")
    repo = ChapterBatchRepository(db)
    return ChapterBatchService(repo), repo


class TestChapterBatchService:
    def test_import_documents_creates_workspace_records(self):
        service, repo = _new_service()

        docs = service.import_documents(
            [r"C:\docs\IEC60335-2-9 fryer.docx"],
            split_mode=SplitMode.CLAUSE.value,
        )

        assert len(docs) == 1
        saved = repo.get_document(docs[0].id)
        assert saved is not None
        assert saved.standard == "60335-2-9"
        assert saved.document_status == DocumentStatus.PENDING_SPLIT.value
        assert saved.split_mode == SplitMode.CLAUSE.value

    def test_import_documents_allows_missing_standard(self):
        service, repo = _new_service()

        docs = service.import_documents(
            [r"C:\docs\unknown.docx"],
            split_mode=SplitMode.SECTION.value,
        )

        saved = repo.get_document(docs[0].id)
        assert saved is not None
        assert saved.standard == ""
        assert saved.split_mode == SplitMode.SECTION.value

    def test_reset_document_for_resplit_clears_local_result_only(self):
        service, repo = _new_service()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/a.docx",
                file_name="a.docx",
                split_mode=SplitMode.CLAUSE.value,
                document_status=DocumentStatus.PARTIAL.value,
                success_clause_count=1,
                failed_clause_count=1,
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
                )
            ],
        )

        service.reset_document_for_resplit(doc_id, SplitMode.SECTION.value)

        doc = repo.get_document(doc_id)
        clauses = repo.get_clauses(doc_id)
        assert doc is not None
        assert doc.document_status == DocumentStatus.PENDING_CONFIRM.value
        assert doc.split_mode == SplitMode.SECTION.value
        assert doc.total_clause_count == 0
        assert clauses == []

    def test_duplicate_check_uses_folder_term_and_test_content(self):
        from tuv_tools.core.chapter_batch.service import check_duplicate_candidates

        current = BatchImportClause(term="10.1", test_content="Heating")
        existing = [{"term": "10.1", "test_content": "Heating", "folder_id": 7}]

        result = check_duplicate_candidates(folder_id=7, clause=current, existing_rows=existing)

        assert result.is_duplicate is True
        assert "term + testContent" in result.reason

    def test_duplicate_check_ignores_other_folder(self):
        from tuv_tools.core.chapter_batch.service import check_duplicate_candidates

        current = BatchImportClause(term="10.1", test_content="Heating")
        existing = [{"term": "10.1", "test_content": "Heating", "folder_id": 9}]

        result = check_duplicate_candidates(folder_id=7, clause=current, existing_rows=existing)

        assert result.is_duplicate is False

    def test_mark_duplicate_candidates_sets_clause_flags(self):
        service, repo = _new_service()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/a.docx",
                file_name="a.docx",
                folder_id=7,
            )
        )
        repo.replace_clauses(
            doc_id,
            [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
        )

        duplicates = service.mark_duplicate_candidates(
            doc_id,
            [{"folder_id": 7, "term": "10.1", "test_content": "Heating"}],
        )

        clause = repo.get_clauses(doc_id)[0]
        assert duplicates == [clause.id]
        assert clause.duplicate_flag is True
        assert "term + testContent" in clause.duplicate_reason

    def test_save_confirmed_documents_sets_pending_create(self):
        service, repo = _new_service()
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path="C:/docs/confirmed.docx",
                file_name="confirmed.docx",
                document_status=DocumentStatus.PENDING_CONFIRM.value,
            )
        )

        ready = service.save_confirmed_documents(
            {
                doc_id: {
                    "standard": "60335-2-9",
                    "folder_id": 1061,
                    "folder_name": "60335-2-9",
                    "product_type": "家电",
                    "plan_sr": "1",
                    "chapter_version": "1.0",
                }
            }
        )

        saved = repo.get_document(doc_id)
        assert ready == [doc_id]
        assert saved is not None
        assert saved.document_status == DocumentStatus.PENDING_CREATE.value
        assert saved.standard == "60335-2-9"

    def test_split_document_creates_clause_rows_from_real_docx(self, tmp_path):
        service, repo = _new_service()
        service._output_root = tmp_path
        fixture = Path(__file__).parent / "fixtures" / "Test Plan for IEC 60335-2-24.doc.docx"
        docs = service.import_documents([str(fixture)], split_mode=SplitMode.CLAUSE.value)

        service.split_document(docs[0].id)

        saved = repo.get_document(docs[0].id)
        clauses = repo.get_clauses(docs[0].id)
        assert saved is not None
        assert saved.document_status == DocumentStatus.PENDING_CONFIRM.value
        assert saved.total_clause_count == len(clauses)
        assert len(clauses) > 0
        assert clauses[0].term
        assert Path(clauses[0].source_docx_path).exists()

    def test_split_document_section_mode_uses_major_version_rows(self, tmp_path):
        service, repo = _new_service()
        service._output_root = tmp_path
        fixture = Path(__file__).parent / "fixtures" / "Test Plan for IEC 60335-2-24.doc.docx"
        docs = service.import_documents([str(fixture)], split_mode=SplitMode.SECTION.value)

        service.split_document(docs[0].id)

        saved = repo.get_document(docs[0].id)
        clauses = repo.get_clauses(docs[0].id)
        terms = [clause.term for clause in clauses]
        assert saved is not None
        assert saved.document_status == DocumentStatus.PENDING_CONFIRM.value
        assert "10" in terms
        assert all("." not in term for term in terms if term.isdigit())
        assert all(clause.test_content == clause.term for clause in clauses)
