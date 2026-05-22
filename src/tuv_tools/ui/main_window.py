"""主窗口框架：侧边导航 + 内容区"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .views.splitter_view import SplitterView
from .views.chapter_view import ChapterView
from .views.settings_dialog import SettingsDialog


class NoFocusDelegate(QStyledItemDelegate):
    """去除列表项选中时的焦点矩形框"""

    def paint(self, painter, option, index):
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TUV Tools")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 侧边栏容器
        nav_container = QWidget()
        nav_container.setFixedWidth(180)
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setItemDelegate(NoFocusDelegate(self._nav))
        self._nav.setStyleSheet("""
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
        """)
        nav_layout.addWidget(self._nav)

        # 设置按钮（固定在底部）
        self._settings_btn = QPushButton("⚙ 设置")
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.clicked.connect(self._open_settings)
        self._settings_btn.setStyleSheet("""
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
        """)
        nav_layout.addWidget(self._settings_btn)

        layout.addWidget(nav_container)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._register_views()
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _register_views(self):
        """注册所有功能视图（新增功能在此添加）"""
        self._add_view("文档拆分", SplitterView())
        self._add_view("条款管理", ChapterView())

    def _add_view(self, label: str, widget: QWidget):
        item = QListWidgetItem(label)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._nav.addItem(item)
        self._stack.addWidget(widget)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()
