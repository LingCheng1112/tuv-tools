"""Chapter 批量导入工作台视图。"""

from __future__ import annotations

from pathlib import Path
import subprocess

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter.api import get_chapters
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter_batch.api import create_chapter_and_return_id, import_chapter_doc
from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor
from tuv_tools.core.chapter_batch.models import (
    ClauseStatus,
    DocumentStatus,
    SplitMode,
    get_clause_edit_state,
    is_document_executable,
    is_document_running,
)
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository
from tuv_tools.core.chapter_batch.service import ChapterBatchService
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer


class ChapterBatchExecutionWorker(QThread):
    """后台执行批量创建和上传。"""

    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, repo: ChapterBatchRepository, document_ids: list[int]):
        super().__init__()
        self._repo = repo
        self._document_ids = document_ids
        self._controller = ChapterBatchExecutionController()

    def request_cancel(self) -> None:
        self._controller.request_cancel()

    def run(self) -> None:
        try:
            settings = AppSettings()
            config = settings.load_api_config()
            if config is None:
                raise RuntimeError("请先在设置中配置后端接口账号。")
            client = TuvClient(config.base_url, config.request_timeout)
            if not auto_login(client, config):
                raise RuntimeError("后端登录失败。")
            executor = ChapterBatchExecutor(
                self._repo,
                create_chapter=lambda chapter: create_chapter_and_return_id(client, chapter),
                upload_chapter_doc=lambda chapter_id, path: import_chapter_doc(client, chapter_id, path),
                controller=self._controller,
            )
            executor.run_documents(self._document_ids)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterClauseExecutionWorker(QThread):
    """后台执行单文档内指定条款的创建和上传。"""

    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, repo: ChapterBatchRepository, document_id: int, clause_ids: list[int]):
        super().__init__()
        self._repo = repo
        self._document_id = document_id
        self._clause_ids = clause_ids
        self._controller = ChapterBatchExecutionController()

    def request_cancel(self) -> None:
        self._controller.request_cancel()

    def run(self) -> None:
        try:
            settings = AppSettings()
            config = settings.load_api_config()
            if config is None:
                raise RuntimeError("请先在设置中配置后端接口账号。")
            client = TuvClient(config.base_url, config.request_timeout)
            if not auto_login(client, config):
                raise RuntimeError("后端登录失败。")
            executor = ChapterBatchExecutor(
                self._repo,
                create_chapter=lambda chapter: create_chapter_and_return_id(client, chapter),
                upload_chapter_doc=lambda chapter_id, path: import_chapter_doc(client, chapter_id, path),
                controller=self._controller,
            )
            executor.run_clauses(self._document_id, self._clause_ids)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterBatchView(QWidget):
    """条款批量导入工作台的最小页面骨架。"""

    COL_CHECK = 0
    COL_FILE_NAME = 1
    COL_STANDARD = 2
    COL_MODE = 3
    COL_STATUS = 4
    COL_SUMMARY = 5
    COL_UPDATED_AT = 6
    VIEW_ONLY_CLAUSE_ACTIONS = {"打开本地 docx", "打开后端 chapter 记录"}

    def __init__(self, repo: ChapterBatchRepository | None = None):
        super().__init__()
        self._repo = repo or ChapterBatchRepository(DatabaseManager())
        self._service = ChapterBatchService(self._repo)
        self._documents = []
        self._selected_document_ids: list[int] = []
        self._execution_worker: ChapterBatchExecutionWorker | None = None
        self._clause_execution_worker: ChapterClauseExecutionWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("条款批量导入")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        toolbar = QHBoxLayout()
        self._import_file_btn = QPushButton("导入文件")
        self._import_dir_btn = QPushButton("导入文件夹")
        toolbar.addWidget(self._import_file_btn)
        toolbar.addWidget(self._import_dir_btn)
        toolbar.addSpacing(16)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文档名或标准号...")
        self._search_edit.setClearButtonEnabled(True)
        toolbar.addWidget(self._search_edit, stretch=1)
        layout.addLayout(toolbar)

        filters = QHBoxLayout()
        self._status_filter = QComboBox()
        self._status_filter.addItems(
            [
                "全部",
                DocumentStatus.PENDING_CONFIRM.value,
                DocumentStatus.PENDING_CREATE.value,
                DocumentStatus.PENDING_UPLOAD.value,
                DocumentStatus.PARTIAL.value,
                DocumentStatus.FAILED.value,
                DocumentStatus.COMPLETED.value,
            ]
        )
        self._mode_filter = QComboBox()
        self._mode_filter.addItems(["全部", "章节", "条款"])
        filters.addWidget(self._status_filter)
        filters.addWidget(self._mode_filter)
        filters.addStretch()
        layout.addLayout(filters)

        self._search_edit.textChanged.connect(self._load_documents)
        self._status_filter.currentIndexChanged.connect(self._load_documents)
        self._mode_filter.currentIndexChanged.connect(self._load_documents)

        self._table = QTableWidget()
        self._configure_table()
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self._table.customContextMenuRequested.connect(self._show_document_context_menu)
        layout.addWidget(self._table, stretch=1)

        bottom = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setStyleSheet(CHECKBOX_STYLE)
        self._select_all_cb.toggled.connect(self._on_select_all_toggled)
        bottom.addWidget(self._select_all_cb)

        self._selected_label = QLabel("已选 0/0 项")
        bottom.addWidget(self._selected_label)
        bottom.addStretch()

        self._bulk_confirm_btn = QPushButton("批量确认")
        self._bulk_confirm_btn.setStyleSheet(self._action_btn_style("#6a6d72"))
        self._bulk_confirm_btn.setEnabled(False)
        bottom.addWidget(self._bulk_confirm_btn)

        self._start_btn = QPushButton("开始执行")
        self._start_btn.setStyleSheet(self._action_btn_style("#4a9eff"))
        self._start_btn.setEnabled(False)
        bottom.addWidget(self._start_btn)

        self._delete_btn = QPushButton("删除记录")
        self._delete_btn.setStyleSheet(self._action_btn_style("#d9534f"))
        self._delete_btn.setEnabled(False)
        bottom.addWidget(self._delete_btn)
        layout.addLayout(bottom)

        self._import_file_btn.clicked.connect(self._import_files)
        self._import_dir_btn.clicked.connect(self._import_dir)
        self._bulk_confirm_btn.clicked.connect(self._open_bulk_confirm)
        self._start_btn.clicked.connect(self._start_selected_documents)
        self._delete_btn.clicked.connect(self._delete_selected_documents)

        self._drawer = ChapterBatchDrawer(self)
        self._drawer.document_selected.connect(self._load_drawer_clauses)
        self._drawer.save_requested.connect(self._on_save_requested)
        self._drawer.upload_requested.connect(self._on_upload_requested)
        self._drawer.clause_action_requested.connect(self._on_clause_action_requested)
        self._drawer.hide()

        self._load_documents()

    def _configure_table(self) -> None:
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["", "文档名", "标准", "拆分方式", "文档状态", "条款结果摘要", "更新时间"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self.COL_FILE_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(self.COL_CHECK, 36)
        self._table.setColumnWidth(self.COL_STANDARD, 120)
        self._table.setColumnWidth(self.COL_MODE, 90)
        self._table.setColumnWidth(self.COL_STATUS, 110)
        self._table.setColumnWidth(self.COL_SUMMARY, 220)
        self._table.setColumnWidth(self.COL_UPDATED_AT, 145)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.setStyleSheet(
            """
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
        )

    @staticmethod
    def _action_btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background-color: {color}; opacity: 0.9; }}
            QPushButton:disabled {{ background-color: #666666; }}
        """

    @staticmethod
    def _make_item(
        text: str,
        tooltip: str = "",
        *,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(alignment)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    @staticmethod
    def _build_summary_text(document) -> str:
        return (
            f"成功 {document.success_clause_count} / "
            f"失败 {document.failed_clause_count} / "
            f"跳过 {document.skipped_clause_count}"
        )

    @staticmethod
    def _build_status_tooltip(document) -> str:
        parts = [document.document_status]
        if document.is_queued:
            parts.append("已加入当前执行队列")
        if document.last_error:
            parts.append(f"错误：{document.last_error}")
        return "\n".join(parts)

    def _load_documents(self) -> None:
        selected = {document_id for document_id in self._selected_document_ids if document_id is not None}
        status = self._status_filter.currentText()
        mode = self._mode_filter.currentText()
        keyword = self._search_edit.text().strip()
        self._documents = self._repo.list_documents(status=status, split_mode=mode, keyword=keyword)
        self._selected_document_ids = [doc.id for doc in self._documents if doc.id in selected]
        selected = set(self._selected_document_ids)

        self._table.clearContents()
        self._table.setRowCount(len(self._documents))
        for row, document in enumerate(self._documents):
            checkbox = QCheckBox()
            checkbox.setStyleSheet(CHECKBOX_STYLE)
            checkbox.blockSignals(True)
            checkbox.setChecked(document.id in selected)
            checkbox.blockSignals(False)
            checkbox.toggled.connect(lambda checked, doc_id=document.id: self._on_document_checked(doc_id, checked))
            self._table.setCellWidget(row, self.COL_CHECK, checkbox)
            self._table.setItem(
                row,
                self.COL_FILE_NAME,
                self._make_item(
                    document.file_name or "-",
                    document.file_path or document.file_name,
                    alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                ),
            )
            standard = document.standard or "-"
            self._table.setItem(row, self.COL_STANDARD, self._make_item(standard, standard))
            self._table.setItem(row, self.COL_MODE, self._make_item(document.split_mode or "-"))
            self._table.setItem(
                row,
                self.COL_STATUS,
                self._make_item(document.document_status or "-", self._build_status_tooltip(document)),
            )
            summary = self._build_summary_text(document)
            self._table.setItem(
                row,
                self.COL_SUMMARY,
                self._make_item(
                    summary,
                    document.last_error or summary,
                    alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                ),
            )
            updated_at = document.updated_at or "-"
            display_time = updated_at[:16] if len(updated_at) > 16 else updated_at
            self._table.setItem(row, self.COL_UPDATED_AT, self._make_item(display_time, updated_at))
        self._update_selected_label()

    def _update_selected_label(self) -> None:
        checked = len(self._selected_document_ids)
        total = len(self._documents)
        self._selected_label.setText(f"已选 {checked}/{total} 项")
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(total > 0 and checked == total)
        self._select_all_cb.blockSignals(False)

        selected_documents = self._selected_documents()
        has_selection = checked > 0
        has_executable = any(
            document.id is not None and is_document_executable(document.document_status)
            for document in selected_documents
        )
        has_deletable = any(
            document.id is not None
            and not document.is_queued
            and not is_document_running(document.document_status)
            for document in selected_documents
        )
        self._bulk_confirm_btn.setEnabled(has_selection)
        self._start_btn.setEnabled(
            has_executable
            and self._execution_worker is None
            and self._clause_execution_worker is None
        )
        self._delete_btn.setEnabled(has_deletable)

    def _import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DOCX 文件", "", "Word Documents (*.docx)")
        if not paths:
            return
        self._import_selected_paths(paths)

    def _import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not path:
            return
        files = [str(item) for item in Path(path).rglob("*.docx") if not item.name.startswith("~$")]
        if not files:
            return
        self._import_selected_paths(files)

    def _choose_import_mode(self) -> str | None:
        mode, accepted = QInputDialog.getItem(
            self,
            "选择拆分类型",
            "拆分类型",
            [SplitMode.CLAUSE.value, SplitMode.SECTION.value],
            0,
            False,
        )
        if not accepted:
            return None
        return mode

    def _import_selected_paths(self, paths: list[str]) -> None:
        split_mode = self._choose_import_mode()
        if split_mode is None:
            return
        self._service.import_and_split_documents(paths, split_mode=split_mode)
        self._load_documents()

    def _on_table_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._documents):
            return
        self._open_drawer_for_documents([self._documents[row]])

    def _open_drawer_for_documents(self, documents) -> None:
        self._drawer.set_documents(list(documents[:1]))
        self._layout_drawer()
        self._drawer.show()
        current = documents[0] if documents else None
        self._drawer.set_edit_locked(bool(current and is_document_running(current.document_status)))
        if documents and documents[0].id is not None:
            self._load_drawer_clauses(documents[0].id)

    def _layout_drawer(self) -> None:
        self._drawer.apply_layout(self.width(), self.height())

    def _set_selected_document_ids(self, document_ids: list[int]) -> None:
        selected = {document_id for document_id in document_ids if document_id is not None}
        self._selected_document_ids = [doc.id for doc in self._documents if doc.id in selected]
        selected = set(self._selected_document_ids)
        for row, document in enumerate(self._documents):
            checkbox = self._table.cellWidget(row, self.COL_CHECK)
            if isinstance(checkbox, QCheckBox):
                checkbox.blockSignals(True)
                checkbox.setChecked(document.id in selected)
                checkbox.blockSignals(False)
        self._update_selected_label()

    def _on_select_all_toggled(self, checked: bool) -> None:
        if checked:
            self._set_selected_document_ids([doc.id for doc in self._documents if doc.id is not None])
            return
        self._set_selected_document_ids([])

    def _selected_documents(self):
        selected = []
        wanted = set(self._selected_document_ids)
        for document in self._documents:
            if document.id in wanted:
                selected.append(document)
        return selected

    def _open_bulk_confirm(self) -> None:
        documents = self._selected_documents()
        if not documents:
            return
        self._open_drawer_for_documents([documents[0]])

    def _show_document_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._documents):
            return
        document = self._documents[row]
        if document.id is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("打开详情")
        open_action.triggered.connect(lambda: self._open_drawer_for_documents([document]))
        resplit_action = menu.addAction("重新拆分")
        resplit_action.setEnabled(
            document.document_status
            not in {DocumentStatus.CREATING.value, DocumentStatus.UPLOADING.value, DocumentStatus.SPLITTING.value}
        )
        resplit_action.triggered.connect(lambda: self._resplit_document(document.id))
        cancel_action = menu.addAction("取消执行")
        cancel_action.setEnabled(self._execution_worker is not None and document.is_queued)
        cancel_action.triggered.connect(self._cancel_execution)
        delete_action = menu.addAction("删除记录")
        delete_action.setEnabled(
            not document.is_queued
            and document.document_status
            not in {DocumentStatus.CREATING.value, DocumentStatus.UPLOADING.value, DocumentStatus.SPLITTING.value}
        )
        delete_action.triggered.connect(lambda: self._delete_documents([document.id]))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_document_checked(self, document_id: int | None, checked: bool) -> None:
        if document_id is None:
            return
        current = set(self._selected_document_ids)
        if checked:
            current.add(document_id)
        else:
            current.discard(document_id)
        self._selected_document_ids = [doc.id for doc in self._documents if doc.id in current]
        self._update_selected_label()

    def _on_save_requested(self, document_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "保存",
            "是否保存当前文档？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._save_documents([document_id]):
            QMessageBox.information(self, "保存", "已保存当前文档。")

    def _on_upload_requested(self, document_id: int, clause_ids: list[int]) -> None:
        ready_ids = self._save_documents([document_id])
        if not ready_ids:
            return
        if not clause_ids:
            QMessageBox.information(self, "上传", "请先勾选要上传的条款。")
            return
        self._start_clause_upload(document_id, clause_ids)

    def _save_documents(self, document_ids: list[int]) -> list[int]:
        if not document_ids:
            return []
        self._save_clause_updates()
        document_updates = {}
        all_fields = self._drawer.all_document_fields()
        for document_id in document_ids:
            current = self._repo.get_document(document_id)
            if current is None or is_document_running(current.document_status):
                continue
            document_updates[document_id] = all_fields.get(document_id, self._drawer.current_document_fields())
        if not document_updates:
            return []
        missing = self._missing_required_document_fields(document_updates)
        if missing:
            QMessageBox.warning(self, "无法保存", "以下文档缺少必填字段：\n" + "\n".join(missing))
            return []
        filtered_document_ids = list(document_updates)
        if not self._resolve_duplicate_candidates(filtered_document_ids):
            return []
        ready_ids = self._service.save_confirmed_documents(document_updates)
        self._load_documents()
        return ready_ids

    def _save_clause_updates(self) -> None:
        for document_id, clauses in self._drawer.all_clause_fields().items():
            document = self._repo.get_document(document_id)
            if document is None or is_document_running(document.document_status):
                self._drawer.clear_clause_cache(document_id)
                continue
            retained_clause_ids: set[int] = set()
            for clause_id, fields in clauses.items():
                clause = self._repo.get_clause(clause_id)
                if clause is None:
                    continue
                editable, _reason = get_clause_edit_state(
                    clause_status=clause.clause_status,
                    chapter_id=clause.chapter_id,
                    backend_chapter_status=clause.backend_chapter_status,
                )
                if not editable:
                    continue
                self._repo.update_clause(clause_id, **fields)
                retained_clause_ids.add(clause_id)
            self._drawer.retain_clause_cache(document_id, retained_clause_ids)

    def _missing_required_document_fields(self, document_updates: dict[int, dict]) -> list[str]:
        missing = []
        for document_id, fields in document_updates.items():
            document = self._repo.get_document(document_id)
            name = document.file_name if document else str(document_id)
            if not fields.get("standard"):
                missing.append(f"{name}: 标准")
            if not fields.get("folder_id"):
                missing.append(f"{name}: 归属文件夹")
            if not fields.get("product_type"):
                missing.append(f"{name}: 产品类别")
            if not fields.get("plan_sr"):
                missing.append(f"{name}: PlanSR")
            if not fields.get("chapter_version"):
                missing.append(f"{name}: 条款版本")
        return missing

    def _resolve_duplicate_candidates(self, document_ids: list[int]) -> bool:
        for document_id in document_ids:
            duplicate_ids = self._service.mark_duplicate_candidates(
                document_id,
                self._existing_rows_for_duplicate_check(document_id),
            )
            for clause_id in duplicate_ids:
                clause = self._repo.get_clause(clause_id)
                if clause is None:
                    continue
                decision = self._ask_duplicate_decision(clause)
                if decision == "skip":
                    self._repo.update_clause(
                        clause_id,
                        clause_status=ClauseStatus.SKIPPED.value,
                        user_decision="skip_duplicate",
                    )
                elif decision == "create":
                    self._repo.update_clause(clause_id, user_decision="create_duplicate")
                else:
                    return False
        return True

    def _existing_rows_for_duplicate_check(self, document_id: int) -> list[dict]:
        document = self._repo.get_document(document_id)
        if document is None or document.folder_id is None:
            return []
        try:
            config = AppSettings().load_api_config()
            if config is None:
                return []
            client = TuvClient(config.base_url, config.request_timeout)
            if not auto_login(client, config):
                return []
            page = get_chapters(client, page=0, size=500, folder_id=document.folder_id)
        except Exception:
            return []
        return [
            {
                "folder_id": chapter.folder_id,
                "term": chapter.term,
                "test_content": chapter.test_content,
            }
            for chapter in page.content
        ]

    def _ask_duplicate_decision(self, clause) -> str | None:
        reply = QMessageBox.question(
            self,
            "疑似重复条款",
            f"条款 {clause.term} 在同一归属文件夹下可能已存在。\n"
            "选择“是”仍然创建，选择“否”跳过此条，选择“取消”停止保存。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            return "create"
        if reply == QMessageBox.StandardButton.No:
            return "skip"
        return None

    def _start_selected_documents(self) -> None:
        document_ids = [
            document.id
            for document in self._selected_documents()
            if document.id is not None and is_document_executable(document.document_status)
        ]
        self._start_documents(document_ids)

    def _start_documents(self, document_ids: list[int]) -> None:
        if (
            not document_ids
            or self._execution_worker is not None
            or self._clause_execution_worker is not None
        ):
            return
        for order, document_id in enumerate(document_ids):
            self._repo.update_document(document_id, is_queued=1, queue_order=order)
        self._load_documents()
        self._execution_worker = ChapterBatchExecutionWorker(self._repo, document_ids)
        self._execution_worker.finished_ok.connect(self._on_execution_finished)
        self._execution_worker.failed.connect(self._on_execution_failed)
        self._execution_worker.finished.connect(self._clear_execution_worker)
        self._execution_worker.start()
        self._update_selected_label()

    def _start_clause_upload(self, document_id: int, clause_ids: list[int]) -> None:
        if self._execution_worker is not None or self._clause_execution_worker is not None:
            return
        document = self._repo.get_document(document_id)
        if document is None or is_document_running(document.document_status):
            return
        ordered_clause_ids = [
            clause.id
            for clause in self._repo.get_clauses(document_id)
            if clause.id in set(clause_ids)
        ]
        if not ordered_clause_ids:
            return
        self._repo.update_document(document_id, is_queued=1, queue_order=0)
        self._load_documents()
        self._clause_execution_worker = ChapterClauseExecutionWorker(self._repo, document_id, ordered_clause_ids)
        self._clause_execution_worker.finished_ok.connect(self._on_execution_finished)
        self._clause_execution_worker.failed.connect(self._on_execution_failed)
        self._clause_execution_worker.finished.connect(self._clear_clause_execution_worker)
        self._clause_execution_worker.start()
        self._update_selected_label()

    def _cancel_execution(self) -> None:
        if self._execution_worker is not None:
            self._execution_worker.request_cancel()
        if self._clause_execution_worker is not None:
            self._clause_execution_worker.request_cancel()

    def _delete_selected_documents(self) -> None:
        deletable_ids = [
            document.id
            for document in self._selected_documents()
            if document.id is not None
            and document.document_status
            not in {DocumentStatus.CREATING.value, DocumentStatus.UPLOADING.value, DocumentStatus.SPLITTING.value}
        ]
        if not deletable_ids:
            return
        reply = QMessageBox.question(
            self,
            "删除记录",
            "仅删除本地工作台记录，不删除后端条款或文档文件。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._delete_documents(deletable_ids)

    def _delete_documents(self, document_ids: list[int]) -> None:
        deletable_ids = []
        for document_id in document_ids:
            document = self._repo.get_document(document_id)
            if document is None:
                continue
            if document.is_queued or is_document_running(document.document_status):
                continue
            deletable_ids.append(document_id)
        if not deletable_ids:
            return
        self._repo.delete_documents(deletable_ids)
        self._selected_document_ids = []
        self._load_documents()

    def _resplit_document(self, document_id: int) -> None:
        current = self._repo.get_document(document_id)
        if current is None or is_document_running(current.document_status):
            return
        split_mode = self._choose_import_mode()
        if split_mode is None:
            return
        self._service.reset_document_for_resplit(document_id, split_mode)
        try:
            self._service.split_document(document_id)
        except Exception as exc:
            self._repo.update_document(
                document_id,
                document_status=DocumentStatus.FAILED.value,
                last_error=str(exc),
            )
            QMessageBox.warning(self, "重新拆分失败", str(exc))
        self._load_documents()

    def _on_execution_finished(self) -> None:
        self._load_documents()

    def _on_execution_failed(self, message: str) -> None:
        QMessageBox.warning(self, "执行失败", message)
        self._load_documents()

    def _clear_execution_worker(self) -> None:
        self._execution_worker = None
        self._update_selected_label()

    def _clear_clause_execution_worker(self) -> None:
        self._clause_execution_worker = None
        self._update_selected_label()

    def _load_drawer_clauses(self, document_id: int) -> None:
        document = self._repo.get_document(document_id)
        locked = bool(document and is_document_running(document.document_status))
        self._drawer.set_edit_locked(locked)
        if locked:
            self._drawer.clear_clause_cache(document_id)
        clauses = self._repo.get_clauses(document_id)
        clause_rows = []
        for clause in clauses:
            editable, readonly_reason = get_clause_edit_state(
                clause_status=clause.clause_status,
                chapter_id=clause.chapter_id,
                backend_chapter_status=clause.backend_chapter_status,
            )
            clause_rows.append(
                {
                    "term": clause.term,
                    "test_content": clause.test_content,
                    "clause_status": clause.clause_status,
                    "chapter_id": clause.chapter_id,
                    "id": clause.id,
                    "duplicate_flag": clause.duplicate_flag,
                    "duplicate_reason": clause.duplicate_reason,
                    "create_error": clause.create_error,
                    "upload_error": clause.upload_error,
                    "editable": editable and not locked,
                    "readonly_reason": "文档执行中，禁止编辑" if locked else readonly_reason,
                }
            )
        self._drawer.set_clauses(clause_rows)

    def _on_clause_action_requested(self, action_name: str, clause_id: int) -> None:
        if not self._can_apply_clause_action(action_name, clause_id):
            return
        if action_name == "重试创建":
            self._set_clause_status_for_retry(clause_id, ClauseStatus.CREATE_FAILED.value)
        elif action_name == "重试上传":
            self._set_clause_status_for_retry(clause_id, ClauseStatus.UPLOAD_FAILED.value)
        elif action_name == "上传":
            self._upload_single_clause(clause_id)
        elif action_name == "恢复跳过":
            self._restore_clause(clause_id)
        elif action_name == "查看错误信息":
            self._show_clause_issue_detail(clause_id)
        elif action_name == "打开本地 docx":
            self._open_local_docx(clause_id)
        elif action_name == "打开后端 chapter 记录":
            self._open_backend_chapter_record(clause_id)
        current = self._drawer.current_document()
        if current and current.id is not None:
            self._repo.reaggregate_document(current.id)
            self._load_drawer_clauses(current.id)
        self._load_documents()

    def _can_apply_clause_action(self, action_name: str, clause_id: int) -> bool:
        if action_name in self.VIEW_ONLY_CLAUSE_ACTIONS:
            return True
        clause = self._repo.get_clause(clause_id)
        if clause is None:
            return False
        document = self._repo.get_document(clause.document_id) if clause.document_id is not None else None
        if document is not None and is_document_running(document.document_status):
            return False
        editable, _reason = get_clause_edit_state(
            clause_status=clause.clause_status,
            chapter_id=clause.chapter_id,
            backend_chapter_status=clause.backend_chapter_status,
        )
        return editable

    def _upload_single_clause(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.document_id is None:
            return
        ready_ids = self._save_documents([clause.document_id])
        if clause.document_id not in ready_ids:
            return
        self._start_clause_upload(clause.document_id, [clause_id])

    def _set_clause_status_for_retry(self, clause_id: int, from_status: str) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.clause_status != from_status:
            return
        if not self._can_mutate_clause(clause):
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value if clause.chapter_id else ClauseStatus.PENDING_CREATE.value,
            create_error="",
            upload_error="",
            last_action="retry",
        )

    def _skip_clause(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or not self._can_mutate_clause(clause):
            return
        self._repo.update_clause(clause_id, clause_status=ClauseStatus.SKIPPED.value, user_decision="skip")

    def _restore_clause(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or not self._can_mutate_clause(clause):
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value if clause.chapter_id else ClauseStatus.PENDING_CREATE.value,
            user_decision="",
        )

    def _can_mutate_clause(self, clause) -> bool:
        document = self._repo.get_document(clause.document_id) if clause.document_id is not None else None
        if document is not None and is_document_running(document.document_status):
            return False
        editable, _reason = get_clause_edit_state(
            clause_status=clause.clause_status,
            chapter_id=clause.chapter_id,
            backend_chapter_status=clause.backend_chapter_status,
        )
        return editable

    def _open_local_docx(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or not clause.source_docx_path:
            return
        subprocess.Popen(["cmd", "/c", "start", "", clause.source_docx_path], shell=False)

    def _open_backend_chapter_record(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.chapter_id is None:
            QMessageBox.information(self, "后端条款记录", "当前条款还没有 chapter ID。")
            return
        QMessageBox.information(self, "后端条款记录", f"chapter ID: {clause.chapter_id}")

    def _show_clause_issue_detail(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None:
            return
        lines = []
        if clause.duplicate_flag:
            lines.append("疑似重复")
            if clause.duplicate_reason:
                lines.append(clause.duplicate_reason)
        if clause.create_error:
            lines.append("创建错误")
            lines.append(clause.create_error)
        if clause.upload_error:
            lines.append("上传错误")
            lines.append(clause.upload_error)
        if not lines:
            lines.append("当前条款没有可查看的错误或重复信息。")
        QMessageBox.information(self, "条款详情", "\n".join(lines))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._drawer.isVisible():
            self._layout_drawer()
