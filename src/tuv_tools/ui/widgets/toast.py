"""Toast 通知组件 — 右下角短暂提示，自动消失"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Property
from PySide6.QtWidgets import QLabel, QWidget


class Toast(QWidget):
    """右下角 toast 通知，作为父控件的子控件显示，定时后淡出销毁"""

    def __init__(self, parent: QWidget, message: str, duration_ms: int = 2000):
        super().__init__(parent)

        label = QLabel(message, self)
        label.setStyleSheet("""
            QLabel {
                background-color: #3c3f41;
                color: #dcdcdc;
                padding: 10px 20px;
                border: 1px solid #555;
                border-radius: 6px;
                font-size: 13px;
            }
        """)
        label.adjustSize()
        self.resize(label.size())

        if parent:
            self.move(parent.width() - self.width() - 20,
                       parent.height() - self.height() - 40)

        self._opacity = 1.0
        self.raise_()
        self.show()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(duration_ms)

    def _fade_out(self) -> None:
        self._anim = QPropertyAnimation(self, b"_opacity")
        self._anim.setDuration(300)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.setWindowOpacity(value)

    _opacity_prop = Property(float, _get_opacity, _set_opacity)
