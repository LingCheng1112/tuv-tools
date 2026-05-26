"""Chapter 批量上传工作台本地业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

from tuv_tools.config.database import _extract_standard_number
from tuv_tools.config.settings import AppSettings
from tuv_tools.core.chapter.api import get_folders
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.splitter.exporting import _write_docx_from_template
from tuv_tools.core.splitter.parsing import build_sections
from tuv_tools.core.splitter.ui_helpers import extract_clause_test_content
from tuv_tools.core.splitter.utils import safe_name

from .models import (
    BatchImportClause,
    BatchImportDocument,
    DocumentStatus,
    SplitMode,
    is_document_running,
)
from .repository import ChapterBatchRepository

CHAPTER_ROOT_FOLDER_ID = 2


@dataclass(slots=True)
class DuplicateCheckResult:
    is_duplicate: bool
    reason: str = ""


def _same_specific_product(left: str | None, right: str | None) -> bool:
    """按业务约定比较 specific_product，空值只与空值相等。"""
    left_value = (left or "").strip()
    right_value = (right or "").strip()
    if not left_value and not right_value:
        return True
    if not left_value or not right_value:
        return False
    return left_value == right_value


def find_duplicate_candidate_row(
    folder_id: int | None,
    clause: BatchImportClause,
    specific_product: str,
    existing_rows: list[dict],
) -> dict | None:
    """返回命中的重复后端条款行。"""
    if folder_id is None:
        return None
    for row in existing_rows:
        if row.get("folder_id") != folder_id:
            continue
        if row.get("term") != clause.term:
            continue
        if row.get("test_content") != clause.test_content:
            continue
        if not _same_specific_product(row.get("specific_product"), specific_product):
            continue
        return row
    return None


def check_duplicate_candidates(
    folder_id: int | None,
    clause: BatchImportClause,
    specific_product: str,
    existing_rows: list[dict],
) -> DuplicateCheckResult:
    """按同目录下 folder + term + testContent + specific_product 判重。"""
    row = find_duplicate_candidate_row(folder_id, clause, specific_product, existing_rows)
    if row is not None:
        return DuplicateCheckResult(True, "同一归属文件夹下 term + testContent + specificProduct 相同")
    return DuplicateCheckResult(False, "")


class ChapterBatchService:
    """封装导入、拆分、判重、保存确认等本地业务。"""

    def __init__(self, repo: ChapterBatchRepository, output_root: Path | None = None):
        self._repo = repo
        self._output_root = output_root or (Path.home() / ".tuv-tools" / "chapter-batch")
        self._folder_context_cache: dict[str, tuple[int, str, str]] = {}

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
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard=standard,
                plan_sr="1",
                chapter_version="1.0",
            )
            self._apply_default_folder_context(document)
            document.id = self._repo.create_document(document)
            saved = self._repo.get_document(document.id)
            if saved is not None:
                created.append(saved)
        return created

    def _apply_default_folder_context(self, document: BatchImportDocument) -> None:
        standard = (document.standard or "").strip()
        if not standard:
            return
        context = self._resolve_folder_context_for_standard(standard)
        if context is None:
            return
        folder_id, folder_name, product_type = context
        document.folder_id = folder_id
        document.folder_name = folder_name
        document.product_type = product_type or document.product_type or "家电"

    def _resolve_folder_context_for_standard(self, standard: str) -> tuple[int, str, str] | None:
        cached = self._folder_context_cache.get(standard)
        if cached is not None:
            return cached
        nodes = self._load_full_folder_tree()
        if not nodes:
            return None

        node_map = {node.id: node for node in nodes}
        target = next((node for node in nodes if node.folder_name.strip() == standard), None)
        if target is None:
            return None

        product_type = "家电"
        category_node = target
        while category_node.pid != CHAPTER_ROOT_FOLDER_ID:
            parent = node_map.get(category_node.pid) if category_node.pid is not None else None
            if parent is None:
                break
            category_node = parent
        if category_node.pid == CHAPTER_ROOT_FOLDER_ID and category_node.folder_name.strip():
            product_type = category_node.folder_name.strip()

        result = (target.id, target.folder_name, product_type)
        self._folder_context_cache[standard] = result
        return result

    def _load_full_folder_tree(self) -> list:
        try:
            config = AppSettings().load_api_config()
            if config is None:
                return []
            client = TuvClient(config.base_url, config.request_timeout)
            if not auto_login(client, config):
                return []
        except Exception:
            return []

        results = []
        queue = [CHAPTER_ROOT_FOLDER_ID]
        visited: set[int] = set()
        while queue:
            pid = queue.pop(0)
            if pid in visited:
                continue
            visited.add(pid)
            try:
                children = get_folders(client, pid=pid)
            except Exception:
                continue
            for child in children:
                results.append(child)
                if child.has_children:
                    queue.append(child.id)
        return results

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
                    test_content=extract_clause_test_content(section.title) or "null",
                    source_docx_path=str(output_path),
                )
            )
        return clauses

    def _export_section_mode(
        self,
        docx_path,
        output_dir,
        sections,
        clean_patterns,
        standard: str,
    ) -> list[BatchImportClause]:
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
        """标记同目录下疑似重复的条款。"""
        document = self._repo.get_document(document_id)
        if document is None:
            return []
        duplicate_ids: list[int] = []
        for clause in self._repo.get_clauses(document_id):
            if clause.id is None:
                continue
            result = check_duplicate_candidates(
                document.folder_id,
                clause,
                document.specific_product,
                existing_rows,
            )
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
                "document_status": DocumentStatus.PENDING_UPLOAD.value,
            }
            self._repo.update_document(document_id, **payload)
            self._repo.reaggregate_document(document_id)
            ready_ids.append(document_id)
        return ready_ids
