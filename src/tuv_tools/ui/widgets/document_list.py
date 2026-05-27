"""文档列表面板 — QTableWidget 封装，含勾选、右键菜单、拖拽导入"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from tuv_tools.core.splitter.ui_helpers import (
    STATUS_LABELS,
    blocks_batch_split,
    is_importable_docx,
    is_selectable_document_status,
)
from . import CHECKBOX_STYLE
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHeaderView,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

class DocumentTable(QTableWidget):
    """文档列表表格"""

    files_dropped = Signal(list)  # 拖拽导入文件路径
    checked_changed = Signal()  # 勾选变化
    split_requested = Signal(int)  # 请求拆分单条 (doc_id)
    resume_preparing_requested = Signal(int)  # 请求继续预处理 (doc_id)
    skip_preparing_split_requested = Signal(int)  # 请求跳过预处理并拆分 (doc_id)
    show_error_requested = Signal(int)  # 请求查看失败原因 (doc_id)
    open_output_requested = Signal(int)  # 请求打开输出目录 (doc_id)
    double_clicked = Signal(int)  # 双击行 (doc_id)
    standard_number_edited = Signal(int, str)  # 标准号编辑完成 (doc_id, standard_number)
    selection_empty = Signal()  # 列表为空时发出

    COL_CHECK = 0
    COL_FILE = 1
    COL_STANDARD = 2
    COL_STATUS = 3
    COL_COUNT = 4
    COL_SPLIT_AT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []
        self._checked: set[int] = set()

        self.setColumnCount(6)
        self.setHorizontalHeaderLabels([
            "", "文件名", "标准号", "状态", "条款数", "拆分时间"
        ])
        self.horizontalHeader().setSectionResizeMode(self.COL_FILE, QHeaderView.Stretch)
        self.setColumnWidth(self.COL_CHECK, 36)
        self.setColumnWidth(self.COL_STANDARD, 120)
        self.setColumnWidth(self.COL_STATUS, 130)
        self.setColumnWidth(self.COL_COUNT, 55)
        self.setColumnWidth(self.COL_SPLIT_AT, 145)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.cellDoubleClicked.connect(self._on_double_click)
        self.itemChanged.connect(self._on_item_changed)
        self._base_style = """
            QTableWidget {
                background-color: #2b2d30;
                alternate-background-color: #303336;
                color: #dcdcdc;
                border: none;
                font-size: 13px;
                outline: none;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #3c3f41;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2b2d30;
                color: #999;
                border: none;
                border-bottom: 2px solid #4a4d50;
                padding: 8px 10px;
                font-size: 12px;
                font-weight: bold;
            }
        """
        self.setStyleSheet(self._base_style)

        # 拖拽支持
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self._drag_files: list[str] = []
        self._suppress_item_changed = False

    # ---- 数据加载 ----

    def load_documents(self, docs: list[dict]) -> None:
        """加载文档列表数据"""
        self._suppress_item_changed = True
        self._data = docs
        self._checked.clear()
        self.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            self._build_row(row, doc)
        self._suppress_item_changed = False
        self.checked_changed.emit()

    @staticmethod
    def _make_item(text: str, tooltip: str = "") -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def _build_row(self, row: int, doc: dict) -> None:
        # 勾选框
        cb = QCheckBox()
        cb.setStyleSheet(CHECKBOX_STYLE)
        cb.setChecked(doc["id"] in self._checked)
        cb.toggled.connect(lambda checked, d=doc: self._on_toggle(d["id"], checked))
        can_select = is_selectable_document_status(doc["status"])
        cb.setEnabled(can_select)
        self.setCellWidget(row, self.COL_CHECK, cb)

        # 文件名
        file_name = doc["file_name"]
        file_missing = not os.path.exists(doc["file_path"])
        display_name = f"⚠ {file_name}" if file_missing else file_name
        self.setItem(row, self.COL_FILE,
                     self._make_item(display_name, "原文件不存在" if file_missing else file_name))

        # 标准号
        std_num = doc.get("standard_number") or "-"
        standard_item = self._make_item(std_num, "" if std_num == "-" else std_num)
        standard_item.setFlags(standard_item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_STANDARD, standard_item)

        # 状态
        status = doc.get("status", "pending")
        label = STATUS_LABELS.get(status, status)
        self.setItem(row, self.COL_STATUS, self._make_item(label, label))

        # 条款数
        count = doc.get("last_section_count")
        self.setItem(row, self.COL_COUNT, self._make_item(str(count) if count else "-"))

        # 拆分时间
        split_at = doc.get("last_split_at") or "-"
        display_time = split_at[:16] if len(split_at) > 16 else split_at
        self.setItem(row, self.COL_SPLIT_AT,
                     self._make_item(display_time, split_at if split_at != "-" else ""))

    def _on_double_click(self, row: int, col: int) -> None:
        if 0 <= row < len(self._data):
            if col == self.COL_STANDARD:
                item = self.item(row, col)
                if item is not None:
                    self.editItem(item)
                return
            self.double_clicked.emit(self._data[row]["id"])

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_item_changed or item.column() != self.COL_STANDARD:
            return
        row = item.row()
        if row < 0 or row >= len(self._data):
            return

        normalized = item.text().strip()
        if normalized == "-":
            normalized = ""

        doc = self._data[row]
        doc["standard_number"] = normalized or None

        display = normalized or "-"
        tooltip = normalized
        if item.text() != display or item.toolTip() != tooltip:
            self._suppress_item_changed = True
            item.setText(display)
            item.setToolTip(tooltip)
            self._suppress_item_changed = False

        self.standard_number_edited.emit(doc["id"], normalized)

    def _on_toggle(self, doc_id: int, checked: bool) -> None:
        if checked:
            self._checked.add(doc_id)
        else:
            self._checked.discard(doc_id)
        self.checked_changed.emit()

    def _delete_doc(self, doc_id: int) -> None:
        reply = QMessageBox.question(
            self, "确认删除",
            "是否删除此导入记录？（不会删除原始文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from tuv_tools.config.database import DatabaseManager
        DatabaseManager().delete_document(doc_id)
        self._checked.discard(doc_id)
        docs = DatabaseManager().get_documents()
        self.load_documents(docs)
        if not docs:
            self.selection_empty.emit()

    # ---- 右键菜单 ----

    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._data):
            return
        doc = self._data[row]
        menu = QMenu(self)

        if doc.get("status") == "prepare_paused":
            resume_action = QAction("继续预处理", self)
            resume_action.triggered.connect(lambda: self.resume_preparing_requested.emit(doc["id"]))
            menu.addAction(resume_action)

            skip_action = QAction("跳过预处理并拆分", self)
            skip_action.triggered.connect(
                lambda: self.skip_preparing_split_requested.emit(doc["id"])
            )
            menu.addAction(skip_action)
        elif doc.get("status") == "prepare_failed":
            retry_prepare_action = QAction("重新预处理", self)
            retry_prepare_action.triggered.connect(
                lambda: self.resume_preparing_requested.emit(doc["id"])
            )
            menu.addAction(retry_prepare_action)

            show_error_action = QAction("查看失败原因", self)
            show_error_action.triggered.connect(lambda: self.show_error_requested.emit(doc["id"]))
            menu.addAction(show_error_action)

            skip_action = QAction("跳过预处理并拆分", self)
            skip_action.triggered.connect(
                lambda: self.skip_preparing_split_requested.emit(doc["id"])
            )
            menu.addAction(skip_action)
        elif is_selectable_document_status(doc["status"]):
            split_action = QAction("拆分此文档", self)
            split_action.triggered.connect(lambda: self.split_requested.emit(doc["id"]))
            menu.addAction(split_action)
        elif doc.get("status") == "failed":
            retry_split_action = QAction("重新拆分此文档", self)
            retry_split_action.triggered.connect(lambda: self.split_requested.emit(doc["id"]))
            menu.addAction(retry_split_action)

            show_error_action = QAction("查看失败原因", self)
            show_error_action.triggered.connect(lambda: self.show_error_requested.emit(doc["id"]))
            menu.addAction(show_error_action)

        open_file_action = QAction("打开文件位置", self)
        open_file_action.triggered.connect(lambda: self._open_file_location(doc))
        menu.addAction(open_file_action)

        if doc.get("status") == "completed":
            open_output_action = QAction("打开输出目录", self)
            open_output_action.triggered.connect(lambda: self.open_output_requested.emit(doc["id"]))
            menu.addAction(open_output_action)

        copy_action = QAction("复制文件名", self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(doc["file_name"]))
        menu.addAction(copy_action)

        menu.addSeparator()
        delete_action = QAction("删除记录", self)
        delete_action.triggered.connect(lambda: self._delete_doc(doc["id"]))
        menu.addAction(delete_action)

        menu.exec(self.viewport().mapToGlobal(pos))

    def _open_file_location(self, doc: dict) -> None:
        file_dir = str(Path(doc["file_path"]).parent)
        if os.path.exists(file_dir):
            os.startfile(file_dir)

    # ---- 勾选状态 ----

    def checked_ids(self) -> list[int]:
        return list(self._checked)

    def checked_count(self) -> int:
        return len(self._checked)

    def total_count(self) -> int:
        return len(self._data)

    def checked_documents(self) -> list[dict]:
        return [doc for doc in self._data if doc["id"] in self._checked]

    def has_checked_batch_split_blockers(self) -> bool:
        return any(blocks_batch_split(doc.get("status", "pending")) for doc in self.checked_documents())

    def set_single_checked(self, doc_id: int) -> None:
        """仅勾选指定文档，取消其余"""
        self._checked.clear()
        doc = next((item for item in self._data if item["id"] == doc_id), None)
        if doc and is_selectable_document_status(doc.get("status", "pending")):
            self._checked.add(doc_id)
        self._rebuild_checkboxes()

    def set_all_checked(self, checked: bool) -> None:
        self._checked.clear()
        if checked:
            for doc in self._data:
                if is_selectable_document_status(doc.get("status", "pending")):
                    self._checked.add(doc["id"])
        self._rebuild_checkboxes()

    def update_row_status(self, doc_id: int, status: str, section_count: int | None = None) -> None:
        """就地更新指定文档的状态列和条款数列，避免全量刷新"""
        for row, doc in enumerate(self._data):
            if doc["id"] == doc_id:
                doc["status"] = status
                if section_count is not None:
                    doc["last_section_count"] = section_count
                label = STATUS_LABELS.get(status, status)
                self.setItem(row, self.COL_STATUS, self._make_item(label, label))
                existing_count = doc.get("last_section_count")
                count_text = str(existing_count) if existing_count else "-"
                self.setItem(row, self.COL_COUNT, self._make_item(count_text))
                cb = self.cellWidget(row, self.COL_CHECK)
                selection_changed = False
                if isinstance(cb, QCheckBox):
                    if not is_selectable_document_status(status) and doc_id in self._checked:
                        self._checked.discard(doc_id)
                        selection_changed = True
                    cb.blockSignals(True)
                    cb.setEnabled(is_selectable_document_status(status))
                    cb.setChecked(doc_id in self._checked)
                    cb.blockSignals(False)
                if selection_changed:
                    self.checked_changed.emit()
                break

    def _rebuild_checkboxes(self) -> None:
        for row, doc in enumerate(self._data):
            cb = self.cellWidget(row, self.COL_CHECK)
            if isinstance(cb, QCheckBox):
                cb.setChecked(doc["id"] in self._checked)

    # ---- 拖拽导入 ----

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._base_style + """
                QTableWidget { border: 2px dashed #4a9eff; }
            """)

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(self._base_style)

    def dropEvent(self, event) -> None:
        self.setStyleSheet(self._base_style)
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        self._drag_files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                for root, _dirs, files in os.walk(path):
                    for f in files:
                        if self._is_importable_docx(f):
                            self._drag_files.append(os.path.join(root, f))
            elif self._is_importable_docx(os.path.basename(path)):
                self._drag_files.append(path)

        if self._drag_files:
            unique_paths = sorted(dict.fromkeys(self._drag_files))
            self.files_dropped.emit(unique_paths)

    @staticmethod
    def _is_importable_docx(file_name: str) -> bool:
        return is_importable_docx(file_name)

    # ---- 搜索筛选 ----

    def filter_by_text(self, text: str) -> None:
        """按文件名/标准号筛选"""
        for row in range(self.rowCount()):
            if not text.strip():
                self.setRowHidden(row, False)
                continue
            match = False
            for col in (self.COL_FILE, self.COL_STANDARD):
                item = self.item(row, col)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            self.setRowHidden(row, not match)
