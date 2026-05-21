"""条款管理视图"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.api import create_chapter, delete_chapters, get_chapters, update_chapter
from tuv_tools.core.chapter.auth import auto_login
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import ApiConfig, Chapter, ChapterStatus, PageResult, STATUS_LABELS


class ChapterWorker(QThread):
    """后台网络操作线程"""
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.result_ready.emit(result)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class ChapterView(QWidget):
    """条款管理视图"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._client: TuvClient | None = None
        self._config: ApiConfig | None = None
        self._worker: ChapterWorker | None = None
        self._current_page = 0
        self._page_size = 20
        self._total = 0
        self._connected = False
        self._setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._connected:
            self._try_connect()

    def _try_connect(self):
        self._config = self._settings.load_api_config()
        if not self._config:
            self._show_settings_dialog()
            return
        self._client = TuvClient(self._config.base_url, self._config.request_timeout)
        self._run_worker(
            lambda: auto_login(self._client, self._config),
            self._on_login_result,
            self._on_login_error,
        )

    def _on_login_result(self, success):
        if success:
            self._connected = True
            self._status_label.setText("● 已连接")
            self._status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self._fetch_chapters()
        else:
            self._status_label.setText("● 未连接")
            self._status_label.setStyleSheet("color: #f44336; font-weight: bold;")

    def _on_login_error(self, msg):
        self._status_label.setText("● 未连接")
        self._status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        self._info_label.setText(f"Connection error: {msg}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # 顶部状态栏
        top_row = QHBoxLayout()
        self._status_label = QLabel("● 未连接")
        self._status_label.setStyleSheet("color: #888; font-weight: bold;")
        top_row.addWidget(self._status_label)
        top_row.addStretch()
        self._settings_btn = QPushButton("⚙ 设置")
        self._settings_btn.clicked.connect(self._show_settings_dialog)
        top_row.addWidget(self._settings_btn)
        layout.addLayout(top_row)

        # 查询工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Folder:"))
        self._folder_edit = QLineEdit()
        self._folder_edit.setFixedWidth(60)
        toolbar.addWidget(self._folder_edit)
        toolbar.addWidget(QLabel("条款号:"))
        self._term_edit = QLineEdit()
        self._term_edit.setFixedWidth(80)
        toolbar.addWidget(self._term_edit)
        toolbar.addWidget(QLabel("标准:"))
        self._standard_edit = QLineEdit()
        self._standard_edit.setFixedWidth(100)
        toolbar.addWidget(self._standard_edit)
        toolbar.addWidget(QLabel("状态:"))
        self._status_combo = QComboBox()
        self._status_combo.addItem("全部", None)
        for val, label in STATUS_LABELS.items():
            self._status_combo.addItem(label, val)
        self._status_combo.setFixedWidth(80)
        toolbar.addWidget(self._status_combo)

        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._on_query)
        toolbar.addWidget(self._query_btn)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._on_clear_filters)
        toolbar.addWidget(self._clear_btn)
        toolbar.addStretch()
        self._add_btn = QPushButton("+ 新增")
        self._add_btn.setStyleSheet(
            "background-color:#4caf50;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:6px 16px;"
        )
        self._add_btn.clicked.connect(self._show_create_dialog)
        toolbar.addWidget(self._add_btn)
        layout.addLayout(toolbar)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["ID", "条款号", "标准", "版本", "测试内容", "状态", "操作"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        # 分页
        page_row = QHBoxLayout()
        self._prev_btn = QPushButton("◀ 上一页")
        self._prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self._prev_btn)
        self._page_label = QLabel("第 0/0 页")
        page_row.addWidget(self._page_label)
        self._next_btn = QPushButton("下一页 ▶")
        self._next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self._next_btn)
        page_row.addStretch()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888; font-size: 12px;")
        page_row.addWidget(self._info_label)
        layout.addLayout(page_row)

    def _build_filters(self) -> dict:
        filters = {}
        folder_text = self._folder_edit.text().strip()
        if folder_text:
            filters["folderId"] = int(folder_text)
        term = self._term_edit.text().strip()
        if term:
            filters["term"] = term
        standard = self._standard_edit.text().strip()
        if standard:
            filters["standard"] = standard
        status_val = self._status_combo.currentData()
        if status_val is not None:
            filters["status"] = status_val
        return filters

    def _fetch_chapters(self):
        if not self._client:
            return
        filters = self._build_filters()
        self._set_buttons_enabled(False)
        self._run_worker(
            lambda: get_chapters(self._client, self._current_page, self._page_size, **filters),
            self._on_chapters_loaded,
            self._on_error,
        )

    def _on_chapters_loaded(self, page_result: PageResult):
        self._total = page_result.total_elements
        self._populate_table(page_result.content)
        total_pages = max(1, (self._total + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"第 {self._current_page + 1}/{total_pages} 页")
        self._info_label.setText(f"共 {self._total} 条，每页 {self._page_size}")
        self._set_buttons_enabled(True)

    def _populate_table(self, chapters: list[Chapter]):
        self._table.setRowCount(len(chapters))
        for row, ch in enumerate(chapters):
            self._table.setItem(row, 0, QTableWidgetItem(str(ch.id or "")))
            self._table.setItem(row, 1, QTableWidgetItem(ch.term))
            self._table.setItem(row, 2, QTableWidgetItem(ch.standard))
            self._table.setItem(row, 3, QTableWidgetItem(str(ch.version)))
            self._table.setItem(row, 4, QTableWidgetItem(ch.test_content))
            status_text = STATUS_LABELS.get(ch.status, str(ch.status))
            self._table.setItem(row, 5, QTableWidgetItem(status_text))
            ops = QWidget()
            ops_layout = QHBoxLayout(ops)
            ops_layout.setContentsMargins(4, 0, 4, 0)
            edit_btn = QPushButton("编辑")
            edit_btn.setFixedHeight(24)
            edit_btn.clicked.connect(lambda _, c=ch: self._show_edit_dialog(c))
            ops_layout.addWidget(edit_btn)
            if ch.status == ChapterStatus.DRAFT and ch.quote_cnt == 0:
                del_btn = QPushButton("删除")
                del_btn.setFixedHeight(24)
                del_btn.setStyleSheet("color: #f44336;")
                del_btn.clicked.connect(lambda _, c=ch: self._confirm_delete(c))
                ops_layout.addWidget(del_btn)
            self._table.setCellWidget(row, 6, ops)

    def _on_query(self):
        self._current_page = 0
        self._fetch_chapters()

    def _on_clear_filters(self):
        self._folder_edit.clear()
        self._term_edit.clear()
        self._standard_edit.clear()
        self._status_combo.setCurrentIndex(0)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._fetch_chapters()

    def _next_page(self):
        total_pages = max(1, (self._total + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._fetch_chapters()

    def _confirm_delete(self, chapter: Chapter):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除条款 {chapter.term}？\n（只有草稿状态且未被引用的条款可删除）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker(
                lambda: delete_chapters(self._client, [chapter.id]),
                lambda _: self._fetch_chapters(),
                self._on_error,
            )

    def _on_error(self, msg: str):
        self._info_label.setText(f"Error: {msg}")
        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled: bool):
        self._query_btn.setEnabled(enabled)
        self._add_btn.setEnabled(enabled)
        self._prev_btn.setEnabled(enabled)
        self._next_btn.setEnabled(enabled)

    def _run_worker(self, func, on_result, on_error):
        self._worker = ChapterWorker(func)
        self._worker.result_ready.connect(on_result)
        self._worker.error_occurred.connect(on_error)
        self._worker.start()

    def _show_settings_dialog(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            self._settings.save_api_config(self._config)
            self._connected = False
            self._try_connect()

    def _show_create_dialog(self):
        dlg = ChapterDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            chapters = dlg.get_chapters()
            if len(chapters) == 1:
                self._run_worker(
                    lambda: create_chapter(self._client, chapters[0]),
                    lambda _: self._fetch_chapters(),
                    self._on_error,
                )
            else:
                self._batch_create(chapters)

    def _show_edit_dialog(self, chapter: Chapter):
        dlg = ChapterDialog(chapter=chapter, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_chapters()[0]
            updated.id = chapter.id
            self._run_worker(
                lambda: update_chapter(self._client, updated),
                lambda _: self._fetch_chapters(),
                self._on_error,
            )

    def _batch_create(self, chapters: list[Chapter]):
        results = {"success": 0, "errors": []}
        def do_batch():
            for ch in chapters:
                try:
                    create_chapter(self._client, ch)
                    results["success"] += 1
                except Exception as e:
                    results["errors"].append(f"{ch.term}: {e}")
            return results
        self._run_worker(do_batch, self._on_batch_done, self._on_error)

    def _on_batch_done(self, results):
        msg = f"成功: {results['success']} 条"
        if results["errors"]:
            msg += f"\n失败: {len(results['errors'])} 条\n" + "\n".join(results["errors"])
        QMessageBox.information(self, "批量创建结果", msg)
        self._fetch_chapters()


class SettingsDialog(QDialog):
    """API 设置对话框"""

    def __init__(self, config: ApiConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)

        self._url_edit = QLineEdit(config.base_url if config else "http://127.0.0.1:8080")
        layout.addRow("API URL:", self._url_edit)
        self._user_edit = QLineEdit(config.username if config else "")
        layout.addRow("用户名:", self._user_edit)
        self._pass_edit = QLineEdit(config.password if config else "")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("密码:", self._pass_edit)
        self._key_edit = QPlainTextEdit(config.rsa_private_key if config else "")
        self._key_edit.setMaximumHeight(100)
        layout.addRow("RSA 私钥:", self._key_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_config(self) -> ApiConfig:
        return ApiConfig(
            base_url=self._url_edit.text().strip(),
            username=self._user_edit.text().strip(),
            password=self._pass_edit.text(),
            rsa_private_key=self._key_edit.toPlainText().strip(),
        )



class ChapterDialog(QDialog):
    """新增/编辑条款对话框"""

    def __init__(self, chapter: Chapter | None = None, parent=None):
        super().__init__(parent)
        self._editing = chapter is not None
        self.setWindowTitle("编辑条款" if self._editing else "新增条款")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)

        if not self._editing:
            self._batch_cb = QCheckBox("批量模式（条款号和测试内容用逗号分隔）")
            layout.addRow(self._batch_cb)

        self._folder_edit = QLineEdit(str(chapter.folder_id) if chapter and chapter.folder_id else "")
        layout.addRow("文件夹 ID *:", self._folder_edit)
        self._term_edit = QLineEdit(chapter.term if chapter else "")
        layout.addRow("条款编号 *:", self._term_edit)
        self._content_edit = QLineEdit(chapter.test_content if chapter else "")
        layout.addRow("测试内容 *:", self._content_edit)
        self._product_edit = QLineEdit(chapter.product_type if chapter else "")
        layout.addRow("产品类别 *:", self._product_edit)
        self._sr_edit = QLineEdit(str(chapter.plan_sr) if chapter else "1")
        layout.addRow("PlanSR *:", self._sr_edit)
        self._standard_edit = QLineEdit(chapter.standard if chapter else "")
        layout.addRow("标准 *:", self._standard_edit)
        self._version_edit = QLineEdit(str(chapter.version) if chapter else "1")
        layout.addRow("条款版本 *:", self._version_edit)
        self._std_ver_edit = QLineEdit(chapter.standard_version if chapter else "")
        layout.addRow("标准版本:", self._std_ver_edit)
        self._specific_edit = QLineEdit(chapter.specific_product if chapter else "")
        layout.addRow("特定产品:", self._specific_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_chapters(self) -> list[Chapter]:
        base = Chapter(
            folder_id=int(self._folder_edit.text().strip() or "0") or None,
            product_type=self._product_edit.text().strip(),
            plan_sr=self._sr_edit.text().strip(),
            standard=self._standard_edit.text().strip(),
            version=int(self._version_edit.text().strip() or "0"),
            standard_version=self._std_ver_edit.text().strip(),
            specific_product=self._specific_edit.text().strip(),
        )
        if self._editing or not self._batch_cb.isChecked():
            base.term = self._term_edit.text().strip()
            base.test_content = self._content_edit.text().strip()
            return [base]
        terms = [t.strip() for t in self._term_edit.text().split(",") if t.strip()]
        contents = [c.strip() for c in self._content_edit.text().split(",") if c.strip()]
        if len(terms) != len(contents):
            contents = contents + [""] * (len(terms) - len(contents))
        chapters = []
        for term, content in zip(terms, contents):
            ch = replace(base, term=term, test_content=content)
            chapters.append(ch)
        return chapters
