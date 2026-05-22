"""文档拆分视图 — 导入→列表→批量拆分"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.splitter import build_sections, export_docx_outputs
from tuv_tools.core.splitter.utils import safe_name
from tuv_tools.core.splitter.utils import CleanPatterns
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from tuv_tools.ui.widgets.clause_panel import ClauseOverlay
from tuv_tools.ui.widgets.document_list import DocumentTable
from tuv_tools.ui.widgets.toast import Toast


class SplitWorker(QThread):
    """后台拆分工作线程"""
    progress = Signal(int, int)  # (current, total)
    doc_done = Signal(int, str, int)  # (doc_id, status, section_count)
    doc_error = Signal(int, str)  # (doc_id, error_message)

    def __init__(self, items: list[tuple[int, str, str]], output_root: str, patterns: CleanPatterns):
        """items: [(doc_id, file_path, output_dir), ...]"""
        super().__init__()
        self._items = items
        self._output_root = output_root
        self._patterns = patterns
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._items)
        for idx, (doc_id, file_path, output_subdir) in enumerate(self._items):
            if self._cancelled:
                break
            self.progress.emit(idx + 1, total)
            docx_path = Path(file_path)
            try:
                if not docx_path.exists():
                    self.doc_error.emit(doc_id, f"文件不存在: {file_path}")
                    continue
                sections = build_sections(docx_path)
                if sections:
                    output_path = resolve_output_root(docx_path, self._output_root, output_subdir)
                    export_docx_outputs(docx_path, sections, output_path, self._patterns)
                self.doc_done.emit(doc_id, "completed", len(sections))
            except Exception as exc:
                self.doc_error.emit(doc_id, str(exc))
        self.progress.emit(total, total)


def resolve_output_root(docx_path: Path, output_root: str, output_subdir: str = "") -> Path:
    """根据配置解析导出根目录；未配置时回退到原文档所在目录。"""
    if output_subdir:
        return Path(output_subdir)
    if output_root:
        return Path(output_root)
    return docx_path.parent


class ParseWorker(QThread):
    """后台解析工作线程（用于条款面板预览）"""
    result_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, docx_path: Path):
        super().__init__()
        self._docx_path = docx_path

    def run(self):
        try:
            sections = build_sections(self._docx_path)
            self.result_ready.emit(sections)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class SplitterView(QWidget):
    """文档拆分视图（新版）"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._worker: SplitWorker | None = None
        self._parse_worker: ParseWorker | None = None
        from tuv_tools.config.database import DatabaseManager
        self._db = DatabaseManager()
        self._setup_ui()
        self._load_documents()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel("文档拆分")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 工具栏：导入 + 搜索
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

        # 文档列表
        self._table = DocumentTable()
        self._table.split_requested.connect(self._split_single)
        self._table.open_output_requested.connect(self._open_output_dir)
        self._table.double_clicked.connect(self._show_clause_panel)
        self._table.selection_empty.connect(self._on_empty)
        layout.addWidget(self._table, stretch=1)

        # 底部操作栏
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

        # 浮层条款面板
        self._clause_panel = ClauseOverlay(self)

        # 进度条
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
        self._cancel_btn.setFixedWidth(60)
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

    # ---- 导入 ----

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
        for fp in paths:
            try:
                before = len(db.get_documents())
                db.add_document(fp)
                after = len(db.get_documents())
                if after > before:
                    added += 1
            except Exception:
                pass
        self._load_documents()
        if added > 0:
            Toast(self, f"已导入 {added} 个文档")

    # ---- 文档列表 ----

    def _load_documents(self) -> None:
        docs = self._db.get_documents()
        self._table.load_documents(docs)
        self._update_selected_label()
        if not docs:
            self._on_empty()

    def _on_empty(self) -> None:
        self._split_btn.setEnabled(False)

    def _on_search(self, text: str) -> None:
        self._table.filter_by_text(text)

    def _update_selected_label(self) -> None:
        checked = self._table.checked_count()
        total = self._table.total_count()
        self._selected_label.setText(f"已选 {checked}/{total} 项")
        self._split_btn.setEnabled(checked > 0)

    # ---- 拆分 ----

    def _split_single(self, doc_id: int) -> None:
        self._table.set_single_checked(doc_id)
        self._update_selected_label()
        self._start_batch_split()

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

        self._progress.setVisible(True)
        self._progress.setMaximum(len(items))
        self._progress.setValue(0)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._split_btn.setEnabled(False)

        self._worker = SplitWorker(items, output_root, patterns)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.doc_done.connect(self._on_doc_done)
        self._worker.doc_error.connect(self._on_doc_error)
        self._worker.finished.connect(self._on_all_done)
        self._worker.start()

    def _on_doc_done(self, doc_id: int, status: str, section_count: int) -> None:
        self._db.update_document_status(doc_id, status, section_count)
        self._table.update_row_status(doc_id, status, section_count)

    def _on_doc_error(self, doc_id: int, error: str) -> None:
        self._db.update_document_status(doc_id, "failed", error=error)
        self._table.update_row_status(doc_id, "failed")

    def _on_all_done(self) -> None:
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._split_btn.setEnabled(True)
        self._load_documents()
        Toast(self, "拆分完成")

    def _cancel_split(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)

    # ---- 条款面板 ----

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

    # ---- 输出目录 ----

    def _open_output_dir(self, doc_id: int | None = None) -> None:
        db = self._db
        output_root = db.get_config("splitter.output_path", "")

        # 定位目标文档
        target_id = doc_id
        if target_id is None:
            checked_ids = self._table.checked_ids()
            target_id = checked_ids[0] if checked_ids else None

        doc = db.get_document(target_id) if target_id else None
        std_num = doc.get("standard_number") if doc else None

        # 优先：output_root/标准号 目录
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

        # 回退：output_root 目录
        if output_root and os.path.isdir(output_root):
            os.startfile(output_root)
            return

        # 最终回退：文档所在目录
        if doc and os.path.exists(doc["file_path"]):
            parent = str(Path(doc["file_path"]).parent)
            if os.path.isdir(parent):
                os.startfile(parent)
                return

        Toast(self, "输出目录不存在，请先拆分文档")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._clause_panel.isVisible():
            self._clause_panel.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.wait(3000)
        super().closeEvent(event)
