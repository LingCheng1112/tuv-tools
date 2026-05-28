"""Chapter 批量上传工作台视图。"""

from __future__ import annotations

from pathlib import Path
import subprocess

from PySide6.QtCore import QThread, Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
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
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.session import ChapterSessionManager
from tuv_tools.core.chapter_batch.api import create_chapter_and_return_id, import_chapter_doc
from tuv_tools.core.chapter_batch.executor import ChapterBatchExecutionController, ChapterBatchExecutor
from tuv_tools.core.chapter_batch.models import (
    BatchImportClause,
    ChapterBatchProgressEvent,
    ClauseStatus,
    DocumentStatus,
    SplitMode,
    display_document_status,
    get_clause_edit_state,
    is_document_executable,
    is_document_running,
)
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository
from tuv_tools.core.chapter_batch.service import (
    ChapterBatchService,
    check_duplicate_candidates,
    find_duplicate_candidate_row,
)
from tuv_tools.core.preparing import _win32com_client, prepare_single_doc
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer


class ChapterBatchExecutionWorker(QThread):
    """后台执行文档级批量上传。"""

    finished_ok = Signal()
    failed = Signal(str)
    progress_changed = Signal(object)

    def __init__(self, repo: ChapterBatchRepository, client: TuvClient, document_ids: list[int]):
        super().__init__()
        self._repo = repo
        self._client = client
        self._document_ids = document_ids
        self._controller = ChapterBatchExecutionController()

    def request_cancel(self) -> None:
        self._controller.request_cancel()

    def run(self) -> None:
        try:
            executor = ChapterBatchExecutor(
                self._repo,
                create_chapter=lambda chapter: create_chapter_and_return_id(self._client, chapter),
                upload_chapter_doc=lambda chapter_id, path: import_chapter_doc(self._client, chapter_id, path),
                controller=self._controller,
                progress=self.progress_changed.emit,
            )
            executor.run_documents(self._document_ids)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterClauseExecutionWorker(QThread):
    """后台执行单文档条款上传。"""

    finished_ok = Signal()
    failed = Signal(str)
    progress_changed = Signal(object)

    def __init__(self, repo: ChapterBatchRepository, client: TuvClient, document_id: int, clause_ids: list[int]):
        super().__init__()
        self._repo = repo
        self._client = client
        self._document_id = document_id
        self._clause_ids = clause_ids
        self._controller = ChapterBatchExecutionController()

    def request_cancel(self) -> None:
        self._controller.request_cancel()

    def run(self) -> None:
        try:
            executor = ChapterBatchExecutor(
                self._repo,
                create_chapter=lambda chapter: create_chapter_and_return_id(self._client, chapter),
                upload_chapter_doc=lambda chapter_id, path: import_chapter_doc(self._client, chapter_id, path),
                controller=self._controller,
                progress=self.progress_changed.emit,
            )
            executor.run_clauses(self._document_id, self._clause_ids)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterBatchProcessingWorker(QThread):
    """后台执行预处理与拆分。"""

    finished_ok = Signal()
    failed = Signal(int, str)
    progress_changed = Signal(object)

    def __init__(
        self,
        repo: ChapterBatchRepository,
        document_ids: list[int],
        output_root: Path | None = None,
        backend_client: TuvClient | None = None,
    ):
        super().__init__()
        self._repo = repo
        self._document_ids = list(document_ids)
        self._output_root = output_root
        self._backend_client = backend_client

    def run(self) -> None:
        import pythoncom  # type: ignore[import-untyped]

        pythoncom.CoInitialize()
        app = None
        try:
            client = _win32com_client()
            app = client.Dispatch("Word.Application")
            app.Visible = False
            app.ScreenUpdating = False
            service = ChapterBatchService(self._repo, output_root=self._output_root)
            total_docs = max(len(self._document_ids), 1)
            for doc_index, document_id in enumerate(self._document_ids, start=1):
                document = self._repo.get_document(document_id)
                if document is None:
                    continue
                try:
                    self._emit_processing_progress(
                        document_id=document_id,
                        total_docs=total_docs,
                        doc_index=doc_index,
                        phase="processing",
                        percent=0,
                        message="补全目录参数",
                    )
                    service.complete_folder_context(document_id, client=self._backend_client)
                    self._emit_processing_progress(
                        document_id=document_id,
                        total_docs=total_docs,
                        doc_index=doc_index,
                        phase="processing",
                        percent=15,
                        message="开始预处理",
                    )
                    doc = None
                    try:
                        normalized_path = str(Path(document.file_path).resolve())
                        doc = app.Documents.Open(normalized_path)
                        prepare_single_doc(doc, app)
                    finally:
                        if doc is not None:
                            try:
                                doc.Close()
                            except Exception:
                                pass
                    self._emit_processing_progress(
                        document_id=document_id,
                        total_docs=total_docs,
                        doc_index=doc_index,
                        phase="processing",
                        percent=55,
                        message="预处理完成，开始拆分",
                    )
                    service.split_document(document_id)
                    self._emit_processing_progress(
                        document_id=document_id,
                        total_docs=total_docs,
                        doc_index=doc_index,
                        phase="processing",
                        percent=100,
                        message="拆分完成",
                    )
                except Exception as exc:
                    self._repo.update_document(
                        document_id,
                        document_status=DocumentStatus.FAILED.value,
                        last_error=str(exc),
                    )
                    self.failed.emit(document_id, str(exc))
            self.finished_ok.emit()
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def _emit_processing_progress(
        self,
        *,
        document_id: int,
        total_docs: int,
        doc_index: int,
        phase: str,
        percent: int,
        message: str,
    ) -> None:
        if total_docs <= 0:
            total_docs = 1
        completed_fraction = max(doc_index - 1, 0) / total_docs
        current_fraction = (max(min(percent, 100), 0) / 100) / total_docs
        overall_percent = int(round((completed_fraction + current_fraction) * 100))
        self.progress_changed.emit(
            ChapterBatchProgressEvent(
                document_id=document_id,
                phase=phase,
                percent=overall_percent,
                message=message,
                current_index=doc_index,
                total_count=total_docs,
                action=phase,
            )
        )


