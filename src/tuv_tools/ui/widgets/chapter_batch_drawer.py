"""Chapter 批量上传工作台右侧抽屉。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.core.chapter.session import ChapterSessionManager
from tuv_tools.core.chapter_batch.models import BatchImportDocument, display_document_status
from .chapter_batch_clause_table import ChapterBatchClauseTable
from .chapter_batch_document_form import ChapterBatchDocumentForm


class ChapterBatchDrawer(QWidget):
    """单文档核对与上传抽屉。"""

    MIN_WIDTH = 560
    PREFERRED_WIDTH = 640
    MAX_WIDTH = 760
    WIDTH_RATIO = 0.46

    document_selected = Signal(int)
    save_requested = Signal(int)
    upload_requested = Signal(int, list)
    clause_action_requested = Signal(str, int)

    def __init__(self, parent=None, session_manager: ChapterSessionManager | None = None):
        super().__init__(parent)
        self._document_field_cache: dict[int, dict] = {}
        self._clause_field_cache: dict[int, dict[int, dict]] = {}
        self._saved_document_field_cache: dict[int, dict] = {}
        self._saved_clause_field_cache: dict[int, dict[int, dict]] = {}
        self._document: BatchImportDocument | None = None
        self._active_document_id: int | None = None
        self._drawer_width = self.PREFERRED_WIDTH
        self.setWindowFlags(Qt.Widget)
        self.setObjectName("chapterBatchDrawer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            #chapterBatchDrawer {
                background-color: rgba(19, 21, 24, 48);
            }
            #drawerPanel {
                background-color: #2b2d30;
                border-left: 1px solid #4a4d50;
            }
            """
        )
        self.setVisible(False)

        self._dismiss_zone = QWidget(self)
        self._dismiss_zone.installEventFilter(self)

        self._panel = QWidget(self)
        self._panel.setObjectName("drawerPanel")

        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = QLabel("文档详情")
        self._title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f1f3f5;")
        header.addWidget(self._title)
        header.addStretch()
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #c7ccd1;
                border: none;
                border-radius: 14px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3d41;
                color: #ffffff;
            }
            """
        )
        self._close_btn.clicked.connect(self.hide)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #b8bec6;")
        layout.addWidget(self._summary)

        self._document_form = ChapterBatchDocumentForm(self, session_manager=session_manager)
        layout.addWidget(self._document_form)

        self._clause_table = ChapterBatchClauseTable(self)
        self._clause_table.action_requested.connect(self.clause_action_requested)
        layout.addWidget(self._clause_table, stretch=1)

        button_row = QHBoxLayout()
        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._emit_save_requested)
        button_row.addWidget(self._save_btn)
        self._upload_btn = QPushButton("上传")
        self._upload_btn.clicked.connect(self._emit_upload_requested)
        button_row.addWidget(self._upload_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

    def preferred_width(self, available_width: int | None = None) -> int:
        if available_width is None and self.parentWidget() is not None:
            available_width = self.parentWidget().width()
        if available_width is None or available_width <= 0:
            return self.PREFERRED_WIDTH

        min_width = min(self.MIN_WIDTH, available_width)
        max_width = min(self.MAX_WIDTH, available_width)
        width = max(int(available_width * self.WIDTH_RATIO), self.PREFERRED_WIDTH)
        return max(min_width, min(width, max_width))

    def apply_layout(self, available_width: int, available_height: int) -> None:
        self._drawer_width = self.preferred_width(available_width)
        dismiss_width = max(0, available_width - self._drawer_width)
        self.setGeometry(0, 0, available_width, available_height)
        self._dismiss_zone.setGeometry(0, 0, dismiss_width, available_height)
        self._panel.setGeometry(dismiss_width, 0, self._drawer_width, available_height)

    def set_documents(self, documents: list[BatchImportDocument]) -> None:
        if self._active_document_id is not None:
            self._cache_current_document_fields()
            self._cache_current_clause_fields()
        self._document = documents[0] if documents else None
        if self._document is None:
            self._active_document_id = None
            self._summary.setText("")
            self._title.setText("文档详情")
            self._document_form.load_document({})
            self._clause_table.load_clauses([])
            return
        self._update_summary(self._document)
        if self._document.id is not None:
            self.document_selected.emit(self._document.id)

    def _update_summary(self, document: BatchImportDocument) -> None:
        self._title.setText(document.file_name or "文档详情")
        self._summary.setText(
            f"状态：{display_document_status(document.document_status)} | 模式：{document.split_mode} | 标准：{document.standard or '(空)'}"
        )
        fields = self._document_field_cache.get(
            document.id or -1,
            {
                "standard": document.standard,
                "folder_id": document.folder_id,
                "folder_name": document.folder_name,
                "product_type": document.product_type,
                "plan_sr": document.plan_sr,
                "standard_version": document.standard_version,
                "chapter_version": document.chapter_version,
                "specific_product": document.specific_product,
            },
        )
        self._document_form.load_document(fields)
        self._clause_table.load_clauses([])
        self._active_document_id = document.id
        if document.id is not None:
            self._saved_document_field_cache.setdefault(document.id, dict(fields))

    def current_document(self) -> BatchImportDocument | None:
        return self._document

    def _emit_save_requested(self) -> None:
        document = self.current_document()
        if document is None:
            QMessageBox.information(self, "保存", "请先选择一个文档。")
            return
        self._cache_current_clause_fields()
        self._cache_current_document_fields()
        if document.id is not None:
            self.save_requested.emit(document.id)

    def _emit_upload_requested(self) -> None:
        document = self.current_document()
        if document is None:
            QMessageBox.information(self, "上传", "请先选择一个文档。")
            return
        if document.id is None:
            return
        self._cache_current_clause_fields()
        self._cache_current_document_fields()
        clause_ids = self._clause_table.checked_clause_ids()
        self.upload_requested.emit(document.id, clause_ids)

    def current_document_fields(self) -> dict:
        return self._document_form.to_document_fields()

    def document_fields(self, document_id: int) -> dict:
        if self._active_document_id == document_id:
            self._cache_current_document_fields()
        return self._document_field_cache.get(document_id, self._document_form.to_document_fields())

    def all_document_fields(self) -> dict[int, dict]:
        self._cache_current_document_fields()
        result = {}
        document = self._document
        if document is not None and document.id is not None:
            result[document.id] = self._document_field_cache.get(document.id, self._document_form.to_document_fields())
        return result

    def mark_saved(self, document_id: int) -> None:
        self._cache_current_document_fields()
        self._cache_current_clause_fields()
        if document_id in self._document_field_cache:
            self._saved_document_field_cache[document_id] = dict(self._document_field_cache[document_id])
        if document_id in self._clause_field_cache:
            self._saved_clause_field_cache[document_id] = {
                clause_id: dict(fields) for clause_id, fields in self._clause_field_cache[document_id].items()
            }

    def is_dirty(self, document_id: int) -> bool:
        if self._active_document_id == document_id:
            self._cache_current_document_fields()
            self._cache_current_clause_fields()
        current_doc = self._document_field_cache.get(document_id, {})
        saved_doc = self._saved_document_field_cache.get(document_id, {})
        if current_doc != saved_doc:
            return True
        current_clauses = self._clause_field_cache.get(document_id, {})
        saved_clauses = self._saved_clause_field_cache.get(document_id, {})
        return current_clauses != saved_clauses

    def _cache_current_document_fields(self) -> None:
        if self._active_document_id is None:
            return
        self._document_field_cache[self._active_document_id] = self._document_form.to_document_fields()

    def set_clauses(self, clauses: list[dict]) -> None:
        self._clause_table.load_clauses(clauses)
        if self._active_document_id is not None:
            current = self._clause_table.to_clause_updates()
            self._clause_field_cache[self._active_document_id] = current
            self._saved_clause_field_cache.setdefault(
                self._active_document_id,
                {clause_id: dict(fields) for clause_id, fields in current.items()},
            )

    def set_edit_locked(self, locked: bool) -> None:
        self._save_btn.setEnabled(not locked)
        self._upload_btn.setEnabled(not locked)
        self._document_form.set_readonly(locked)

    def checked_clause_ids(self) -> list[int]:
        return self._clause_table.checked_clause_ids()

    def all_clause_fields(self) -> dict[int, dict[int, dict]]:
        self._cache_current_clause_fields()
        result = {}
        for document_id, fields in self._clause_field_cache.items():
            result[document_id] = fields
        return result

    def clear_clause_cache(self, document_id: int | None = None) -> None:
        if document_id is None:
            self._clause_field_cache.clear()
            self._saved_clause_field_cache.clear()
            return
        self._clause_field_cache.pop(document_id, None)
        self._saved_clause_field_cache.pop(document_id, None)

    def retain_clause_cache(self, document_id: int, clause_ids: set[int]) -> None:
        cached = self._clause_field_cache.get(document_id)
        if cached is None:
            return
        retained = {clause_id: fields for clause_id, fields in cached.items() if clause_id in clause_ids}
        if retained:
            self._clause_field_cache[document_id] = retained
            saved = self._saved_clause_field_cache.get(document_id, {})
            self._saved_clause_field_cache[document_id] = {
                clause_id: fields for clause_id, fields in saved.items() if clause_id in clause_ids
            }
            return
        self._clause_field_cache.pop(document_id, None)
        self._saved_clause_field_cache.pop(document_id, None)

    def _cache_current_clause_fields(self) -> None:
        if self._active_document_id is None:
            return
        self._clause_field_cache[self._active_document_id] = self._clause_table.to_clause_updates()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._dismiss_zone and event.type() == QEvent.Type.MouseButtonPress:
            self.hide()
            return True
        return super().eventFilter(watched, event)
