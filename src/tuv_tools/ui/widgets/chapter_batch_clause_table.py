"""Chapter 批量导入条款明细表。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QTableWidget, QTableWidgetItem

from tuv_tools.core.chapter_batch.models import ClauseStatus


class ChapterBatchClauseTable(QTableWidget):
    """展示某个文档下的条款明细。"""

    action_requested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(["条款编号", "测试内容", "状态", "chapter ID", "重复", "错误信息"])
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def load_clauses(self, clauses: list[dict]) -> None:
        self.setRowCount(len(clauses))
        for row, clause in enumerate(clauses):
            term_item = QTableWidgetItem(clause.get("term", ""))
            term_item.setData(Qt.ItemDataRole.UserRole, clause.get("id"))
            self.setItem(row, 0, term_item)
            self.setItem(row, 1, QTableWidgetItem(clause.get("test_content", "")))
            status_item = QTableWidgetItem(clause.get("clause_status", ""))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 2, status_item)
            chapter_item = QTableWidgetItem(str(clause.get("chapter_id") or ""))
            chapter_item.setFlags(chapter_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 3, chapter_item)
            duplicate_item = QTableWidgetItem("是" if clause.get("duplicate_flag") else "")
            duplicate_item.setFlags(duplicate_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 4, duplicate_item)
            error_text = clause.get("create_error") or clause.get("upload_error") or clause.get("duplicate_reason") or ""
            error_item = QTableWidgetItem(error_text)
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 5, error_item)

    def to_clause_updates(self) -> dict[int, dict]:
        updates: dict[int, dict] = {}
        for row in range(self.rowCount()):
            term_item = self.item(row, 0)
            content_item = self.item(row, 1)
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

    def available_actions_for_status(self, status: str) -> list[str]:
        if status == ClauseStatus.CREATE_FAILED.value:
            return ["重试创建", "跳过此条", "打开本地 docx"]
        if status == ClauseStatus.UPLOAD_FAILED.value:
            return ["重试上传", "跳过此条", "打开本地 docx", "打开后端 chapter 记录"]
        if status == ClauseStatus.SKIPPED.value:
            return ["恢复跳过", "打开本地 docx"]
        if status == ClauseStatus.PENDING_UPLOAD.value:
            return ["重试上传", "打开本地 docx", "打开后端 chapter 记录"]
        if status == ClauseStatus.PENDING_CREATE.value:
            return ["跳过此条", "打开本地 docx"]
        return ["打开本地 docx"]

    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0:
            return
        term_item = self.item(row, 0)
        status_item = self.item(row, 2)
        if term_item is None or status_item is None:
            return
        clause_id = term_item.data(Qt.ItemDataRole.UserRole)
        if clause_id is None:
            return
        menu = QMenu(self)
        for action_name in self.available_actions_for_status(status_item.text()):
            action = menu.addAction(action_name)
            action.triggered.connect(lambda _checked=False, name=action_name, cid=int(clause_id): self.action_requested.emit(name, cid))
        menu.exec(self.viewport().mapToGlobal(pos))
