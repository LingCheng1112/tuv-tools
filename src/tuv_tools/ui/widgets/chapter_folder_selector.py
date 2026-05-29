"""条款目录树选择器。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.core.chapter.api import get_folders
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.session import ChapterSessionManager
from tuv_tools.ui.theme import ThemeManager


CHAPTER_ROOT_FOLDER_ID = 2


class FolderLoadWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, client: TuvClient | None, pid: int | None, folder_name: str = "", parent: QObject | None = None):
        super().__init__(parent)
        self._client = client
        self._pid = pid
        self._folder_name = folder_name

    def run(self) -> None:
        try:
            if self._client is None:
                raise RuntimeError("当前未连接后端。")
            self.loaded.emit(get_folders(self._client, pid=self._pid, folder_name=self._folder_name))
        except Exception as exc:
            self.failed.emit(str(exc))


class ChapterFolderDialog(QDialog):
    """条款目录树选择弹窗。"""

    def __init__(self, parent=None, session_manager: ChapterSessionManager | None = None):
        super().__init__(parent)
        self._session_manager = session_manager
        self.setWindowTitle("选择归属文件夹")
        self.resize(460, 560)
        self._selected_folder_id: int | None = None
        self._selected_folder_name = ""
        self._workers: list[FolderLoadWorker] = []

        layout = QVBoxLayout(self)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索目录")
        layout.addWidget(self._search_edit)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("条款目录")
        self._tree.itemExpanded.connect(self._load_children)
        self._tree.itemClicked.connect(self._select_item)
        layout.addWidget(self._tree, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._search_edit.returnPressed.connect(self._load_roots)
        self._load_roots()

    def selected_folder(self) -> tuple[int | None, str]:
        return self._selected_folder_id, self._selected_folder_name

    def _load_roots(self) -> None:
        self._tree.clear()
        self._run_loader(CHAPTER_ROOT_FOLDER_ID, self._search_edit.text().strip(), self._populate_roots)

    def _populate_roots(self, folders) -> None:
        for folder in folders:
            item = QTreeWidgetItem([folder.folder_name])
            item.setData(0, Qt.ItemDataRole.UserRole, folder.id)
            if folder.has_children:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._tree.addTopLevelItem(item)

    def _load_children(self, item: QTreeWidgetItem) -> None:
        if item.childCount() > 0:
            return
        folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self._run_loader(folder_id, "", lambda folders: self._populate_children(item, folders))

    def _populate_children(self, parent: QTreeWidgetItem, folders) -> None:
        for folder in folders:
            child = QTreeWidgetItem([folder.folder_name])
            child.setData(0, Qt.ItemDataRole.UserRole, folder.id)
            if folder.has_children:
                child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            parent.addChild(child)

    def _select_item(self, item: QTreeWidgetItem, _column: int) -> None:
        self._selected_folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self._selected_folder_name = item.text(0)

    def _run_loader(self, pid: int | None, folder_name: str, callback) -> None:
        client = self._session_manager.get_connected_client() if self._session_manager is not None else None
        worker = FolderLoadWorker(client, pid, folder_name, self)
        worker.loaded.connect(callback)
        worker.failed.connect(lambda message: QMessageBox.warning(self, "目录加载失败", message))
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker: FolderLoadWorker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass


class ChapterFolderSelector(QWidget):
    """可复用的目录选择器占位实现。"""

    folder_changed = Signal(object, str)

    def __init__(self, parent=None, session_manager: ChapterSessionManager | None = None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._selected_folder_id: int | None = None
        self._selected_folder_name = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._display = QLabel("")
        layout.addWidget(self._display, stretch=1)

        self._button = QPushButton("选择")
        self._button.clicked.connect(self._open_dialog)
        layout.addWidget(self._button)
        self.set_connection_enabled(self._session_manager is None or self._session_manager.is_connected())
        self._apply_theme()
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        if self._session_manager is not None:
            self._session_manager.status_changed.connect(self._on_session_status_changed)

    def _apply_theme(self) -> None:
        c = ThemeManager.instance().colors
        self._display.setStyleSheet(f"padding: 4px 6px; border: 1px solid {c.border_secondary};")

    def set_connection_enabled(self, enabled: bool) -> None:
        self._button.setEnabled(enabled)
        if not enabled and not self._selected_folder_name:
            self._display.setText("")

    def set_selected_folder(self, folder_id: int | None, folder_name: str = "") -> None:
        self._selected_folder_id = folder_id
        self._selected_folder_name = folder_name
        self._display.setText(folder_name or "")

    def selected_folder(self) -> tuple[int | None, str]:
        return self._selected_folder_id, self._selected_folder_name

    def _emit_folder_changed(self, folder_id: int | None, folder_name: str) -> None:
        self.set_selected_folder(folder_id, folder_name)
        self.folder_changed.emit(folder_id, folder_name)

    def _on_session_status_changed(self, _status: str) -> None:
        self.set_connection_enabled(self._session_manager is None or self._session_manager.is_connected())

    def _open_dialog(self) -> None:
        if self._session_manager is not None and not self._session_manager.is_connected():
            return
        dialog = ChapterFolderDialog(self, session_manager=self._session_manager)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder_id, folder_name = dialog.selected_folder()
        self._emit_folder_changed(folder_id, folder_name)
