"""条款管理视图"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QThread, QTimer, Signal, Qt
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
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.session import ChapterConnectionStatus, ChapterSessionManager
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from tuv_tools.ui.widgets.chapter_folder_selector import ChapterFolderSelector
from tuv_tools.core.chapter.api import (
    create_chapter,
    delete_chapters,
    get_chapters,
    get_folders,
    update_chapter,
)
from tuv_tools.core.chapter.models import (
    Chapter,
    ChapterStatus,
    FolderNode,
    PageResult,
    STATUS_LABELS,
)


CHAPTER_ROOT_FOLDER_ID = 2


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

    def __init__(self, session_manager: ChapterSessionManager | None = None):
        super().__init__()
        self._settings = AppSettings()
        self._session_manager = session_manager
        self._workers: list[ChapterWorker] = []
        self._current_page = 0
        self._page_size = 20
        self._total = 0
        self._selected_folder_id: int | None = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._do_folder_search)
        self._setup_ui()
        if self._session_manager is not None:
            self._session_manager.status_changed.connect(self._on_session_status_changed)
            self._apply_connection_state()

    @property
    def _client(self):
        return self._session_manager.client if self._session_manager is not None else None

    def _on_session_status_changed(self, _status: str) -> None:
        self._apply_connection_state()

    def _apply_connection_state(self) -> None:
        connected = self._session_manager is not None and self._session_manager.is_connected()
        self._content_root.setEnabled(connected)
        self._offline_hint.setVisible(not connected)
        if connected:
            self._load_folder_tree()
            self._fetch_chapters()


    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self._offline_hint = QLabel("当前未连接后端，请先在设置中登录后再使用条款管理。")
        self._offline_hint.setStyleSheet("color: #d9534f; font-size: 13px; padding: 4px 0;")
        self._offline_hint.setVisible(False)
        layout.addWidget(self._offline_hint)

        # 主体：左侧目录树 + 右侧内容
        self._content_root = QWidget(self)
        content_layout = QVBoxLayout(self._content_root)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧目录树
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(4)
        self._folder_search = QLineEdit()
        self._folder_search.setPlaceholderText("搜索目录...")
        self._folder_search.textChanged.connect(self._on_folder_search)
        tree_layout.addWidget(self._folder_search)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("条款目录")
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._tree.itemExpanded.connect(self._on_tree_item_expanded)
        tree_layout.addWidget(self._tree)
        splitter.addWidget(tree_container)

        # 右侧内容区
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 查询工具栏
        toolbar = QHBoxLayout()
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
        right_layout.addLayout(toolbar)

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
        right_layout.addWidget(self._table)

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
        right_layout.addLayout(page_row)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([200, 800])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        content_layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._content_root, stretch=1)


    def _load_folder_tree(self):
        """加载目录树根节点"""
        self._run_worker(
            lambda: get_folders(self._client, pid=CHAPTER_ROOT_FOLDER_ID),
            self._on_root_folders_loaded,
            self._on_error,
        )

    def _on_root_folders_loaded(self, folders: list[FolderNode]):
        self._tree.clear()
        for folder in folders:
            item = QTreeWidgetItem([folder.folder_name])
            item.setData(0, Qt.ItemDataRole.UserRole, folder.id)
            if folder.has_children:
                item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
            self._tree.addTopLevelItem(item)

    def _on_tree_item_expanded(self, item: QTreeWidgetItem):
        """懒加载子节点"""
        if item.childCount() > 0:
            return
        folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self._run_worker(
            lambda: get_folders(self._client, pid=folder_id),
            lambda folders: self._on_child_folders_loaded(item, folders),
            self._on_error,
        )

    def _on_child_folders_loaded(self, parent_item: QTreeWidgetItem, folders: list[FolderNode]):
        for folder in folders:
            child = QTreeWidgetItem([folder.folder_name])
            child.setData(0, Qt.ItemDataRole.UserRole, folder.id)
            if folder.has_children:
                child.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
            parent_item.addChild(child)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """点击目录节点，按 folderId 过滤条款"""
        self._selected_folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self._current_page = 0
        self._fetch_chapters()

    def _on_folder_search(self, text: str):
        """搜索目录（防抖 300ms）"""
        self._search_timer.start()

    def _do_folder_search(self):
        """执行目录搜索"""
        text = self._folder_search.text().strip()
        if not self._client or not text:
            if not text:
                self._load_folder_tree()
            return
        self._run_worker(
            lambda: get_folders(self._client, pid=CHAPTER_ROOT_FOLDER_ID, folder_name=text),
            self._on_root_folders_loaded,
            self._on_error,
        )


    def _build_filters(self) -> dict:
        filters = {}
        if self._selected_folder_id is not None:
            filters["folderId"] = self._selected_folder_id
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
        self._term_edit.clear()
        self._standard_edit.clear()
        self._status_combo.setCurrentIndex(0)
        self._selected_folder_id = None
        self._tree.clearSelection()
        self._current_page = 0
        self._fetch_chapters()


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
        if chapter.id is None:
            return
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
        worker = ChapterWorker(func)
        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker: ChapterWorker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _show_create_dialog(self):
        dlg = ChapterDialog(folder_id=self._selected_folder_id, parent=self)
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



class ChapterDialog(QDialog):
    """新增/编辑条款对话框"""

    def __init__(self, chapter: Chapter | None = None, folder_id: int | None = None, parent=None):
        super().__init__(parent)
        self._editing = chapter is not None
        self.setWindowTitle("编辑条款" if self._editing else "新增条款")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)

        if not self._editing:
            self._batch_cb = QCheckBox("批量模式（条款号和测试内容用逗号分隔）")
            self._batch_cb.setStyleSheet(CHECKBOX_STYLE)
            layout.addRow(self._batch_cb)

        default_folder_id = chapter.folder_id if chapter and chapter.folder_id else folder_id
        self._folder_selector = ChapterFolderSelector(self)
        self._folder_selector.set_selected_folder(default_folder_id, "")
        layout.addRow("归属文件夹 *:", self._folder_selector)
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
        def _safe_int(text: str, default: int = 0) -> int:
            try:
                return int(text.strip()) if text.strip() else default
            except ValueError:
                return default

        folder_val, _folder_name = self._folder_selector.selected_folder()
        base = Chapter(
            folder_id=folder_val or None,
            product_type=self._product_edit.text().strip(),
            plan_sr=self._sr_edit.text().strip(),
            standard=self._standard_edit.text().strip(),
            version=_safe_int(self._version_edit.text()),
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
