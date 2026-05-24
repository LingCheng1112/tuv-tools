"""Chapter 批量导入工作台视图。"""

from __future__ import annotations

from pathlib import Path
import subprocess

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.api import get_chapters
from tuv_tools.core.chapter_batch.api import create_chapter_and_return_id, import_chapter_doc
from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor
from tuv_tools.core.chapter_batch.models import ClauseStatus, DocumentStatus, SplitMode, is_document_executable
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


class ChapterBatchView(QWidget):
    """条款批量导入工作台的最小页面骨架。"""

    COL_FILE_NAME = 1

    def __init__(self, repo: ChapterBatchRepository | None = None):
        super().__init__()
        self._repo = repo or ChapterBatchRepository(DatabaseManager())
        self._service = ChapterBatchService(self._repo)
        self._documents = []
        self._selected_document_ids: list[int] = []
        self._execution_worker: ChapterBatchExecutionWorker | None = None
        layout = QVBoxLayout(self)

        title = QLabel("条款批量导入")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        toolbar = QHBoxLayout()
        self._import_file_btn = QPushButton("导入文件")
        self._import_dir_btn = QPushButton("导入文件夹")
        self._bulk_confirm_btn = QPushButton("批量确认")
        self._start_btn = QPushButton("开始执行")
        self._delete_btn = QPushButton("删除记录")
        toolbar.addWidget(self._import_file_btn)
        toolbar.addWidget(self._import_dir_btn)
        toolbar.addWidget(self._bulk_confirm_btn)
        toolbar.addWidget(self._start_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        filters = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文档名 / 标准")
        self._status_filter = QComboBox()
        self._status_filter.addItems(["全部", "待确认", "待创建", "待上传", "部分完成", "失败", "已完成"])
        self._mode_filter = QComboBox()
        self._mode_filter.addItems(["全部", "章节", "条款"])
        self._display_filter = QComboBox()
        self._display_filter.addItems(["全部", "指定状态"])
        filters.addWidget(self._search_edit, stretch=1)
        filters.addWidget(self._status_filter)
        filters.addWidget(self._mode_filter)
        filters.addWidget(self._display_filter)
        layout.addLayout(filters)

        self._search_edit.textChanged.connect(self._load_documents)
        self._status_filter.currentIndexChanged.connect(self._load_documents)
        self._mode_filter.currentIndexChanged.connect(self._load_documents)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["选择", "文档名", "标准", "模式", "文档状态", "条款结果摘要", "更新时间"]
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self._table.customContextMenuRequested.connect(self._show_document_context_menu)
        layout.addWidget(self._table, stretch=1)

        self._import_file_btn.clicked.connect(self._import_files)
        self._import_dir_btn.clicked.connect(self._import_dir)
        self._bulk_confirm_btn.clicked.connect(self._open_bulk_confirm)
        self._start_btn.clicked.connect(self._start_selected_documents)
        self._delete_btn.clicked.connect(self._delete_selected_documents)

        self._drawer = ChapterBatchDrawer(self)
        self._drawer.document_selected.connect(self._load_drawer_clauses)
        self._drawer.save_confirm_requested.connect(self._on_save_confirm_requested)
        self._drawer.clause_action_requested.connect(self._on_clause_action_requested)
        self._drawer.hide()

        self._load_documents()

    def _load_documents(self) -> None:
        status = self._status_filter.currentText()
        mode = self._mode_filter.currentText()
        keyword = self._search_edit.text().strip()
        self._documents = self._repo.list_documents(status=status, split_mode=mode, keyword=keyword)
        self._table.setRowCount(len(self._documents))
        for row, document in enumerate(self._documents):
            checkbox = QCheckBox()
            checkbox.setStyleSheet(CHECKBOX_STYLE)
            checkbox.toggled.connect(
                lambda checked, doc_id=document.id: self._on_document_checked(doc_id, checked)
            )
            self._table.setCellWidget(row, 0, checkbox)
            self._table.setItem(row, 1, QTableWidgetItem(document.file_name))
            self._table.setItem(row, 2, QTableWidgetItem(document.standard))
            self._table.setItem(row, 3, QTableWidgetItem(document.split_mode))
            self._table.setItem(row, 4, QTableWidgetItem(document.document_status))
            summary = (
                f"成功 {document.success_clause_count} / "
                f"失败 {document.failed_clause_count} / "
                f"跳过 {document.skipped_clause_count}"
            )
            self._table.setItem(row, 5, QTableWidgetItem(summary))
            self._table.setItem(row, 6, QTableWidgetItem(""))

    def _import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 DOCX 文件",
            "",
            "Word Documents (*.docx)",
        )
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
        self._drawer.set_documents(list(documents))
        self._drawer.setGeometry(max(0, self.width() - 420), 0, 420, self.height())
        self._drawer.show()
        if documents and documents[0].id is not None:
            self._load_drawer_clauses(documents[0].id)

    def _set_selected_document_ids(self, document_ids: list[int]) -> None:
        self._selected_document_ids = document_ids
        selected = set(document_ids)
        for row, document in enumerate(self._documents):
            checkbox = self._table.cellWidget(row, 0)
            if isinstance(checkbox, QCheckBox):
                checkbox.blockSignals(True)
                checkbox.setChecked(document.id in selected)
                checkbox.blockSignals(False)

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
        self._open_drawer_for_documents(documents)

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
        resplit_action.setEnabled(document.document_status not in {DocumentStatus.CREATING.value, DocumentStatus.UPLOADING.value, DocumentStatus.SPLITTING.value})
        resplit_action.triggered.connect(lambda: self._resplit_document(document.id))
        cancel_action = menu.addAction("取消执行")
        cancel_action.setEnabled(self._execution_worker is not None and document.is_queued)
        cancel_action.triggered.connect(self._cancel_execution)
        delete_action = menu.addAction("删除记录")
        delete_action.setEnabled(not document.is_queued and document.document_status not in {DocumentStatus.CREATING.value, DocumentStatus.UPLOADING.value, DocumentStatus.SPLITTING.value})
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

    def _on_save_confirm_requested(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        self._save_clause_updates()
        document_updates = {}
        all_fields = self._drawer.all_document_fields()
        for document_id in document_ids:
            current = next((doc for doc in self._documents if doc.id == document_id), None)
            if current is None:
                continue
            document_updates[document_id] = all_fields.get(document_id, self._drawer.current_document_fields())
        missing = self._missing_required_document_fields(document_updates)
        if missing:
            QMessageBox.warning(self, "无法保存确认", "以下文档缺少必填字段：\n" + "\n".join(missing))
            return
        if not self._resolve_duplicate_candidates(document_ids):
            return
        ready_ids = self._service.save_confirmed_documents(document_updates)
        self._load_documents()
        action = self._ask_post_confirm_action()
        if action == "upload":
            for document_id in ready_ids:
                self._repo.update_document(document_id, is_queued=1)
            self._load_documents()
            self._start_documents(ready_ids)
            return
        for document_id in ready_ids:
            self._repo.update_document(document_id, is_queued=0)
        self._load_documents()

    def _ask_post_confirm_action(self) -> str:
        reply = QMessageBox.question(
            self,
            "确认完成",
            "请选择下一步操作：\n是：直接上传\n否：稍后处理\n取消：只保留本地已保存结果",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            return "upload"
        if reply == QMessageBox.StandardButton.No:
            return "later"
        return "cancel"

    def _save_clause_updates(self) -> None:
        for _document_id, clauses in self._drawer.all_clause_fields().items():
            for clause_id, fields in clauses.items():
                self._repo.update_clause(clause_id, **fields)

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
        if not document_ids or self._execution_worker is not None:
            return
        for order, document_id in enumerate(document_ids):
            self._repo.update_document(
                document_id,
                is_queued=1,
                queue_order=order,
            )
        self._load_documents()
        self._execution_worker = ChapterBatchExecutionWorker(self._repo, document_ids)
        self._execution_worker.finished_ok.connect(self._on_execution_finished)
        self._execution_worker.failed.connect(self._on_execution_failed)
        self._execution_worker.finished.connect(self._clear_execution_worker)
        self._execution_worker.start()

    def _cancel_execution(self) -> None:
        if self._execution_worker is None:
            return
        self._execution_worker.request_cancel()

    def _delete_selected_documents(self) -> None:
        deletable_ids = [
            document.id
            for document in self._selected_documents()
            if document.id is not None and document.document_status not in {
                DocumentStatus.CREATING.value,
                DocumentStatus.UPLOADING.value,
                DocumentStatus.SPLITTING.value,
            }
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
        self._repo.delete_documents(document_ids)
        self._selected_document_ids = []
        self._load_documents()

    def _resplit_document(self, document_id: int) -> None:
        split_mode = self._choose_import_mode()
        if split_mode is None:
            return
        self._service.reset_document_for_resplit(document_id, split_mode)
        try:
            self._service.split_document(document_id)
        except Exception as exc:
            self._repo.update_document(document_id, document_status=DocumentStatus.FAILED.value, last_error=str(exc))
            QMessageBox.warning(self, "重新拆分失败", str(exc))
        self._load_documents()

    def _on_execution_finished(self) -> None:
        self._load_documents()

    def _on_execution_failed(self, message: str) -> None:
        QMessageBox.warning(self, "执行失败", message)
        self._load_documents()

    def _clear_execution_worker(self) -> None:
        self._execution_worker = None

    def _load_drawer_clauses(self, document_id: int) -> None:
        clauses = self._repo.get_clauses(document_id)
        self._drawer.set_clauses(
            [
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
                }
                for clause in clauses
            ]
        )

    def _on_clause_action_requested(self, action_name: str, clause_id: int) -> None:
        if action_name == "重试创建":
            self._set_clause_status_for_retry(clause_id, ClauseStatus.CREATE_FAILED.value)
        elif action_name == "重试上传":
            self._set_clause_status_for_retry(clause_id, ClauseStatus.UPLOAD_FAILED.value)
        elif action_name == "跳过此条":
            self._skip_clause(clause_id)
        elif action_name == "恢复跳过":
            self._restore_clause(clause_id)
        elif action_name == "打开本地 docx":
            self._open_local_docx(clause_id)
        elif action_name == "打开后端 chapter 记录":
            self._open_backend_chapter_record(clause_id)
        current = self._drawer.current_document()
        if current and current.id is not None:
            self._repo.reaggregate_document(current.id)
            self._load_drawer_clauses(current.id)
        self._load_documents()

    def _set_clause_status_for_retry(self, clause_id: int, from_status: str) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.clause_status != from_status:
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value if clause.chapter_id else ClauseStatus.PENDING_CREATE.value,
            create_error="",
            upload_error="",
            last_action="retry",
        )

    def _skip_clause(self, clause_id: int) -> None:
        self._repo.update_clause(clause_id, clause_status=ClauseStatus.SKIPPED.value, user_decision="skip")

    def _restore_clause(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None:
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value if clause.chapter_id else ClauseStatus.PENDING_CREATE.value,
            user_decision="",
        )

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._drawer.isVisible():
            self._drawer.setGeometry(max(0, self.width() - 420), 0, 420, self.height())
