"""主窗口框架：侧边导航 + 内容区"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.session import ChapterConnectionStatus, ChapterSessionManager

from .views.chapter_batch_view import ChapterBatchView
from .views.chapter_login_dialog import ChapterLoginDialog
from .views.chapter_view import ChapterView
from .views.settings_dialog import SettingsDialog
from .views.splitter_view import SplitterView


class NoFocusDelegate(QStyledItemDelegate):
    """去除列表项选中时的焦点矩形框。"""

    def paint(self, painter, option, index):
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._chapter_session = ChapterSessionManager(self._settings, self)
        self.setWindowTitle("TUV Tools")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_container = QWidget()
        nav_container.setFixedWidth(180)
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setItemDelegate(NoFocusDelegate(self._nav))
        self._nav.setStyleSheet(
            """
            QListWidget {
                background-color: #2b2d30;
                color: #dcdcdc;
                border: none;
                font-size: 14px;
                padding-top: 8px;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-left: 3px solid transparent;
            }
            QListWidget::item:selected {
                background-color: #3c3f41;
                border-left: 3px solid #4a9eff;
                color: #ffffff;
            }
            QListWidget::item:hover:!selected {
                background-color: #333537;
            }
            """
        )
        nav_layout.addWidget(self._nav)

        self._connection_btn = QPushButton("● 未连接")
        self._connection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._connection_btn.clicked.connect(self._open_login_dialog)
        self._connection_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2b2d30;
                color: #dcdcdc;
                border: none;
                border-top: 1px solid #3a3d40;
                font-size: 13px;
                padding: 10px 16px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #333537;
            }
            """
        )
        nav_layout.addWidget(self._connection_btn)

        self._settings_btn = QPushButton("⚿ 设置")
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.clicked.connect(self._open_settings)
        self._settings_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2b2d30;
                color: #dcdcdc;
                border: none;
                border-top: 1px solid #444;
                font-size: 14px;
                padding: 12px 16px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #333537;
            }
            """
        )
        nav_layout.addWidget(self._settings_btn)

        layout.addWidget(nav_container)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._register_views()
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)
        self._chapter_session.status_changed.connect(self._on_connection_status_changed)
        self._chapter_session.login_dialog_requested.connect(self._show_startup_login_dialog)
        self._chapter_session.initialize_on_startup()

    def _register_views(self):
        """注册所有功能视图。"""
        self._add_view("文档拆分", SplitterView())
        self._add_view("条款管理", ChapterView(self._chapter_session))
        self._add_view("条款批量上传", ChapterBatchView(session_manager=self._chapter_session))

    def _add_view(self, label: str, widget: QWidget):
        item = QListWidgetItem(label)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._nav.addItem(item)
        self._stack.addWidget(widget)

    def _open_settings(self):
        dlg = SettingsDialog(self, settings=self._settings)
        dlg.exec()
        self._chapter_session.apply_saved_credentials()

    def _open_login_dialog(self):
        dialog = ChapterLoginDialog(self, settings=self._settings)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._chapter_session.apply_saved_credentials()

    def _show_startup_login_dialog(self):
        if self._chapter_session.status == ChapterConnectionStatus.UNCONFIGURED:
            self._open_login_dialog()

    def _on_connection_status_changed(self, _status: str) -> None:
        text = self._chapter_session.status_text()
        self._connection_btn.setText(text)
        if self._chapter_session.status == ChapterConnectionStatus.CONNECTED:
            color = "#4caf50"
        elif self._chapter_session.status == ChapterConnectionStatus.CONNECTING:
            color = "#9fbce6"
        else:
            color = "#d9534f"
        self._connection_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #2b2d30;
                color: {color};
                border: none;
                border-top: 1px solid #3a3d40;
                font-size: 13px;
                padding: 10px 16px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: #333537;
            }}
            """
        )
