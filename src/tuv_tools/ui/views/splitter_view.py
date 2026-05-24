"""文档拆分视图 - 导入、列表、批量拆分"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.splitter import build_sections, export_docx_outputs
from tuv_tools.core.splitter.exporting import get_output_base_dir_name
from tuv_tools.core.splitter.models import CoreProgressEvent, SplitCancelled
from tuv_tools.core.splitter.ui_helpers import build_split_summary, resolve_output_root
from tuv_tools.core.splitter.utils import CleanPatterns, safe_name
from tuv_tools.ui.views.splitter_progress import ProgressThrottler, SplitProgressMapper
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from tuv_tools.ui.widgets.clause_panel import ClauseOverlay
from tuv_tools.ui.widgets.document_list import DocumentTable
from tuv_tools.ui.widgets.toast import Toast
from tuv_tools.core.preparing.worker import PreparingWorker


class SplitWorker(QThread):
    """后台拆分工作线程"""
    doc_started = Signal(int)
    progress_detail = Signal(object)
    doc_done = Signal(int, str, int)  # (doc_id, status, section_count)
    doc_error = Signal(int, str)  # (doc_id, error_message)
    doc_cancelled = Signal(int)
    batch_cancelled = Signal()

    def __init__(self, items: list[tuple[int, str, str]], output_root: str, patterns: CleanPatterns):
        """items: [(doc_id, file_path, output_dir), ...]"""
        super().__init__()
        self._items = items
        self._output_root = output_root
        self._patterns = patterns
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._items)
        for idx, (doc_id, file_path, output_subdir) in enumerate(self._items, 1):
            if self._cancelled:
                self.batch_cancelled.emit()
                break

            docx_path = Path(file_path)
            self.doc_started.emit(doc_id)
            mapper = SplitProgressMapper(doc_id, docx_path.name, idx, total)
            throttler = ProgressThrottler()

            def should_cancel() -> bool:
                return self._cancelled

            def on_core_progress(event: CoreProgressEvent) -> None:
                if self._cancelled:
                    raise SplitCancelled("Document split cancelled")
                if throttler.should_emit(event):
                    self.progress_detail.emit(mapper.to_ui_event(event))

            try:
                on_core_progress(CoreProgressEvent("validating", "校验文件", 0, 1, f"校验 {docx_path.name}"))
                if not docx_path.exists():
                    self.doc_error.emit(doc_id, f"文件不存在: {file_path}")
                    continue
                on_core_progress(CoreProgressEvent("validating", "校验文件", 1, 1, "文件存在"))

                sections = build_sections(docx_path, progress=on_core_progress, should_cancel=should_cancel)
                if sections:
                    output_path = resolve_output_root(docx_path, self._output_root, output_subdir)
                    base_name = get_output_base_dir_name(docx_path)
                    staging_root = output_path / f"{base_name}.partial-{doc_id}"
                    export_docx_outputs(
                        docx_path,
                        sections,
                        output_path,
                        self._patterns,
                        progress=on_core_progress,
                        should_cancel=should_cancel,
                        staging_root=staging_root,
                    )
                self.doc_done.emit(doc_id, "completed", len(sections))
            except SplitCancelled:
                self.doc_cancelled.emit(doc_id)
                self.batch_cancelled.emit()
                break
            except Exception as exc:
                self.doc_error.emit(doc_id, str(exc))

class ParseWorker(QThread):
    """后台解析工作线程（用于条款面板预览）"""
    result_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, docx_path: Path):
        super().__init__()
        self._docx_path = docx_path

    def run(self) -> None:
        try:
            sections = build_sections(self._docx_path)
            self.result_ready.emit(sections)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class SplitterView(QWidget):
    """文档拆分视图"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._worker: SplitWorker | None = None
        self._parse_worker: ParseWorker | None = None
        self._preparing_worker: PreparingWorker | None = None
        self._preparing_pending_ids: set[int] = set()
        self._split_success = 0
        self._split_failed = 0
        self._split_cancelled = False
        self._split_total = 0
        from tuv_tools.config.database import DatabaseManager
        self._db = DatabaseManager()
        self._setup_ui()
        self._load_documents()
        self._resume_preparing_if_needed()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("文档拆分")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        toolbar = QHBoxLayout()
        import_file_btn = QPushButton("导入文件")
        import_file_btn.clicked.connect(self._import_files)
        toolbar.addWidget(import_file_btn)
        import_dir_btn = QPushButton("导入文件夹")
        import_dir_btn.clicked.connect(self._import_dir)
        toolbar.addWidget(import_dir_btn)
        toolbar.addSpacing(16)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文件名或标准号...")
        self._search_edit.textChanged.connect(self._on_search)
        self._search_edit.setClearButtonEnabled(True)
        toolbar.addWidget(self._search_edit)
        layout.addLayout(toolbar)

        self._table = DocumentTable()
        self._table.files_dropped.connect(self._add_paths)
        self._table.split_requested.connect(self._split_single)
        self._table.resume_preparing_requested.connect(self._resume_preparing)
        self._table.skip_preparing_split_requested.connect(self._skip_preparing_and_split)
        self._table.show_error_requested.connect(self._show_document_error)
        self._table.open_output_requested.connect(self._open_output_dir)
        self._table.double_clicked.connect(self._show_clause_panel)
        self._table.selection_empty.connect(self._on_empty)
        layout.addWidget(self._table, stretch=1)

        bottom = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setStyleSheet(CHECKBOX_STYLE)
        self._select_all_cb.toggled.connect(self._table.set_all_checked)
        bottom.addWidget(self._select_all_cb)
        self._selected_label = QLabel("已选 0/0 项")
        self._table.checked_changed.connect(self._update_selected_label)
        bottom.addWidget(self._selected_label)
        bottom.addStretch()
        self._split_btn = QPushButton("开始拆分选中")
        self._split_btn.setStyleSheet(self._action_btn_style("#4a9eff"))
        self._split_btn.clicked.connect(self._start_batch_split)
        bottom.addWidget(self._split_btn)
        layout.addLayout(bottom)

        self._clause_panel = ClauseOverlay(self)

        self._progress_title = QLabel("")
        self._progress_title.setVisible(False)
        self._progress_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._progress_detail = QLabel("")
        self._progress_detail.setVisible(False)
        self._progress_detail.setStyleSheet("color: #999; font-size: 12px;")
        layout.addWidget(self._progress_title)
        layout.addWidget(self._progress_detail)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedHeight(22)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #2b2d30;
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                color: #dcdcdc;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background-color: #4a9eff;
                border-radius: 3px;
            }
        """)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setFixedWidth(90)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555; color: #dcdcdc;
                border: none; border-radius: 4px; padding: 4px 12px;
            }
            QPushButton:hover { background-color: #666; }
        """)
        self._cancel_btn.clicked.connect(self._cancel_split)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self._progress, stretch=1)
        progress_row.addWidget(self._cancel_btn)
        layout.addLayout(progress_row)

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

    def _import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 DOCX 文件", "", "Word Documents (*.docx)"
        )
        if paths:
            self._add_paths(paths)

    def _import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not path:
            return
        files: list[str] = []
        for root, _dirs, filenames in os.walk(path):
            for f in filenames:
                if f.lower().endswith(".docx") and not f.startswith("~$"):
                    files.append(os.path.join(root, f))
        if files:
            self._add_paths(files)

    def _add_paths(self, paths: list[str]) -> None:
        db = self._db
        added = 0
        new_items: list[tuple[int, str]] = []
        for fp in paths:
            try:
                before = len(db.get_documents())
                doc_id = db.add_document(fp)
                after = len(db.get_documents())
                if after > before:
                    added += 1
                    db.update_document_status(doc_id, "preparing")
                    new_items.append((doc_id, fp))
                    self._preparing_pending_ids.add(doc_id)
            except Exception:
                pass
        self._load_documents()
        if new_items:
            self._ensure_preparing_worker()
            self._preparing_worker.add_items(new_items)  # type: ignore[union-attr]
            msg = f"已导入 {added} 个文档"
            if self._preparing_worker and self._preparing_worker.isRunning():
                msg += f"（队列 +{len(new_items)}，正在后台预处理...）"
            Toast(self, msg)
        elif added > 0:
            Toast(self, f"已导入 {added} 个文档")

    def _ensure_preparing_worker(self) -> None:
        """确保全局预处理 worker 存在（懒创建、单例）"""
        if self._preparing_worker is None or not self._preparing_worker.isRunning():
            self._preparing_worker = PreparingWorker()
            self._preparing_worker.doc_prepared.connect(self._on_doc_prepared)
            self._preparing_worker.doc_error.connect(self._on_prepare_error)
            self._preparing_worker.start()

    def _load_documents(self) -> None:
        docs = self._db.get_documents()
        self._table.load_documents(docs)
        self._update_selected_label()
        if not docs:
            self._on_empty()

    def _resume_preparing_if_needed(self) -> None:
        """启动时检查是否存在残留 preparing 文档。"""
        docs = self._db.get_preparing_documents()
        if not docs:
            return

        preview = "\n".join(doc["file_name"] for doc in docs[:5])
        extra = ""
        if len(docs) > 5:
            extra = f"\n以及另外 {len(docs) - 5} 个文件"
        message = (
            "检测到上次退出时未完成的预处理任务。\n"
            f"共 {len(docs)} 个文件：\n{preview}{extra}\n\n"
            "是否继续后台预处理？"
        )
        reply = QMessageBox.question(
            self,
            "检测到未完成的预处理任务",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            queued: list[tuple[int, str]] = []
            failed_ids: list[int] = []
            for doc in docs:
                file_path = doc["file_path"]
                if os.path.exists(file_path):
                    queued.append((doc["id"], file_path))
                else:
                    failed_ids.append(doc["id"])
                    self._db.update_document_status(doc["id"], "failed", error="Source file missing")
            if queued:
                self._ensure_preparing_worker()
                self._preparing_worker.add_items(queued)  # type: ignore[union-attr]
                self._preparing_pending_ids.update(doc_id for doc_id, _path in queued)
            for doc in docs:
                refreshed = self._db.get_document(doc["id"])
                if refreshed is not None:
                    self._table.update_row_status(
                        doc["id"],
                        refreshed["status"],
                        refreshed.get("last_section_count"),
                    )
            return

        self._db.update_documents_status([doc["id"] for doc in docs], "prepare_paused")
        for doc in docs:
            refreshed = self._db.get_document(doc["id"])
            if refreshed is not None:
                self._table.update_row_status(
                    doc["id"],
                    refreshed["status"],
                    refreshed.get("last_section_count"),
                )

    def _on_empty(self) -> None:
        self._split_btn.setEnabled(False)

    def _on_search(self, text: str) -> None:
        self._table.filter_by_text(text)

    def _update_selected_label(self) -> None:
        checked = self._table.checked_count()
        total = self._table.total_count()
        self._selected_label.setText(f"已选 {checked}/{total} 项")
        self._split_btn.setEnabled(checked > 0)

    def _split_single(self, doc_id: int) -> None:
        self._table.set_single_checked(doc_id)
        self._update_selected_label()
        self._start_batch_split()

    def _resume_preparing(self, doc_id: int) -> None:
        doc = self._db.get_document(doc_id)
        if not doc:
            return
        self._db.update_document_status(doc_id, "preparing")
        self._table.update_row_status(doc_id, "preparing")
        if not os.path.exists(doc["file_path"]):
            self._db.update_document_status(doc_id, "failed", error="Source file missing")
            self._table.update_row_status(doc_id, "failed")
            return
        self._ensure_preparing_worker()
        self._preparing_worker.add_items([(doc_id, doc["file_path"])])  # type: ignore[union-attr]
        self._preparing_pending_ids.add(doc_id)

    def _skip_preparing_and_split(self, doc_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "确认跳过预处理",
            "该文档尚未完成预处理，继续拆分可能导致复选框未统一。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        doc = self._db.get_document(doc_id)
        if not doc or not os.path.exists(doc["file_path"]):
            Toast(self, "没有可拆分的文档")
            return

        patterns = self._settings.load_inline_clean_patterns()
        output_root = self._db.get_config("splitter.output_path", "")

        self._progress_title.setVisible(True)
        self._progress_title.setText("准备拆分文档...")
        self._progress_detail.setVisible(True)
        self._progress_detail.setText("")
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("取消")
        self._split_btn.setEnabled(False)
        self._split_success = 0
        self._split_failed = 0
        self._split_cancelled = False
        self._split_total = 1

        self._worker = SplitWorker([(doc_id, doc["file_path"], "")], output_root, patterns)
        self._worker.doc_started.connect(self._on_doc_started)
        self._worker.progress_detail.connect(self._on_progress_detail)
        self._worker.doc_done.connect(self._on_doc_done)
        self._worker.doc_error.connect(self._on_doc_error)
        self._worker.doc_cancelled.connect(self._on_doc_cancelled)
        self._worker.batch_cancelled.connect(self._on_batch_cancelled)
        self._worker.finished.connect(self._on_all_done)
        self._worker.start()

    def _start_batch_split(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        checked_ids = self._table.checked_ids()
        if not checked_ids:
            return

        db = self._db
        items: list[tuple[int, str, str]] = []
        for doc_id in checked_ids:
            doc = db.get_document(doc_id)
            if doc and os.path.exists(doc["file_path"]):
                items.append((doc_id, doc["file_path"], ""))

        if not items:
            Toast(self, "没有可拆分的文档")
            return

        patterns = self._settings.load_inline_clean_patterns()
        output_root = db.get_config("splitter.output_path", "")

        self._progress_title.setVisible(True)
        self._progress_title.setText("准备拆分文档...")
        self._progress_detail.setVisible(True)
        self._progress_detail.setText("")
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("取消")
        self._split_btn.setEnabled(False)
        self._split_success = 0
        self._split_failed = 0
        self._split_cancelled = False
        self._split_total = len(items)

        self._worker = SplitWorker(items, output_root, patterns)
        self._worker.doc_started.connect(self._on_doc_started)
        self._worker.progress_detail.connect(self._on_progress_detail)
        self._worker.doc_done.connect(self._on_doc_done)
        self._worker.doc_error.connect(self._on_doc_error)
        self._worker.doc_cancelled.connect(self._on_doc_cancelled)
        self._worker.batch_cancelled.connect(self._on_batch_cancelled)
        self._worker.finished.connect(self._on_all_done)
        self._worker.start()

    def _on_doc_started(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "processing")
        self._table.update_row_status(doc_id, "processing")

    def _on_progress_detail(self, event) -> None:
        title = f"第 {event.doc_index}/{event.doc_total} 个文档 | {event.file_name}"
        self._progress_title.setText(title)
        self._progress_title.setToolTip(event.file_name)
        self._progress_detail.setText(event.message)
        self._progress.setValue(event.overall_percent)

    def _on_doc_done(self, doc_id: int, status: str, section_count: int) -> None:
        self._split_success += 1
        self._db.update_document_status(doc_id, status, section_count)
        self._table.update_row_status(doc_id, status, section_count)

    def _on_doc_error(self, doc_id: int, error: str) -> None:
        self._split_failed += 1
        self._db.update_document_status(doc_id, "failed", error=error)
        self._table.update_row_status(doc_id, "failed")

    def _on_doc_cancelled(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "cancelled")
        self._table.update_row_status(doc_id, "cancelled")

    def _on_batch_cancelled(self) -> None:
        self._split_cancelled = True

    def _on_all_done(self) -> None:
        self._progress_title.setVisible(False)
        self._progress_detail.setVisible(False)
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._split_btn.setEnabled(True)
        self._load_documents()
        Toast(self, build_split_summary(
            success=self._split_success,
            failed=self._split_failed,
            cancelled=self._split_cancelled,
            total=self._split_total,
        ))

    def _cancel_split(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setText("正在取消...")
            self._progress_detail.setText("正在取消，等待当前安全检查点...")

    def _on_doc_prepared(self, doc_id: int) -> None:
        self._db.update_document_status(doc_id, "pending")
        self._table.update_row_status(doc_id, "pending")
        self._preparing_pending_ids.discard(doc_id)
        if not self._preparing_pending_ids:
            Toast(self, "所有预处理已完成")

    def _on_prepare_error(self, doc_id: int, error: str) -> None:
        self._db.update_document_status(doc_id, "prepare_failed", error=error)
        self._table.update_row_status(doc_id, "prepare_failed")
        Toast(self, f"预处理失败: {error}")
        self._preparing_pending_ids.discard(doc_id)
        if not self._preparing_pending_ids:
            Toast(self, "所有预处理已完成")

    def _show_document_error(self, doc_id: int) -> None:
        doc = self._db.get_document(doc_id)
        if not doc:
            return
        error = doc.get("error_message") or "未知错误"
        QMessageBox.information(self, "失败原因", error)

    def _show_clause_panel(self, doc_id: int) -> None:
        db = self._db
        doc = db.get_document(doc_id)
        if not doc:
            return

        docx_path = Path(doc["file_path"])
        file_name = doc.get("file_name", "")
        self._clause_panel.set_title(file_name)
        self._clause_panel.show_loading()
        self._clause_panel.expand()

        if not docx_path.exists():
            self._clause_panel.show_error("原文件不存在")
            return

        self._parse_worker = ParseWorker(docx_path)
        self._parse_worker.result_ready.connect(self._clause_panel.set_sections)
        self._parse_worker.error_occurred.connect(self._clause_panel.show_error)
        self._parse_worker.start()

    def _open_output_dir(self, doc_id: int | None = None) -> None:
        db = self._db
        output_root = db.get_config("splitter.output_path", "")

        target_id = doc_id
        if target_id is None:
            checked_ids = self._table.checked_ids()
            target_id = checked_ids[0] if checked_ids else None

        doc = db.get_document(target_id) if target_id else None
        std_num = doc.get("standard_number") if doc else None

        if output_root and std_num:
            clause_dir = os.path.join(output_root, std_num)
            if os.path.isdir(clause_dir):
                os.startfile(clause_dir)
                return

        if not output_root and doc:
            base_dir = os.path.join(
                str(Path(doc["file_path"]).parent),
                safe_name(std_num or Path(doc["file_path"]).stem),
            )
            if os.path.isdir(base_dir):
                os.startfile(base_dir)
                return

        if output_root and os.path.isdir(output_root):
            os.startfile(output_root)
            return

        if doc and os.path.exists(doc["file_path"]):
            parent = str(Path(doc["file_path"]).parent)
            if os.path.isdir(parent):
                os.startfile(parent)
                return

        Toast(self, "输出目录不存在，请先拆分文档")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._clause_panel.isVisible():
            self._clause_panel.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.wait(3000)
        if self._preparing_worker and self._preparing_worker.isRunning():
            self._preparing_worker.stop()
            self._preparing_worker.wait(3000)
        super().closeEvent(event)
