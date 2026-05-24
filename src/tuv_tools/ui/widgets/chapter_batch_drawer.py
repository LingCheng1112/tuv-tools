"""Chapter 批量导入工作台右侧抽屉。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.core.chapter_batch.models import BatchImportDocument
from .chapter_batch_clause_table import ChapterBatchClauseTable
from .chapter_batch_document_form import ChapterBatchDocumentForm


class ChapterBatchDrawer(QWidget):
    """最小右侧抽屉壳体，支持单文档或多文档标签切换。"""

    document_selected = Signal(int)
    save_confirm_requested = Signal(list)
    clause_action_requested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._documents: list[BatchImportDocument] = []
        self._document_id_to_row: dict[int, int] = {}
        self._document_field_cache: dict[int, dict] = {}
        self._clause_field_cache: dict[int, dict[int, dict]] = {}
        self._active_document_id: int | None = None
        self.setWindowFlags(Qt.Widget)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = QLabel("文档详情")
        self._title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self._title)
        header.addStretch()
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.hide)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._tabs = QListWidget()
        self._tabs.setMaximumHeight(72)
        self._tabs.currentRowChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._document_form = ChapterBatchDocumentForm(self)
        layout.addWidget(self._document_form)

        self._clause_table = ChapterBatchClauseTable(self)
        self._clause_table.action_requested.connect(self.clause_action_requested)
        layout.addWidget(self._clause_table, stretch=1)

        button_row = QHBoxLayout()
        self._save_btn = QPushButton("保存确认")
        self._save_btn.clicked.connect(self._emit_save_confirm)
        button_row.addWidget(self._save_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

    def set_documents(self, documents: list[BatchImportDocument]) -> None:
        if self._active_document_id is not None:
            self._cache_current_document_fields()
        self._documents = documents
        self._document_id_to_row = {document.id: idx for idx, document in enumerate(documents) if document.id is not None}
        self._tabs.clear()
        for document in documents:
            self._tabs.addItem(QListWidgetItem(document.file_name))
        if documents:
            self._tabs.setCurrentRow(0)
            self._update_summary(documents[0])

    def _on_tab_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._documents):
            return
        self._cache_current_document_fields()
        self._cache_current_clause_fields()
        document = self._documents[row]
        self._update_summary(document)
        self._active_document_id = document.id
        if document.id is not None:
            self.document_selected.emit(document.id)

    def _update_summary(self, document: BatchImportDocument) -> None:
        self._title.setText(document.file_name or "文档详情")
        self._summary.setText(
            f"状态：{document.document_status} | 模式：{document.split_mode} | 标准：{document.standard or '(空)'}"
        )
        self._document_form.load_document(self._document_field_cache.get(document.id or -1, {
            "standard": document.standard,
            "folder_id": document.folder_id,
            "folder_name": document.folder_name,
            "product_type": document.product_type,
            "plan_sr": document.plan_sr,
            "standard_version": document.standard_version,
            "chapter_version": document.chapter_version,
            "specific_product": document.specific_product,
        }))
        self._clause_table.load_clauses([])
        self._active_document_id = document.id

    def current_document(self) -> BatchImportDocument | None:
        row = self._tabs.currentRow()
        if row < 0 or row >= len(self._documents):
            return None
        return self._documents[row]

    def _emit_save_confirm(self) -> None:
        document = self.current_document()
        if document is None:
            QMessageBox.information(self, "保存确认", "请先选择一个文档。")
            return
        self._cache_current_clause_fields()
        self.save_confirm_requested.emit([doc.id for doc in self._documents if doc.id is not None])

    def current_document_fields(self) -> dict:
        return self._document_form.to_document_fields()

    def document_fields(self, document_id: int) -> dict:
        if self._active_document_id == document_id:
            self._cache_current_document_fields()
        return self._document_field_cache.get(document_id, self._document_form.to_document_fields())

    def all_document_fields(self) -> dict[int, dict]:
        self._cache_current_document_fields()
        result = {}
        for document in self._documents:
            if document.id is None:
                continue
            result[document.id] = self._document_field_cache.get(document.id, self._document_form.to_document_fields())
        return result

    def _cache_current_document_fields(self) -> None:
        if self._active_document_id is None:
            return
        self._document_field_cache[self._active_document_id] = self._document_form.to_document_fields()

    def set_clauses(self, clauses: list[dict]) -> None:
        self._clause_table.load_clauses(clauses)

    def set_edit_locked(self, locked: bool) -> None:
        self._save_btn.setEnabled(not locked)
        self._document_form.set_readonly(locked)

    def all_clause_fields(self) -> dict[int, dict[int, dict]]:
        self._cache_current_clause_fields()
        result = {}
        for document_id, fields in self._clause_field_cache.items():
            result[document_id] = fields
        return result

    def clear_clause_cache(self, document_id: int | None = None) -> None:
        if document_id is None:
            self._clause_field_cache.clear()
            return
        self._clause_field_cache.pop(document_id, None)

    def retain_clause_cache(self, document_id: int, clause_ids: set[int]) -> None:
        cached = self._clause_field_cache.get(document_id)
        if cached is None:
            return
        retained = {clause_id: fields for clause_id, fields in cached.items() if clause_id in clause_ids}
        if retained:
            self._clause_field_cache[document_id] = retained
            return
        self._clause_field_cache.pop(document_id, None)

    def _cache_current_clause_fields(self) -> None:
        if self._active_document_id is None:
            return
        self._clause_field_cache[self._active_document_id] = self._clause_table.to_clause_updates()
