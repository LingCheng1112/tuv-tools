"""主窗口框架：侧边导航 + 内容区。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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
from tuv_tools.core.chapter.session import ChapterSessionManager

from .views.chapter_batch_view import ChapterBatchView
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

    def __init__(
        self,
        settings: AppSettings | None = None,
        session_manager: ChapterSessionManager | None = None,
    ):
        super().__init__()
        self._settings = settings or AppSettings()
        self._chapter_session = session_manager or ChapterSessionManager(self._settings, self)
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

        self._settings_btn = QPushButton("设置")
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

        self._connection_status = QLabel(self._connection_badge_text())
        self._connection_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._connection_status.setStyleSheet(self._connection_badge_style())
        nav_layout.addWidget(self._connection_status)

        layout.addWidget(nav_container)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._register_views()
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._chapter_session.status_changed.connect(self._refresh_connection_status)
        self._nav.setCurrentRow(0)

    def _refresh_connection_status(self, _status: str) -> None:
        self._connection_status.setText(self._connection_badge_text())
        self._connection_status.setStyleSheet(self._connection_badge_style())

    def _connection_badge_text(self) -> str:
        return f"● {self._chapter_session.status_text()}"

    def _connection_badge_style(self) -> str:
        palette = {
            "connected": ("#1f3a2b", "#4caf50"),
            "loading": ("#1e3248", "#4a9eff"),
            "login_required": ("#3b2424", "#ff6b6b"),
            "disconnected": ("#3b2424", "#ff6b6b"),
            "error": ("#3b2424", "#ff6b6b"),
        }
        bg_color, fg_color = palette.get(self._chapter_session.status.value, ("#25282c", "#c8d0db"))
        return f"""
            QLabel {{
                background-color: {bg_color};
                color: {fg_color};
                border-top: 1px solid #3a3d41;
                font-size: 13px;
                font-weight: 600;
                padding: 10px 16px;
            }}
        """

    def _register_views(self):
        """注册所有功能视图。"""
        self._add_view("文档拆分", SplitterView())
        self._add_view("条款管理", ChapterView(self._chapter_session))
        self._add_view("批量上传", ChapterBatchView(session_manager=self._chapter_session))

    def _add_view(self, label: str, widget: QWidget):
        item = QListWidgetItem(label)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._nav.addItem(item)
        self._stack.addWidget(widget)

    def _open_settings(self):
        dialog = SettingsDialog(
            self,
            settings=self._settings,
            session_manager=self._chapter_session,
        )
        dialog.exec()
