"""Chapter 批量导入工作台本地 repository。"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any

from tuv_tools.config.database import DatabaseManager
from .models import (
    BatchImportClause,
    BatchImportDocument,
    ClauseStatus,
    DocumentStatus,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ChapterBatchRepository:
    """封装 Chapter 批量导入工作台的 SQLite 访问。"""

    def __init__(self, db: DatabaseManager):
        self._db = db

    @property
    def _conn(self):
        return self._db._conn

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
                document.document_status,
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
        data = dict(row)
        data["is_queued"] = bool(data.get("is_queued", 0))
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
            data = dict(row)
            data["is_queued"] = bool(data.get("is_queued", 0))
            results.append(BatchImportDocument(**{key: data.get(key) for key in allowed}))
        return results

    def update_document(self, document_id: int, **fields_to_update: Any) -> None:
        if not fields_to_update:
            return
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
                    clause.clause_status,
                    clause.chapter_id,
                    clause.backend_chapter_status,
                    clause.source_docx_path,
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
            data = dict(row)
            data["duplicate_flag"] = bool(data.get("duplicate_flag", 0))
            clauses.append(BatchImportClause(**{key: data.get(key) for key in allowed}))
        return clauses

    def get_clause(self, clause_id: int) -> BatchImportClause | None:
        row = self._conn.execute(
            "SELECT * FROM batch_import_clauses WHERE id = ?",
            (clause_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["duplicate_flag"] = bool(data.get("duplicate_flag", 0))
        allowed = {item.name for item in fields(BatchImportClause)}
        return BatchImportClause(**{key: data.get(key) for key in allowed})

    def update_clause(self, clause_id: int, **fields_to_update: Any) -> None:
        if not fields_to_update:
            return
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

    def reaggregate_document(self, document_id: int, *, forced_status: str | None = None) -> None:
        clauses = self.get_clauses(document_id)
        current = self.get_document(document_id)
        success = sum(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses)
        failed = sum(
            c.clause_status in {ClauseStatus.CREATE_FAILED.value, ClauseStatus.UPLOAD_FAILED.value}
            for c in clauses
        )
        skipped = sum(c.clause_status == ClauseStatus.SKIPPED.value for c in clauses)

        if not clauses and current is not None and current.document_status == DocumentStatus.PENDING_CREATE.value:
            status = DocumentStatus.PENDING_CREATE.value
        elif clauses and all(c.clause_status == ClauseStatus.UPLOAD_SUCCESS.value for c in clauses):
            status = DocumentStatus.COMPLETED.value
        elif success > 0:
            status = DocumentStatus.PARTIAL.value
        elif any(c.clause_status == ClauseStatus.PENDING_UPLOAD.value for c in clauses):
            status = DocumentStatus.PENDING_UPLOAD.value
        elif any(c.clause_status == ClauseStatus.PENDING_CREATE.value for c in clauses):
            status = DocumentStatus.PENDING_CREATE.value
        elif failed > 0:
            status = DocumentStatus.FAILED.value
        else:
            status = DocumentStatus.PENDING_CONFIRM.value
        if forced_status is not None:
            status = forced_status

        self.update_document(
            document_id,
            document_status=status,
            total_clause_count=len(clauses),
            success_clause_count=success,
            failed_clause_count=failed,
            skipped_clause_count=skipped,
        )
