"""文档拆分功能视图"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.splitter import build_sections, export_docx_outputs
from tuv_tools.core.splitter.utils import CleanPatterns


@dataclass
class ProcessResult:
    file_name: str
    section_count: int
    success: bool
    error: str = ""


class SplitWorker(QThread):
    """后台拆分工作线程"""
    progress = Signal(int, int)  # (current, total)
    file_done = Signal(object)   # ProcessResult
    finished_all = Signal()

    def __init__(self, files: list[Path], output_root: Path, patterns: CleanPatterns, recursive: bool):
        super().__init__()
        self._files = files
        self._output_root = output_root
        self._patterns = patterns
        self._recursive = recursive
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._files)
        for idx, docx_path in enumerate(self._files):
            if self._cancelled:
                break
            self.progress.emit(idx, total)
            try:
                sections = build_sections(docx_path)
                if sections:
                    export_docx_outputs(docx_path, sections, self._output_root, self._patterns)
                self.file_done.emit(ProcessResult(
                    file_name=docx_path.name,
                    section_count=len(sections),
                    success=True,
                ))
            except Exception as exc:
                self.file_done.emit(ProcessResult(
                    file_name=docx_path.name,
                    section_count=0,
                    success=False,
                    error=str(exc),
                ))
        self.progress.emit(total, total)
        self.finished_all.emit()


class SplitterView(QWidget):
    """文档拆分视图"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._worker: SplitWorker | None = None
        self._results: list[ProcessResult] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 标题
        title = QLabel("DOCX 测试模板拆分")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # 输入配置区
        config_group = QGroupBox("配置")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)

        # 输入路径
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("输入路径:"))
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("选择 DOCX 文件或包含 DOCX 的文件夹")
        input_row.addWidget(self._input_edit)
        self._input_file_btn = QPushButton("选择文件")
        self._input_file_btn.clicked.connect(self._select_input_file)
        input_row.addWidget(self._input_file_btn)
        self._input_dir_btn = QPushButton("选择文件夹")
        self._input_dir_btn.clicked.connect(self._select_input_dir)
        input_row.addWidget(self._input_dir_btn)
        config_layout.addLayout(input_row)

        # 输出路径
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("输出路径:"))
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("留空则自动生成在输入路径旁的 split_output 目录")
        output_row.addWidget(self._output_edit)
        self._output_btn = QPushButton("选择")
        self._output_btn.clicked.connect(self._select_output_dir)
        output_row.addWidget(self._output_btn)
        config_layout.addLayout(output_row)

        # 规则文件
        rules_row = QHBoxLayout()
        rules_row.addWidget(QLabel("清洗规则:"))
        self._rules_edit = QLineEdit()
        self._rules_edit.setText(str(self._settings.default_rules_path))
        rules_row.addWidget(self._rules_edit)
        self._rules_btn = QPushButton("选择")
        self._rules_btn.clicked.connect(self._select_rules_file)
        rules_row.addWidget(self._rules_btn)
        config_layout.addLayout(rules_row)

        # 选项
        options_row = QHBoxLayout()
        self._recursive_cb = QCheckBox("递归扫描子目录")
        options_row.addWidget(self._recursive_cb)
        options_row.addStretch()
        config_layout.addLayout(options_row)

        layout.addWidget(config_group)

        # 操作按钮 + 进度条
        action_row = QHBoxLayout()
        self._run_btn = QPushButton("开始拆分")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 0 24px;
            }
            QPushButton:hover { background-color: #3a8eef; }
            QPushButton:disabled { background-color: #666666; }
        """)
        self._run_btn.clicked.connect(self._start_split)
        action_row.addWidget(self._run_btn)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(36)
        self._progress.setVisible(False)
        action_row.addWidget(self._progress)
        layout.addLayout(action_row)

        # 结果表格
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["文件名", "条款数", "状态", "备注"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        # 状态栏
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(self._status)

    # ── 文件选择 ──────────────────────────────────────────

    def _select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 DOCX 文件", "", "Word Documents (*.docx)"
        )
        if path:
            self._input_edit.setText(path)

    def _select_input_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self._input_edit.setText(path)

    def _select_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._output_edit.setText(path)

    def _select_rules_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择清洗规则文件", "", "JSON Files (*.json)"
        )
        if path:
            self._rules_edit.setText(path)

    # ── 拆分逻辑 ──────────────────────────────────────────

    def _discover_files(self, input_path: Path, output_root: Path) -> list[Path]:
        excluded = [output_root.resolve()]
        if input_path.is_file():
            return [input_path]
        recursive = self._recursive_cb.isChecked()
        iterator = input_path.rglob("*.docx") if recursive else input_path.glob("*.docx")
        discovered: list[Path] = []
        for path in iterator:
            resolved = path.resolve()
            if not resolved.is_file():
                continue
            if resolved.name.startswith("~$"):
                continue
            if any(self._is_within(resolved, root) for root in excluded):
                continue
            discovered.append(resolved)
        return sorted(discovered)

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _start_split(self):
        if self._worker and self._worker.isRunning():
            return

        input_text = self._input_edit.text().strip()
        if not input_text:
            self._status.setText("请先选择输入路径")
            return

        input_path = Path(input_text)
        if not input_path.exists():
            self._status.setText("输入路径不存在")
            return

        output_text = self._output_edit.text().strip()
        if output_text:
            output_root = Path(output_text)
        elif input_path.is_file():
            output_root = input_path.parent / "split_output"
        else:
            output_root = input_path / "split_output"
        output_root.mkdir(parents=True, exist_ok=True)

        rules_path = Path(self._rules_edit.text().strip())
        if not rules_path.exists():
            self._status.setText("清洗规则文件不存在")
            return
        patterns = self._settings.load_inline_clean_patterns(rules_path)

        files = self._discover_files(input_path, output_root)
        if not files:
            self._status.setText("未找到任何 DOCX 文件")
            return

        self._results.clear()
        self._table.setRowCount(0)
        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setMaximum(len(files))
        self._progress.setValue(0)
        self._status.setText(f"正在处理 {len(files)} 个文件...")

        self._worker = SplitWorker(files, output_root, patterns, self._recursive_cb.isChecked())
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)

    def _on_file_done(self, result: ProcessResult):
        self._results.append(result)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(result.file_name))
        self._table.setItem(row, 1, QTableWidgetItem(str(result.section_count)))
        status_item = QTableWidgetItem("成功" if result.success else "失败")
        if not result.success:
            status_item.setForeground(Qt.GlobalColor.red)
        self._table.setItem(row, 2, status_item)
        self._table.setItem(row, 3, QTableWidgetItem(result.error))

    def _on_finished(self):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        success = sum(1 for r in self._results if r.success)
        failed = len(self._results) - success
        total_sections = sum(r.section_count for r in self._results)
        self._status.setText(
            f"完成: {success} 个文件成功, {failed} 个失败, 共拆分 {total_sections} 个条款"
        )

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
