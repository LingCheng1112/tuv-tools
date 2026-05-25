"""Chapter 批量导入条款明细表。"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QMenu,
    QStyle,
    QStyleOptionButton,
    QTableWidget,
    QTableWidgetItem,
)

from tuv_tools.core.chapter_batch.models import ClauseStatus


VIEW_ONLY_ACTIONS = {"打开本地 docx", "打开后端 chapter 记录"}


class ChapterBatchClauseTable(QTableWidget):
    """展示某个文档下的条款明细。"""

    COL_CHECK = 0
    COL_TERM = 1
    COL_CONTENT = 2
    COL_STATUS = 3
    COL_CHAPTER_ID = 4

    action_requested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["", "条款编号", "测试内容", "状态", "chapter ID"])
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._header = _ClauseCheckHeader(Qt.Orientation.Horizontal, self)
        self._header.toggled.connect(self.set_all_checked)
        self.setHorizontalHeader(self._header)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setStyleSheet(
            """
            QTableWidget {
                background-color: #25272b;
                alternate-background-color: #2b2e33;
                color: #d7dce2;
                border: 1px solid #3b3e43;
                border-radius: 8px;
                font-size: 13px;
                gridline-color: transparent;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #3b4a5c;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #25272b;
                color: #99a2ad;
                border: none;
                border-bottom: 1px solid #3b3e43;
                padding: 8px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            """
        )
        header = self.horizontalHeader()
        self.setColumnWidth(self.COL_CHECK, 36)
        header.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_TERM, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_CONTENT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_CHAPTER_ID, QHeaderView.ResizeMode.ResizeToContents)

    def load_clauses(self, clauses: list[dict]) -> None:
        self.setRowCount(len(clauses))
        for row, clause in enumerate(clauses):
            editable = clause.get("editable", True)
            readonly_reason = clause.get("readonly_reason", "")
            clause_id = clause.get("id")

            checkbox = QCheckBox()
            checkbox.setStyleSheet("margin-left: 8px;")
            checkbox.setChecked(bool(clause.get("checked", True)))
            checkbox.toggled.connect(self._sync_header_state)
            self.setCellWidget(row, self.COL_CHECK, checkbox)

            term_item = QTableWidgetItem(clause.get("term", ""))
            term_item.setData(Qt.ItemDataRole.UserRole, clause_id)
            term_item.setData(Qt.ItemDataRole.UserRole + 1, editable)
            if not editable:
                term_item.setFlags(term_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, self.COL_TERM, term_item)

            content_item = QTableWidgetItem(clause.get("test_content", ""))
            if not editable:
                content_item.setFlags(content_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, self.COL_CONTENT, content_item)

            status_item = QTableWidgetItem(clause.get("clause_status", ""))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, self.COL_STATUS, status_item)

            chapter_item = QTableWidgetItem(str(clause.get("chapter_id") or ""))
            chapter_item.setFlags(chapter_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            chapter_item.setToolTip(str(clause.get("chapter_id") or ""))
            self.setItem(row, self.COL_CHAPTER_ID, chapter_item)

            term_item.setData(Qt.ItemDataRole.UserRole + 2, clause.get("duplicate_flag", False))
            term_item.setData(Qt.ItemDataRole.UserRole + 3, clause.get("duplicate_reason", ""))
            term_item.setData(Qt.ItemDataRole.UserRole + 4, clause.get("create_error", ""))
            term_item.setData(Qt.ItemDataRole.UserRole + 5, clause.get("upload_error", ""))
            term_item.setData(Qt.ItemDataRole.UserRole + 6, readonly_reason)
        self._sync_header_state()

    def to_clause_updates(self) -> dict[int, dict]:
        updates: dict[int, dict] = {}
        for row in range(self.rowCount()):
            term_item = self.item(row, self.COL_TERM)
            content_item = self.item(row, self.COL_CONTENT)
            if term_item is None:
                continue
            clause_id = term_item.data(Qt.ItemDataRole.UserRole)
            if clause_id is None:
                continue
            updates[int(clause_id)] = {
                "term": term_item.text().strip(),
                "test_content": content_item.text().strip() if content_item is not None else "",
            }
        return updates

    def checked_clause_ids(self) -> list[int]:
        clause_ids: list[int] = []
        for row in range(self.rowCount()):
            checkbox = self.cellWidget(row, self.COL_CHECK)
            term_item = self.item(row, self.COL_TERM)
            if not isinstance(checkbox, QCheckBox) or not checkbox.isChecked() or term_item is None:
                continue
            clause_id = term_item.data(Qt.ItemDataRole.UserRole)
            if clause_id is not None:
                clause_ids.append(int(clause_id))
        return clause_ids

    def set_all_checked(self, checked: bool) -> None:
        for row in range(self.rowCount()):
            checkbox = self.cellWidget(row, self.COL_CHECK)
            if not isinstance(checkbox, QCheckBox):
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._sync_header_state()

    def set_checked_clause_ids(self, clause_ids: list[int]) -> None:
        wanted = {int(clause_id) for clause_id in clause_ids}
        for row in range(self.rowCount()):
            checkbox = self.cellWidget(row, self.COL_CHECK)
            term_item = self.item(row, self.COL_TERM)
            if not isinstance(checkbox, QCheckBox) or term_item is None:
                continue
            clause_id = term_item.data(Qt.ItemDataRole.UserRole)
            checkbox.blockSignals(True)
            checkbox.setChecked(clause_id is not None and int(clause_id) in wanted)
            checkbox.blockSignals(False)
        self._sync_header_state()

    def available_actions_for_status(self, status: str, editable: bool = True) -> list[str]:
        if status == ClauseStatus.CREATE_FAILED.value:
            actions = ["重试创建", "上传", "打开本地 docx"]
        elif status == ClauseStatus.UPLOAD_FAILED.value:
            actions = ["重试上传", "上传", "打开本地 docx", "打开后端 chapter 记录"]
        elif status == ClauseStatus.SKIPPED.value:
            actions = ["恢复跳过", "打开本地 docx"]
        elif status == ClauseStatus.PENDING_UPLOAD.value:
            actions = ["重试上传", "上传", "打开本地 docx", "打开后端 chapter 记录"]
        elif status == ClauseStatus.PENDING_CREATE.value:
            actions = ["上传", "打开本地 docx"]
        else:
            actions = ["打开本地 docx"]
        actions.append("查看错误信息")
        if editable:
            return actions
        return [action for action in actions if action in VIEW_ONLY_ACTIONS or action == "查看错误信息"]

    def _sync_header_state(self) -> None:
        total = self.rowCount()
        checked = len(self.checked_clause_ids())
        self._header.set_checked(total > 0 and checked == total)

    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0:
            return
        term_item = self.item(row, self.COL_TERM)
        status_item = self.item(row, self.COL_STATUS)
        if term_item is None or status_item is None:
            return
        clause_id = term_item.data(Qt.ItemDataRole.UserRole)
        if clause_id is None:
            return
        editable = bool(term_item.data(Qt.ItemDataRole.UserRole + 1))
        menu = QMenu(self)
        for action_name in self.available_actions_for_status(status_item.text(), editable):
            action = menu.addAction(action_name)
            action.triggered.connect(
                lambda _checked=False, name=action_name, cid=int(clause_id): self.action_requested.emit(name, cid)
            )
        menu.exec(self.viewport().mapToGlobal(pos))


class _ClauseCheckHeader(QHeaderView):
    """条款勾选表头。"""

    toggled = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._checked = False
        self.setSectionsClickable(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        logical_index = self.logicalIndexAt(event.position().toPoint())
        if logical_index == ChapterBatchClauseTable.COL_CHECK:
            self._checked = not self._checked
            self.toggled.emit(self._checked)
            self.viewport().update()
            return
        super().mousePressEvent(event)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        if logical_index != ChapterBatchClauseTable.COL_CHECK:
            return
        option = QStyleOptionButton()
        indicator_w = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, self)
        indicator_h = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, option, self)
        option.rect = QRect(
            rect.x() + (rect.width() - indicator_w) // 2,
            rect.y() + (rect.height() - indicator_h) // 2,
            indicator_w,
            indicator_h,
        )
        option.state = QStyle.StateFlag.State_Enabled
        option.state |= QStyle.StateFlag.State_On if self._checked else QStyle.StateFlag.State_Off
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
        self.viewport().update()
