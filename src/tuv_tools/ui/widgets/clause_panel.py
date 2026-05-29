"""条款面板 — 浮层叠加式，从右侧滑入覆盖列表"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from tuv_tools.core.splitter.ui_helpers import extract_clause_test_content
from tuv_tools.ui.theme import ThemeManager
from tuv_tools.ui.widgets import scrollbar_style


class ClauseOverlay(QWidget):
    """浮层叠加面板：半透明遮罩 + 右侧滑入面板"""

    PANEL_WIDTH = 600
    ANIM_DURATION = 250
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = None
        self._expanded = False
        self.setVisible(False)

        # 半透明遮罩
        self._backdrop = QWidget(self)
        self._backdrop.installEventFilter(self)

        # 条款面板本体
        self._panel = QWidget(self)
        self._panel.setObjectName("clausePanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # 标题栏
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 8, 10)
        self._title_label = QLabel("条款列表")
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.clicked.connect(self.collapse)
        header.addWidget(self._close_btn)
        panel_layout.addLayout(header)

        # 条款列表
        self._list = QListWidget()
        panel_layout.addWidget(self._list)

        self._empty_label = QLabel("无条款数据")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        panel_layout.addWidget(self._empty_label)

        self._panel_x = 0
        self._apply_theme()
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _apply_theme(self) -> None:
        c = ThemeManager.instance().colors
        self._backdrop.setStyleSheet(f"background-color: {c.bg_overlay};")
        self._panel.setStyleSheet(
            f"""
            #clausePanel {{
                background-color: {c.bg_primary};
                border-left: 1px solid {c.border_secondary};
            }}
            """
        )
        self._title_label.setStyleSheet(
            f"color: {c.text_primary}; font-size: 14px; font-weight: bold;"
        )
        self._close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {c.text_secondary};
                border: none;
                border-radius: 13px;
            }}
            QPushButton:hover {{
                background-color: {c.bg_hover};
                color: {c.text_primary};
            }}
            """
        )
        self._list.setStyleSheet(
            f"""
            QListWidget {{
                background-color: {c.bg_primary}; color: {c.text_primary};
                border: none; border-top: 1px solid {c.border_subtle}; font-size: 13px;
            }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {c.border_subtle}; }}
            QListWidget::item:hover {{ background-color: {c.bg_hover}; }}
            """
            + scrollbar_style()
        )
        self._empty_label.setStyleSheet(f"color: {c.text_muted}; padding: 20px;")

    def set_x(self, x: int) -> None:
        self._panel_x = x
        self._panel.move(x, 0)

    def _get_x(self) -> int:
        return self._panel_x

    _x_prop = Property(int, _get_x, set_x)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._backdrop.setGeometry(0, 0, self.width(), self.height())
        self._panel.setGeometry(self._panel_x, 0, self.PANEL_WIDTH, self.height())

    def _animate_x(self, target: int) -> None:
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"_x_prop")
        self._anim.setDuration(self.ANIM_DURATION)
        self._anim.setStartValue(self._panel_x)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if self._panel_x >= self.width():
            self.setVisible(False)

    def expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self.setGeometry(0, 0, self.parent().width(), self.parent().height())
        start_x = self.width()
        self._panel.move(start_x, 0)
        self._panel_x = start_x
        self.setVisible(True)
        self.raise_()
        self._animate_x(self.width() - self.PANEL_WIDTH)

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self._animate_x(self.width())
        self.closed.emit()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._backdrop and event.type() == event.Type.MouseButtonPress:
            self.collapse()
            return True
        return super().eventFilter(obj, event)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    @staticmethod
    def _clean_title(raw: str) -> str:
        import re
        text = raw

        # 1. 移除模板括号块（含内容）
        text = re.sub(r"\(Testing equipment[^)]*\)", "", text)
        text = re.sub(r"\(please specify[^)]*\)", "", text)

        # 2. 移除复选框模板行：☐ Test date : ...  ☐ Ambient temperature : ...  等
        text = re.sub(r"☐\s*(Test date|Ambient temperature|Equipment ID|Sample ID|Equipment No)\s*:?[^☐|\n]*", "", text)
        text = re.sub(r"☐+", "", text)

        # 3. 去掉条款号/Annex/TABLE 前缀（已经在 clause_id 中）
        text = re.sub(r"^[\d.,&\s]+\|?\s*", "", text)
        text = re.sub(r"^Annex\s+[A-Z]{1,2}\s*[,&]?\s*[\d.]*\s*[-—–]\s*", "", text)
        text = re.sub(r"^TABLE:\s*", "", text)

        # 4. 按 | 拆分，取首个有效段（跳过纯数字/标点/空白段）
        for part in text.split("|"):
            part = part.strip()
            if part and re.search(r"[A-Za-z]{3,}", part):
                text = part
                break
        else:
            text = ""

        # 5. 清理残留空白和标点
        text = re.sub(r"\s+", " ", text).strip(" .:;|-\t")

        if not text or re.match(r"^[\d.,&\s]+$", text):
            return "(无测试内容)"
        return text

    def set_sections(self, sections: list) -> None:
        self._list.clear()
        if not sections:
            self._empty_label.setVisible(True)
            self._list.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._list.setVisible(True)
        for s in sections:
            title = extract_clause_test_content(s.title) or "(无测试内容)"
            text = f"{s.clause_id}: {title[:120]}"
            item = QListWidgetItem(text)
            item.setToolTip(title)
            self._list.addItem(item)

    def show_loading(self) -> None:
        self._list.clear()
        self._empty_label.setText("加载中...")
        self._empty_label.setVisible(True)
        self._list.setVisible(False)

    def show_error(self, msg: str) -> None:
        self._list.clear()
        self._empty_label.setText(f"加载失败: {msg}")
        self._empty_label.setVisible(True)
        self._list.setVisible(False)
