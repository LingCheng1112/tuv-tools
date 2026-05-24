"""Chapter 批量导入工作台本地业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

from tuv_tools.config.database import _extract_standard_number
from tuv_tools.config.settings import AppSettings
from tuv_tools.core.splitter.exporting import _write_docx_from_template
from tuv_tools.core.splitter.parsing import build_sections
from tuv_tools.core.splitter.utils import safe_name

from .models import BatchImportClause, BatchImportDocument, DocumentStatus, SplitMode, is_document_running
from .repository import ChapterBatchRepository


@dataclass(slots=True)
class DuplicateCheckResult:
    is_duplicate: bool
    reason: str = ""


def check_duplicate_candidates(
    folder_id: int | None,
    clause: BatchImportClause,
    existing_rows: list[dict],
) -> DuplicateCheckResult:
    """按同目录下 term + testContent 判断疑似重复。"""
    if folder_id is None:
        return DuplicateCheckResult(False, "")
    for row in existing_rows:
        if row.get("folder_id") != folder_id:
            continue
        if row.get("term") == clause.term and row.get("test_content") == clause.test_content:
            return DuplicateCheckResult(True, "同一归属文件夹下 term + testContent 相同")
    return DuplicateCheckResult(False, "")


class ChapterBatchService:
    """封装文档导入、默认值生成、重新拆分重置等本地业务。"""

    def __init__(self, repo: ChapterBatchRepository, output_root: Path | None = None):
        self._repo = repo
        self._output_root = output_root or (Path.home() / ".tuv-tools" / "chapter-batch")

    def import_documents(self, paths: list[str], split_mode: str) -> list[BatchImportDocument]:
        created: list[BatchImportDocument] = []
        for raw_path in paths:
            path = Path(raw_path)
            file_path = str(path.resolve()) if path.is_absolute() else str(path)
            file_name = path.name
            standard = _extract_standard_number(file_name) or ""
            fingerprint = sha1(file_path.encode("utf-8")).hexdigest()
            document = BatchImportDocument(
                file_path=file_path,
                file_name=file_name,
                file_fingerprint=fingerprint,
                document_status=DocumentStatus.PENDING_SPLIT.value,
                split_mode=split_mode,
                standard=standard,
                plan_sr="1",
                chapter_version="1.0",
            )
            document.id = self._repo.create_document(document)
            saved = self._repo.get_document(document.id)
            if saved is not None:
                created.append(saved)
        return created

    def import_and_split_documents(self, paths: list[str], split_mode: str) -> list[BatchImportDocument]:
        """导入文档后立即执行本地拆分，失败只落到对应文档记录。"""
        documents = self.import_documents(paths, split_mode)
        results: list[BatchImportDocument] = []
        for document in documents:
            if document.id is None:
                continue
            try:
                self.split_document(document.id)
            except Exception as exc:
                self._repo.update_document(
                    document.id,
                    document_status=DocumentStatus.FAILED.value,
                    last_error=str(exc),
                )
            saved = self._repo.get_document(document.id)
            if saved is not None:
                results.append(saved)
        return results

    def split_document(self, document_id: int) -> None:
        """按文档当前拆分模式生成本地 docx 和条款行。"""
        document = self._repo.get_document(document_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        self._repo.update_document(
            document_id,
            document_status=DocumentStatus.SPLITTING.value,
            last_error="",
        )
        docx_path = Path(document.file_path)
        sections = build_sections(docx_path)
        clean_patterns = AppSettings().load_inline_clean_patterns()
        doc_output_dir = self._output_root / str(document_id)
        if document.split_mode == SplitMode.SECTION.value:
            clauses = self._export_section_mode(
                docx_path,
                doc_output_dir,
                sections,
                clean_patterns,
                document.standard,
            )
        else:
            clauses = self._export_clause_mode(docx_path, doc_output_dir, sections, clean_patterns)
        self._repo.replace_clauses(document_id, clauses)
        self._repo.update_document(
            document_id,
            document_status=DocumentStatus.PENDING_CONFIRM.value,
            total_clause_count=len(clauses),
            success_clause_count=0,
            failed_clause_count=0,
            skipped_clause_count=0,
            last_error="",
        )

    def _export_clause_mode(self, docx_path, output_dir, sections, clean_patterns) -> list[BatchImportClause]:
        output_dir = Path(output_dir) / "clauses_docx"
        used_names: dict[str, int] = {}
        clauses: list[BatchImportClause] = []
        for index, section in enumerate(sections):
            stem = safe_name(section.clause_id or f"clause_{index + 1}")
            used_names[stem] = used_names.get(stem, 0) + 1
            if used_names[stem] > 1:
                stem = safe_name(f"{stem}_{used_names[stem]}")
            output_path = output_dir / f"{stem}.docx"
            _write_docx_from_template(docx_path, output_path, [section], clean_patterns)
            clauses.append(
                BatchImportClause(
                    sort_index=index,
                    term=section.clause_id,
                    test_content=section.title or "null",
                    source_docx_path=str(output_path),
                )
            )
        return clauses

    def _export_section_mode(self, docx_path, output_dir, sections, clean_patterns, standard: str) -> list[BatchImportClause]:
        output_dir = Path(output_dir) / "versions_docx"
        grouped: dict[str, list] = {}
        for section in sections:
            grouped.setdefault(section.major_version, []).append(section)
        clauses: list[BatchImportClause] = []
        for index, (major_version, group_sections) in enumerate(grouped.items()):
            stem = safe_name(major_version or f"section_{index + 1}")
            output_path = output_dir / f"{stem}.docx"
            _write_docx_from_template(
                docx_path,
                output_path,
                group_sections,
                clean_patterns,
                collapse_shared_tables=True,
            )
            clauses.append(
                BatchImportClause(
                    sort_index=index,
                    term=major_version,
                    test_content=major_version or standard or "null",
                    source_docx_path=str(output_path),
                )
            )
        return clauses

    def mark_duplicate_candidates(self, document_id: int, existing_rows: list[dict]) -> list[int]:
        """标记同目录下 term + testContent 疑似重复的条款。"""
        document = self._repo.get_document(document_id)
        if document is None:
            return []
        duplicate_ids: list[int] = []
        for clause in self._repo.get_clauses(document_id):
            if clause.id is None:
                continue
            result = check_duplicate_candidates(document.folder_id, clause, existing_rows)
            self._repo.update_clause(
                clause.id,
                duplicate_flag=result.is_duplicate,
                duplicate_reason=result.reason,
            )
            if result.is_duplicate:
                duplicate_ids.append(clause.id)
        return duplicate_ids

    def reset_document_for_resplit(self, document_id: int, split_mode: str) -> None:
        current = self._repo.get_document(document_id)
        if current is None or is_document_running(current.document_status):
            return
        self._repo.replace_clauses(document_id, [])
        self._repo.update_document(
            document_id,
            split_mode=split_mode,
            document_status=DocumentStatus.PENDING_CONFIRM.value,
            total_clause_count=0,
            success_clause_count=0,
            failed_clause_count=0,
            skipped_clause_count=0,
            is_queued=0,
            queue_order=None,
            last_error="",
        )

    def save_confirmed_documents(self, document_updates: dict[int, dict]) -> list[int]:
        ready_ids: list[int] = []
        for document_id, fields in document_updates.items():
            current = self._repo.get_document(document_id)
            if current is None or is_document_running(current.document_status):
                continue
            payload = {
                "standard": fields.get("standard", ""),
                "folder_id": fields.get("folder_id"),
                "folder_name": fields.get("folder_name", ""),
                "product_type": fields.get("product_type", ""),
                "plan_sr": fields.get("plan_sr", ""),
                "standard_version": fields.get("standard_version", ""),
                "chapter_version": fields.get("chapter_version", ""),
                "specific_product": fields.get("specific_product", ""),
                "document_status": DocumentStatus.PENDING_CREATE.value,
            }
            self._repo.update_document(document_id, **payload)
            self._repo.reaggregate_document(document_id)
            ready_ids.append(document_id)
        return ready_ids
