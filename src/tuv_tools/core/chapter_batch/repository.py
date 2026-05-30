"""Chapter 批量导入工作台本地 repository。"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any

from tuv_tools.config import AppSettings
from tuv_tools.config.database import DatabaseManager
from tuv_tools.config.settings import CHAPTER_BATCH_DIR_NAME
from .models import (
    BatchImportClause,
    BatchImportDocument,
    ClauseStatus,
    DocumentStatus,
    normalize_clause_source_docx_path,
    resolve_clause_source_docx_path,
)

_LEGACY_DOCUMENT_STATUS_MAP = {
    "\u5f85\u62c6\u5206": DocumentStatus.PREPARING.value,
    "\u5f85\u521b\u5efa": DocumentStatus.PENDING_UPLOAD.value,
    "\u521b\u5efa\u4e2d": DocumentStatus.UPLOADING.value,
    "\u5df2\u8df3\u8fc7": DocumentStatus.PENDING_UPLOAD.value,
}

_LEGACY_CLAUSE_STATUS_MAP = {
    "\u5f85\u521b\u5efa": ClauseStatus.PENDING_UPLOAD.value,
    "\u521b\u5efa\u5931\u8d25": ClauseStatus.UPLOAD_FAILED.value,
    "\u7528\u6237\u8df3\u8fc7": ClauseStatus.PENDING_UPLOAD.value,
    "\u91cd\u590d\u8df3\u8fc7": ClauseStatus.PENDING_UPLOAD.value,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_document_status(status: str | None) -> str | None:
    if status is None:
        return None
    return _LEGACY_DOCUMENT_STATUS_MAP.get(status, status)


def _normalize_clause_status(status: str | None) -> str | None:
    if status is None:
        return None
    return _LEGACY_CLAUSE_STATUS_MAP.get(status, status)


def _normalize_document_row(data: dict[str, Any]) -> dict[str, Any]:
    data["document_status"] = _normalize_document_status(data.get("document_status"))
    data["is_queued"] = bool(data.get("is_queued", 0))
    return data


def _normalize_clause_row(data: dict[str, Any]) -> dict[str, Any]:
    data["clause_status"] = _normalize_clause_status(data.get("clause_status"))
    data["duplicate_flag"] = bool(data.get("duplicate_flag", 0))
    return data


class ChapterBatchRepository:
    """封装 Chapter 批量导入工作台的 SQLite 访问。"""

    def __init__(self, db: DatabaseManager):
        self._db = db
        self._chapter_batch_root = self._resolve_chapter_batch_root()

    def _resolve_chapter_batch_root(self):
        db_path = self._db._db_path.resolve()
        settings = AppSettings()
        if db_path == settings.get_database_path().resolve():
            return settings.get_chapter_batch_output_root()
        return db_path.parent / CHAPTER_BATCH_DIR_NAME

    @property
    def _conn(self):
        return self._db._conn

    def _normalize_clause_path_for_storage(self, source_docx_path: str) -> str:
        return normalize_clause_source_docx_path(source_docx_path, self._chapter_batch_root)

    def _resolve_clause_path_for_runtime(self, source_docx_path: str) -> str:
        return resolve_clause_source_docx_path(source_docx_path, self._chapter_batch_root)

    def create_document(self, document: BatchImportDocument) -> int:
        now = _now()
        cur = self._conn.execute(
            """
            INSERT INTO batch_import_documents (
                file_path, file_name, file_fingerprint, document_status, split_mode,
                standard, folder_id, folder_name, product_type, plan_sr,
                standard_version, chapter_version, specific_product,
                total_clause_count, success_clause_count, failed_clause_count,
                skipped_clause_count, is_queued, queue_order, last_error,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.file_path,
                document.file_name,
                document.file_fingerprint,
                _normalize_document_status(document.document_status),
                document.split_mode,
                document.standard,
                document.folder_id,
                document.folder_name,
                document.product_type,
                document.plan_sr,
                document.standard_version,
                document.chapter_version,
                document.specific_product,
                document.total_clause_count,
                document.success_clause_count,
                document.failed_clause_count,
                document.skipped_clause_count,
                int(document.is_queued),
                document.queue_order,
                document.last_error,
                now,
                now,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_document(self, document_id: int) -> BatchImportDocument | None:
        row = self._conn.execute(
            "SELECT * FROM batch_import_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        data = _normalize_document_row(dict(row))
        allowed = {item.name for item in fields(BatchImportDocument)}
        return BatchImportDocument(**{key: data.get(key) for key in allowed})

    def list_documents(
        self,
        *,
        status: str | None = None,
        keyword: str = "",
        split_mode: str | None = None,
    ) -> list[BatchImportDocument]:
        sql = ["SELECT * FROM batch_import_documents WHERE 1 = 1"]
        params: list[Any] = []
        if status and status != "全部":
            if status == DocumentStatus.PENDING_UPLOAD.value:
                sql.append("AND document_status IN (?, ?)")
                params.extend([DocumentStatus.PENDING_UPLOAD.value, DocumentStatus.PENDING_CONFIRM.value])
            else:
                sql.append("AND document_status = ?")
                params.append(status)
        if split_mode and split_mode != "全部":
            sql.append("AND split_mode = ?")
            params.append(split_mode)
        normalized = keyword.strip()
        if normalized:
            sql.append("AND (file_name LIKE ? OR standard LIKE ?)")
            like = f"%{normalized}%"
            params.extend([like, like])
        sql.append("ORDER BY updated_at DESC, id DESC")
        rows = self._conn.execute(" ".join(sql), params).fetchall()
        allowed = {item.name for item in fields(BatchImportDocument)}
        results: list[BatchImportDocument] = []
        for row in rows:
            data = _normalize_document_row(dict(row))
            results.append(BatchImportDocument(**{key: data.get(key) for key in allowed}))
        return results

    def update_document(self, document_id: int, **fields_to_update: Any) -> None:
        if not fields_to_update:
            return
        if "document_status" in fields_to_update:
            fields_to_update["document_status"] = _normalize_document_status(
                fields_to_update["document_status"]
            )
        fields_to_update["updated_at"] = _now()
        columns = ", ".join(f"{key} = ?" for key in fields_to_update)
        values = list(fields_to_update.values()) + [document_id]
        self._conn.execute(
            f"UPDATE batch_import_documents SET {columns} WHERE id = ?",
            values,
        )
        self._conn.commit()

    def replace_clauses(self, document_id: int, clauses: list[BatchImportClause]) -> None:
        self._conn.execute(
            "DELETE FROM batch_import_clauses WHERE document_id = ?",
            (document_id,),
        )
        now = _now()
        for clause in clauses:
            self._conn.execute(
                """
                INSERT INTO batch_import_clauses (
                    document_id, sort_index, term, test_content, clause_status,
                    chapter_id, backend_chapter_status, source_docx_path,
                    duplicate_flag, duplicate_reason, user_decision,
                    create_error, upload_error, last_action, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    clause.sort_index,
                    clause.term,
                    clause.test_content,
                    _normalize_clause_status(clause.clause_status),
                    clause.chapter_id,
                    clause.backend_chapter_status,
                    self._normalize_clause_path_for_storage(clause.source_docx_path),
                    int(clause.duplicate_flag),
                    clause.duplicate_reason,
                    clause.user_decision,
                    clause.create_error,
                    clause.upload_error,
                    clause.last_action,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def get_clauses(self, document_id: int) -> list[BatchImportClause]:
        rows = self._conn.execute(
            """
            SELECT * FROM batch_import_clauses
            WHERE document_id = ?
            ORDER BY sort_index ASC, id ASC
            """,
            (document_id,),
        ).fetchall()
        allowed = {item.name for item in fields(BatchImportClause)}
        clauses: list[BatchImportClause] = []
        for row in rows:
            data = _normalize_clause_row(dict(row))
            data["source_docx_path"] = self._resolve_clause_path_for_runtime(
                data.get("source_docx_path", "")
            )
            clauses.append(BatchImportClause(**{key: data.get(key) for key in allowed}))
        return clauses

    def get_clause(self, clause_id: int) -> BatchImportClause | None:
        row = self._conn.execute(
            "SELECT * FROM batch_import_clauses WHERE id = ?",
            (clause_id,),
        ).fetchone()
        if row is None:
            return None
        data = _normalize_clause_row(dict(row))
        data["source_docx_path"] = self._resolve_clause_path_for_runtime(
            data.get("source_docx_path", "")
        )
        allowed = {item.name for item in fields(BatchImportClause)}
        return BatchImportClause(**{key: data.get(key) for key in allowed})

    def update_clause(self, clause_id: int, **fields_to_update: Any) -> None:
        if not fields_to_update:
            return
        if "clause_status" in fields_to_update:
            fields_to_update["clause_status"] = _normalize_clause_status(
                fields_to_update["clause_status"]
            )
        if "source_docx_path" in fields_to_update:
            fields_to_update["source_docx_path"] = self._normalize_clause_path_for_storage(
                fields_to_update["source_docx_path"]
            )
        fields_to_update["updated_at"] = _now()
        columns = ", ".join(f"{key} = ?" for key in fields_to_update)
        values = list(fields_to_update.values()) + [clause_id]
        self._conn.execute(
            f"UPDATE batch_import_clauses SET {columns} WHERE id = ?",
            values,
        )
        self._conn.commit()

    def delete_documents(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        self._conn.executemany(
            "DELETE FROM batch_import_documents WHERE id = ?",
            [(document_id,) for document_id in document_ids],
        )
        self._conn.commit()

    def clear_queued_flags(self) -> None:
        self._conn.execute(
            """
            UPDATE batch_import_documents
            SET is_queued = 0, updated_at = ?
            WHERE is_queued != 0
            """,
            (_now(),),
        )
        self._conn.commit()

    def reaggregate_document(self, document_id: int, *, forced_status: str | None = None) -> None:
        clauses = self.get_clauses(document_id)
        current = self.get_document(document_id)
        success = sum(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses)
        failed = sum(c.clause_status == ClauseStatus.UPLOAD_FAILED.value for c in clauses)
        skipped = 0

        if not clauses:
            status = (
                current.document_status
                if current is not None
                else DocumentStatus.PENDING_CONFIRM.value
            )
        elif clauses and all(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses):
            status = DocumentStatus.COMPLETED.value
        elif success > 0:
            status = DocumentStatus.PARTIAL.value
        elif any(c.clause_status == ClauseStatus.PENDING_UPLOAD.value for c in clauses):
            status = DocumentStatus.PENDING_UPLOAD.value
        elif any(c.clause_status == ClauseStatus.UPLOADING.value for c in clauses):
            status = DocumentStatus.UPLOADING.value
        elif failed > 0:
            status = DocumentStatus.FAILED.value
        else:
            status = DocumentStatus.PENDING_CONFIRM.value
        if forced_status is not None:
            status = _normalize_document_status(forced_status)

        self.update_document(
            document_id,
            document_status=status,
            total_clause_count=len(clauses),
            success_clause_count=success,
            failed_clause_count=failed,
            skipped_clause_count=skipped,
        )
