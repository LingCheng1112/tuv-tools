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

from tuv_tools import APP_NAME
from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.session import ChapterSessionManager
from .theme import ThemeManager, ACCENT_PRIMARY, ACCENT_SUCCESS, ACCENT_ERROR
from .widgets import scrollbar_style

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
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        central = QWidget()
        central.setObjectName("mainWindowCentral")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_container = QWidget()
        nav_container.setObjectName("mainWindowNav")
        nav_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav_container.setFixedWidth(180)
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setItemDelegate(NoFocusDelegate(self._nav))
        nav_layout.addWidget(self._nav)

        self._settings_btn = QPushButton("设置")
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.clicked.connect(self._open_settings)
        nav_layout.addWidget(self._settings_btn)

        self._connection_status = QLabel(self._connection_badge_text())
        self._connection_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        nav_layout.addWidget(self._connection_status)

        layout.addWidget(nav_container)

        self._stack = QStackedWidget()
        self._stack.setObjectName("mainWindowStack")
        self._stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout.addWidget(self._stack)

        self._register_views()
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._chapter_session.status_changed.connect(self._refresh_connection_status)

        self._apply_theme()
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._nav.setCurrentRow(0)

    def _refresh_connection_status(self, _status: str) -> None:
        self._connection_status.setText(self._connection_badge_text())
        self._connection_status.setStyleSheet(self._connection_badge_style())

    def _connection_badge_text(self) -> str:
        return f"● {self._chapter_session.status_text()}"

    def _connection_badge_style(self) -> str:
        c = ThemeManager.instance().colors
        palette = {
            "connected": (c.bg_badge_success, ACCENT_SUCCESS),
            "loading": (c.bg_badge_loading, ACCENT_PRIMARY),
            "login_required": (c.bg_badge_error, ACCENT_ERROR),
            "disconnected": (c.bg_badge_error, ACCENT_ERROR),
            "error": (c.bg_badge_error, ACCENT_ERROR),
        }
        bg_color, fg_color = palette.get(
            self._chapter_session.status.value, (c.bg_primary, c.text_secondary)
        )
        return f"""
            QLabel {{
                background-color: {bg_color};
                color: {fg_color};
                border-top: 1px solid {c.border_subtle};
                font-size: 13px;
                font-weight: 600;
                padding: 10px 16px;
            }}
        """

    def _apply_theme(self) -> None:
        c = ThemeManager.instance().colors
        self.centralWidget().setStyleSheet(
            f"""
            #mainWindowCentral {{
                background-color: {c.bg_primary};
            }}
            #mainWindowNav {{
                background-color: {c.bg_secondary};
                border-right: 1px solid {c.border_primary};
            }}
            #mainWindowStack {{
                background-color: {c.bg_primary};
            }}
            QListWidget {{
                background-color: transparent;
                color: {c.text_primary};
                border: none;
                font-size: 14px;
                padding-top: 8px;
            }}
            QListWidget::item {{
                padding: 12px 16px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:selected {{
                background-color: {c.bg_selected};
                border-left: 3px solid {ACCENT_PRIMARY};
                color: {c.text_inverse};
                font-weight: 600;
            }}
            QListWidget::item:hover:!selected {{
                background-color: {c.bg_hover};
            }}
            """
        )
        self._nav.setStyleSheet(
            f"""
            QListWidget {{
                background-color: transparent;
                color: {c.text_primary};
                border: none;
                font-size: 14px;
                padding-top: 8px;
            }}
            QListWidget::item {{
                padding: 12px 16px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:selected {{
                background-color: {c.bg_selected};
                border-left: 3px solid {ACCENT_PRIMARY};
                color: {c.text_inverse};
                font-weight: 600;
            }}
            QListWidget::item:hover:!selected {{
                background-color: {c.bg_hover};
            }}
            """
            + scrollbar_style()
        )
        self._settings_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {c.bg_secondary};
                color: {c.text_secondary};
                border: none;
                border-top: 1px solid {c.border_subtle};
                font-size: 14px;
                padding: 12px 16px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {c.bg_hover};
                color: {c.text_primary};
            }}
            """
        )
        self._connection_status.setStyleSheet(self._connection_badge_style())

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