class _StatusProgressRing(QWidget):
    """状态列使用的轻量环形进度。"""

    def __init__(self, percent: int, parent=None):
        super().__init__(parent)
        self._percent = max(0, min(percent, 100))
        self.setFixedSize(18, 18)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(2, 2, 14, 14)

        track_pen = QPen(QColor("#4a4d50"), 2)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        progress_pen = QPen(QColor("#4a9eff"), 2)
        painter.setPen(progress_pen)
        span = int(-360 * 16 * (self._percent / 100))
        painter.drawArc(rect, 90 * 16, span)


class _RunningStatusWidget(QWidget):
    """单元格内状态视图：左侧环形进度，文字保持居中显示。"""

    def __init__(self, status_text: str, percent: int, parent=None):
        super().__init__(parent)
        self._percent = max(0, min(percent, 100))
        self._label = QLabel(status_text, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #dcdcdc; font-size: 13px;")
        self.setMinimumHeight(26)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        ring_rect = QRectF(8, max((self.height() - 18) / 2, 0), 18, 18)
        track_pen = QPen(QColor("#4a4d50"), 2)
        painter.setPen(track_pen)
        painter.drawArc(ring_rect.adjusted(2, 2, -2, -2), 0, 360 * 16)

        progress_pen = QPen(QColor("#4a9eff"), 2)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        span = int(-360 * 16 * (self._percent / 100))
        painter.drawArc(ring_rect.adjusted(2, 2, -2, -2), 90 * 16, span)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._label.setGeometry(0, 0, self.width(), self.height())


class _SummaryTextWidget(QWidget):
    """单元格内摘要视图，保持文本垂直居中。"""

    def __init__(self, text: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        label = QLabel(text, self)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        label.setStyleSheet("color: #dcdcdc; font-size: 13px; padding: 0 10px;")
        layout.addWidget(label)
        if tooltip:
            self.setToolTip(tooltip)
            label.setToolTip(tooltip)


class ChapterBatchView(QWidget):
    """批量上传工作台。"""

    COL_CHECK = 0
    COL_FILE_NAME = 1
    COL_STANDARD = 2
    COL_MODE = 3
    COL_STATUS = 4
    COL_SUMMARY = 5
    COL_UPDATED_AT = 6

    VIEW_ONLY_CLAUSE_ACTIONS = {"打开本地 docx", "打开后端 chapter 记录", "查看错误信息"}

    def __init__(self, repo: ChapterBatchRepository | None = None, session_manager: ChapterSessionManager | None = None):
        super().__init__()
        self._session_manager = session_manager
        self._repo = repo or ChapterBatchRepository(DatabaseManager())
        self._service = ChapterBatchService(self._repo)
        self._documents = []
        self._selected_document_ids: list[int] = []
        self._progress_by_document_id: dict[int, ChapterBatchProgressEvent] = {}
        self._processing_worker: ChapterBatchProcessingWorker | None = None
        self._execution_worker: ChapterBatchExecutionWorker | None = None
        self._clause_execution_worker: ChapterClauseExecutionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        self._title_label = QLabel("批量上传")
        self._title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        self._backend_hint = QLabel("当前未连接后端。文档导入与本地核对仍可使用，上传与目录相关操作请先到设置中登录。")
        self._backend_hint.setWordWrap(True)
        self._backend_hint.setStyleSheet("color: #d9534f; font-size: 13px;")
        layout.addWidget(self._backend_hint)

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
        filters.addWidget(QLabel("状态"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(
            [
                "全部",
                DocumentStatus.PENDING_UPLOAD.value,
                DocumentStatus.PARTIAL.value,
                DocumentStatus.FAILED.value,
                DocumentStatus.COMPLETED.value,
            ]
        )
        filters.addWidget(self._status_filter)
        filters.addWidget(QLabel("拆分方式"))
        self._mode_filter = QComboBox()
        self._mode_filter.addItems(["全部", SplitMode.SECTION.value, SplitMode.CLAUSE.value])
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

        self._upload_btn = QPushButton("批量上传")
        self._upload_btn.setStyleSheet(self._action_btn_style("#4a9eff"))
        self._upload_btn.setEnabled(False)
        bottom.addWidget(self._upload_btn)

        self._delete_btn = QPushButton("删除记录")
        self._delete_btn.setStyleSheet(self._action_btn_style("#d9534f"))
        self._delete_btn.setEnabled(False)
        bottom.addWidget(self._delete_btn)
        layout.addLayout(bottom)

        self._import_file_btn.clicked.connect(self._import_files)
        self._import_dir_btn.clicked.connect(self._import_dir)
        self._upload_btn.clicked.connect(self._upload_selected_documents)
        self._delete_btn.clicked.connect(self._delete_selected_documents)

        self._drawer = ChapterBatchDrawer(self, session_manager=session_manager)
        self._drawer.document_selected.connect(self._load_drawer_clauses)
        self._drawer.save_requested.connect(self._on_save_requested)
        self._drawer.upload_requested.connect(self._on_upload_requested)
        self._drawer.clause_action_requested.connect(self._on_clause_action_requested)
        self._drawer.hide()

        if self._session_manager is not None:
            self._session_manager.status_changed.connect(self._on_session_status_changed)

        self._load_documents()
        self._apply_backend_connection_state()

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
        self._table.setColumnWidth(self.COL_STATUS, 182)
        self._table.setColumnWidth(self.COL_SUMMARY, 220)
        self._table.setColumnWidth(self.COL_UPDATED_AT, 145)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(42)
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
    def _build_status_tooltip(document) -> str:
        parts = [display_document_status(document.document_status)]
        if document.is_queued:
            parts.append("已加入当前执行队列")
        if document.last_error:
            parts.append(f"错误：{document.last_error}")
        return "\n".join(parts)

    @staticmethod
    def _display_status_text(status: str) -> str:
        return display_document_status(status)

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
            if is_document_running(document.document_status):
                self._table.setCellWidget(row, self.COL_STATUS, self._build_running_status_widget(document))
            else:
                self._table.setItem(
                    row,
                    self.COL_STATUS,
                    self._make_item(
                        self._display_status_text(document.document_status),
                        self._build_status_tooltip(document),
                    ),
                )
            summary = self._build_summary_text(document)
            self._table.setCellWidget(
                row,
                self.COL_SUMMARY,
                _SummaryTextWidget(
                    summary,
                    document.last_error or summary,
                    self._table,
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
        self._upload_btn.setEnabled(
            self._is_backend_connected()
            and has_executable
            and self._execution_worker is None
            and self._clause_execution_worker is None
        )
        self._delete_btn.setEnabled(has_deletable)

    def _is_backend_connected(self) -> bool:
        return self._session_manager is None or self._session_manager.is_connected()

    def _current_backend_client(self) -> TuvClient | None:
        if self._session_manager is None:
            return None
        return self._session_manager.get_connected_client()

    def _apply_backend_connection_state(self) -> None:
        connected = self._is_backend_connected() and (
            self._session_manager is None or self._current_backend_client() is not None
        )
        self._backend_hint.setVisible(not connected)
        self._drawer._document_form._folder_selector.set_connection_enabled(connected)
        self._update_selected_label()

    def _on_session_status_changed(self, _status: str) -> None:
        self._apply_backend_connection_state()

    def _ensure_backend_available(self) -> bool:
        if self._is_backend_connected() and (self._session_manager is None or self._current_backend_client() is not None):
            return True
        QMessageBox.warning(self, "未连接", "当前未连接后端，相关上传与目录功能不可用。")
        return False

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
        documents = self._service.import_documents(paths, split_mode=split_mode)
        self._load_documents()
        document_ids = [document.id for document in documents if document is not None and document.id is not None]
        self._start_processing_documents(document_ids)

    def _start_processing_documents(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        if self._processing_worker is not None:
            return
        self._processing_worker = ChapterBatchProcessingWorker(
            self._repo,
            document_ids,
            backend_client=self._current_backend_client(),
        )
        self._processing_worker.progress_changed.connect(self._on_progress_changed)
        self._processing_worker.failed.connect(self._on_processing_failed)
        self._processing_worker.finished_ok.connect(self._on_processing_finished)
        self._processing_worker.finished.connect(self._clear_processing_worker)
        self._processing_worker.start()

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
        resplit_action.setEnabled(not is_document_running(document.document_status))
        resplit_action.triggered.connect(lambda: self._resplit_document(document.id))
        cancel_action = menu.addAction("取消上传")
        cancel_action.setEnabled(self._execution_worker is not None and document.is_queued)
        cancel_action.triggered.connect(self._cancel_execution)
        delete_action = menu.addAction("删除记录")
        delete_action.setEnabled(not document.is_queued and not is_document_running(document.document_status))
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
            self._drawer.mark_saved(document_id)
            QMessageBox.information(self, "保存", "已保存当前文档。")

    def _on_upload_requested(self, document_id: int, clause_ids: list[int]) -> None:
        if not self._ensure_backend_available():
            return
        if self._drawer.is_dirty(document_id):
            QMessageBox.warning(self, "提示", "请先保存修改后再上传")
            return
        if not clause_ids:
            QMessageBox.information(self, "上传", "请先勾选要上传的条款。")
            return
        if not self._resolve_upload_duplicates(document_id, clause_ids):
            return
        uploadable_clause_ids = self._collect_uploadable_clause_ids(
            document_id,
            clause_ids,
            allow_reupload=False,
        )
        if not uploadable_clause_ids:
            self._repo.reaggregate_document(document_id)
            self._load_documents()
            self._load_drawer_clauses(document_id)
            return
        self._start_clause_upload(document_id, uploadable_clause_ids)

    def _collect_uploadable_clause_ids(
        self,
        document_id: int,
        clause_ids: list[int],
        *,
        allow_reupload: bool,
    ) -> list[int]:
        wanted = {int(clause_id) for clause_id in clause_ids}
        uploadable_clause_ids: list[int] = []
        for clause in self._repo.get_clauses(document_id):
            if clause.id not in wanted:
                continue
            if clause.id is None:
                continue
            if clause.clause_status == ClauseStatus.PENDING_UPLOAD.value:
                uploadable_clause_ids.append(clause.id)
                continue
            if clause.clause_status == ClauseStatus.UPLOAD_FAILED.value:
                uploadable_clause_ids.append(clause.id)
                continue
            if (
                allow_reupload
                and clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
                and clause.chapter_id is not None
            ):
                uploadable_clause_ids.append(clause.id)
        return uploadable_clause_ids

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
        ready_ids = self._service.save_confirmed_documents(document_updates)
        for document_id in ready_ids:
            self._drawer.mark_saved(document_id)
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

    def _resolve_upload_duplicates(self, document_id: int, clause_ids: list[int] | None = None) -> bool:
        document = self._repo.get_document(document_id)
        if document is None:
            return False
        wanted = None if clause_ids is None else {int(clause_id) for clause_id in clause_ids}
        duplicate_rows_cache: dict[tuple[str, str], list[dict]] = {}
        skip_remaining_duplicates = False
        for clause in self._repo.get_clauses(document_id):
            if wanted is not None and clause.id not in wanted:
                continue
            if clause.id is None:
                continue
            original_status = clause.clause_status
            original_chapter_id = clause.chapter_id
            original_user_decision = clause.user_decision
            if clause.chapter_id is not None:
                self._repo.update_clause(
                    clause.id,
                    duplicate_flag=False,
                    duplicate_reason="",
                    user_decision="",
                )
                continue
            if skip_remaining_duplicates:
                self._repo.update_clause(
                    clause.id,
                    clause_status=original_status,
                    chapter_id=original_chapter_id,
                    user_decision="skip_duplicate_all",
                )
                continue
            cache_key = ((clause.term or "").strip(), (clause.test_content or "").strip())
            existing_rows = duplicate_rows_cache.get(cache_key)
            if existing_rows is None:
                existing_rows = self._existing_rows_for_duplicate_check(document_id, clause)
                duplicate_rows_cache[cache_key] = existing_rows

            result = check_duplicate_candidates(
                document.folder_id,
                clause,
                document.specific_product,
                existing_rows,
            )
            matched_row = find_duplicate_candidate_row(
                document.folder_id,
                clause,
                document.specific_product,
                existing_rows,
            )
            if matched_row is None:
                updates = {"duplicate_flag": False, "duplicate_reason": "", "user_decision": ""}
                self._repo.update_clause(clause.id, **updates)
                continue

            self._repo.update_clause(
                clause.id,
                duplicate_flag=result.is_duplicate,
                duplicate_reason=result.reason,
            )
            decision = self._ask_duplicate_decision(document, clause, matched_row)
            if decision == "overwrite":
                self._repo.update_clause(
                    clause.id,
                    chapter_id=matched_row.get("id") or clause.chapter_id,
                    clause_status=ClauseStatus.PENDING_UPLOAD.value,
                    user_decision="overwrite",
                    duplicate_flag=True,
                    duplicate_reason=result.reason,
                )
            elif decision == "skip":
                self._repo.update_clause(
                    clause.id,
                    chapter_id=original_chapter_id,
                    clause_status=original_status,
                    user_decision="skip_duplicate",
                    duplicate_flag=True,
                    duplicate_reason=result.reason,
                )
            elif decision == "skip_all":
                self._repo.update_clause(
                    clause.id,
                    chapter_id=original_chapter_id,
                    clause_status=original_status,
                    user_decision="skip_duplicate_all",
                    duplicate_flag=True,
                    duplicate_reason=result.reason,
                )
                skip_remaining_duplicates = True
            else:
                self._repo.update_clause(
                    clause.id,
                    chapter_id=original_chapter_id,
                    clause_status=original_status,
                    user_decision=original_user_decision,
                )
                return False
        self._repo.reaggregate_document(document_id)
        self._load_documents()
        current = self._drawer.current_document()
        if current is not None and current.id == document_id:
            self._load_drawer_clauses(document_id)
        return True

    def _existing_rows_for_duplicate_check(self, document_id: int, clause=None) -> list[dict]:
        document = self._repo.get_document(document_id)
        if document is None or document.folder_id is None:
            return []
        client = self._current_backend_client()
        if client is None:
            return []
        try:
            params = {
                "folder_id": document.folder_id,
                "size": 100,
            }
            if clause is not None:
                params["term"] = clause.term
                params["test_content"] = clause.test_content
            specific_product = (document.specific_product or "").strip()
            if specific_product:
                params["specific_product"] = specific_product
            rows: list[dict] = []
            page_index = 0
            page_size = int(params["size"])
            while True:
                page = get_chapters(client, page=page_index, **params)
                rows.extend(
                    {
                        "id": chapter.id,
                        "folder_id": chapter.folder_id,
                        "term": chapter.term,
                        "test_content": chapter.test_content,
                        "specific_product": chapter.specific_product,
                    }
                    for chapter in page.content
                )
                if clause is None:
                    break
                if find_duplicate_candidate_row(
                    document.folder_id,
                    clause,
                    document.specific_product,
                    rows,
                ) is not None:
                    break
                if page.total_elements <= 0:
                    break
                if not page.content:
                    break
                if (page_index + 1) * page_size >= page.total_elements:
                    break
                page_index += 1
        except Exception:
            return []
        return rows

    def _ask_duplicate_decision(self, document, clause, matched_row: dict) -> str | None:
        specific_product = document.specific_product or "(空)"
        message_box = QMessageBox(self)
        message_box.setWindowTitle("检测到重复条款")
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(
            (
                f"条款号：{clause.term}\n"
                f"测试内容：{clause.test_content}\n"
                f"具体产品：{specific_product}\n"
                f"归属文件夹：{document.folder_name or document.folder_id or '(空)'}\n\n"
                "检测到已存在相同条款，请选择处理方式。"
            )
        )
        overwrite_button = message_box.addButton("覆盖", QMessageBox.ButtonRole.AcceptRole)
        skip_button = message_box.addButton("跳过当前条款", QMessageBox.ButtonRole.RejectRole)
        skip_all_button = message_box.addButton("后续重复全部跳过", QMessageBox.ButtonRole.DestructiveRole)
        message_box.exec()
        clicked = message_box.clickedButton()
        if clicked is overwrite_button:
            return "overwrite"
        if clicked is skip_button:
            return "skip"
        if clicked is skip_all_button:
            return "skip_all"
        return None

    def _ask_reupload_overwrite(self, document, clause) -> bool:
        message_box = QMessageBox(self)
        message_box.setWindowTitle("确认覆盖上传")
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(
            (
                f"条款号：{clause.term}\n"
                f"测试内容：{clause.test_content}\n"
                f"归属文件夹：{document.folder_name or document.folder_id or '(空)'}\n\n"
                "该条款已上传成功并记录了 chapter ID，重新上传将直接覆盖已有文档。是否继续？"
            )
        )
        overwrite_button = message_box.addButton("覆盖", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = message_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        message_box.exec()
        return message_box.clickedButton() is overwrite_button

    def _upload_selected_documents(self) -> None:
        if not self._ensure_backend_available():
            return
        if self._execution_worker is not None or self._clause_execution_worker is not None:
            return
        selected_documents = [
            document
            for document in self._selected_documents()
            if document.id is not None and is_document_executable(document.document_status)
        ]
        if not selected_documents:
            return
        current = self._drawer.current_document()
        if current is not None and current.id in {document.id for document in selected_documents}:
            if self._drawer.is_dirty(current.id):
                QMessageBox.warning(self, "提示", "请先保存修改后再上传")
                return
        ready_document_ids: list[int] = []
        for document in selected_documents:
            if document.id is None:
                continue
            if not self._resolve_upload_duplicates(document.id):
                return
            clauses = self._repo.get_clauses(document.id)
            if any(
                clause.clause_status in {
                    ClauseStatus.PENDING_UPLOAD.value,
                    ClauseStatus.UPLOAD_FAILED.value,
                }
                for clause in clauses
            ):
                ready_document_ids.append(document.id)
            else:
                self._repo.reaggregate_document(document.id)
        if not ready_document_ids:
            self._load_documents()
            return
        self._start_documents(ready_document_ids)

    def _start_documents(self, document_ids: list[int]) -> None:
        if not document_ids or self._execution_worker is not None or self._clause_execution_worker is not None:
            return
        client = self._current_backend_client()
        if client is None:
            self._ensure_backend_available()
            return
        for order, document_id in enumerate(document_ids):
            self._repo.update_document(document_id, is_queued=1, queue_order=order)
        self._load_documents()
        self._execution_worker = ChapterBatchExecutionWorker(self._repo, client, document_ids)
        self._execution_worker.progress_changed.connect(self._on_progress_changed)
        self._execution_worker.finished_ok.connect(self._on_execution_finished)
        self._execution_worker.failed.connect(self._on_execution_failed)
        self._execution_worker.finished.connect(self._clear_execution_worker)
        self._execution_worker.start()
        self._update_selected_label()

    def _start_clause_upload(self, document_id: int, clause_ids: list[int]) -> None:
        if self._execution_worker is not None or self._clause_execution_worker is not None:
            return
        client = self._current_backend_client()
        if client is None:
            self._ensure_backend_available()
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
        self._clause_execution_worker = ChapterClauseExecutionWorker(self._repo, client, document_id, ordered_clause_ids)
        self._clause_execution_worker.progress_changed.connect(self._on_progress_changed)
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
            if document.id is not None and not is_document_running(document.document_status)
        ]
        if not deletable_ids:
            return
        reply = QMessageBox.question(
            self,
            "删除记录",
            "将删除本地工作台记录及其拆分结果，不删除原始导入文件，也不删除后端条款或后端文档。是否继续？",
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
        self._service.delete_documents(deletable_ids)
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
        current = self._drawer.current_document()
        if current is not None and current.id is not None:
            self._progress_by_document_id.pop(current.id, None)
        self._load_documents()
        if current is not None and current.id is not None:
            self._load_drawer_clauses(current.id)

    def _on_execution_failed(self, message: str) -> None:
        QMessageBox.warning(self, "执行失败", message)
        self._load_documents()

    def _on_progress_changed(self, event: object) -> None:
        if not isinstance(event, ChapterBatchProgressEvent):
            return
        self._progress_by_document_id[event.document_id] = event
        self._load_documents()
        current = self._drawer.current_document()
        if current is not None and current.id == event.document_id:
            self._drawer._summary.setText(
                f"状态：{self._display_status_text(current.document_status)} | 进度：{event.percent}% | {event.message or '(处理中)'}"
            )

    def _on_processing_failed(self, document_id: int, message: str) -> None:
        self._progress_by_document_id.pop(document_id, None)
        self._load_documents()
        current = self._drawer.current_document()
        if current is not None and current.id == document_id:
            self._load_drawer_clauses(document_id)
        QMessageBox.warning(self, "预处理或拆分失败", message)

    def _on_processing_finished(self) -> None:
        if self._processing_worker is not None:
            for document_id in self._processing_worker._document_ids:
                self._progress_by_document_id.pop(document_id, None)
        self._load_documents()

    def _clear_processing_worker(self) -> None:
        self._processing_worker = None

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
        if action_name == "重试上传":
            self._set_clause_status_for_retry(clause_id, ClauseStatus.UPLOAD_FAILED.value)
        elif action_name == "上传":
            self._upload_single_clause(clause_id)
        elif action_name == "重新上传":
            self._reupload_single_clause(clause_id)
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
        if action_name == "重新上传":
            return clause.chapter_id is not None and clause.clause_status in {
                ClauseStatus.PENDING_UPLOAD.value,
                ClauseStatus.UPLOAD_SUCCESS.value,
                ClauseStatus.UPLOAD_FAILED.value,
            }
        if action_name == "上传" and clause.chapter_id is not None:
            return clause.clause_status == ClauseStatus.PENDING_UPLOAD.value
        if action_name == "重试上传" and clause.chapter_id is not None:
            return clause.clause_status == ClauseStatus.UPLOAD_FAILED.value
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
        self._on_upload_requested(clause.document_id, [clause_id])

    def _reupload_single_clause(self, clause_id: int) -> None:
        if not self._ensure_backend_available():
            return
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.document_id is None:
            return
        if clause.chapter_id is None:
            return
        document = self._repo.get_document(clause.document_id)
        if document is None or is_document_running(document.document_status):
            return
        if self._drawer.is_dirty(clause.document_id):
            QMessageBox.warning(self, "提示", "请先保存修改后再上传")
            return
        if not self._ask_reupload_overwrite(document, clause):
            return
        uploadable_clause_ids = self._collect_uploadable_clause_ids(
            clause.document_id,
            [clause_id],
            allow_reupload=True,
        )
        if not uploadable_clause_ids:
            self._repo.reaggregate_document(clause.document_id)
            self._load_documents()
            self._load_drawer_clauses(clause.document_id)
            return
        self._start_clause_upload(clause.document_id, uploadable_clause_ids)

    def _set_clause_status_for_retry(self, clause_id: int, from_status: str) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or clause.clause_status != from_status:
            return
        if not self._can_mutate_clause(clause):
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value,
            create_error="",
            upload_error="",
            last_action="retry",
        )

    def _restore_clause(self, clause_id: int) -> None:
        clause = self._repo.get_clause(clause_id)
        if clause is None or not self._can_mutate_clause(clause):
            return
        self._repo.update_clause(
            clause_id,
            clause_status=ClauseStatus.PENDING_UPLOAD.value,
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

    @staticmethod
    def _build_summary_text(document) -> str:
        return f"成功 {document.success_clause_count} / 失败 {document.failed_clause_count}"

    def _build_running_status_widget(self, document) -> QWidget:
        progress_event = self._progress_by_document_id.get(document.id or -1)
        tooltip = self._build_status_tooltip(document)
        if progress_event is not None and progress_event.message:
            tooltip = f"{tooltip}\n进度：{progress_event.percent}%\n{progress_event.message}"
        widget = _RunningStatusWidget(
            self._display_status_text(document.document_status),
            progress_event.percent if progress_event is not None else 0,
            self._table,
        )
        widget.setToolTip(tooltip)
        return widget

    def _ensure_documents_have_standard(self, document_ids: list[int]) -> list[int]:
        ready_ids: list[int] = []
        for document_id in document_ids:
            document = self._repo.get_document(document_id)
            if document is None:
                continue
            if (document.standard or "").strip():
                ready_ids.append(document_id)
                continue
            value, accepted = QInputDialog.getText(
                self,
                "补录标准号",
                f"文档 {document.file_name or document_id} 未识别到标准号，请输入标准号：",
                text="",
            )
            if not accepted:
                ready_ids.append(document_id)
                continue
            normalized = value.strip()
            if not normalized:
                ready_ids.append(document_id)
                continue
            self._repo.update_document(document_id, standard=normalized)
            ready_ids.append(document_id)
        return ready_ids

    def _import_selected_paths(self, paths: list[str]) -> None:
        split_mode = self._choose_import_mode()
        if split_mode is None:
            return
        documents = self._service.import_documents(paths, split_mode=split_mode)
        document_ids = [document.id for document in documents if document is not None and document.id is not None]
        document_ids = self._ensure_documents_have_standard(document_ids)
        self._load_documents()
        self._start_processing_documents(document_ids)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._drawer.isVisible():
            self._layout_drawer()
