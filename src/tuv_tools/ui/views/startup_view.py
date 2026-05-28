"""独立启动页，承载加载态与登录态。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPauseAnimation,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter, QPixmap, QResizeEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFormLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.core.chapter.models import ApiConfig


class StartupView(QWidget):
    """首屏启动视图。"""

    login_submitted = Signal(str, str, str)
    skip_requested = Signal()
    settings_requested = Signal()

    def __init__(self, logo_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("TUV Tools")
        self.setMinimumSize(720, 520)
        self.resize(900, 620)
        self.setStyleSheet(
            """
            QWidget {
                background-color: #1f2329;
                color: #f4f5f7;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #181c22;
                border: 1px solid #495466;
                border-radius: 8px;
                padding: 10px 12px;
                min-height: 18px;
            }
            QPushButton {
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: bold;
            }
            QPushButton#PrimaryButton {
                background-color: #4a9eff;
                color: white;
            }
            QPushButton#SecondaryButton {
                background-color: transparent;
                color: #c8d0db;
                border: 1px solid #4e5663;
            }
            """
        )

        self._loading_logo_size = 210
        self._login_logo_size = 150
        self._panel_gap = 24
        self._panel_slide_distance = 18
        self._top_margin = 40
        self._logo_source = self._build_logo_pixmap(logo_path) if logo_path is not None and logo_path.exists() else None
        self._transition_group: QParallelAnimationGroup | None = None
        self._login_state_active = False
        self._transition_progress_value = 0.0
        self._login_slide_progress_value = 0.0

        self._brand_wrap = QWidget(self)
        self._brand_layout = QVBoxLayout(self._brand_wrap)
        self._brand_layout.setContentsMargins(0, 0, 0, 0)
        self._brand_layout.setSpacing(12)

        self._logo_label = QLabel()
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel("TUV Tools")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size: 32px; font-weight: bold;")

        self._subtitle = QLabel("正在加载")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setStyleSheet("color: #b8c0cc; font-size: 15px;")

        self._brand_layout.addWidget(self._logo_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._brand_layout.addWidget(self._title)
        self._brand_layout.addWidget(self._subtitle)

        self._loading_wrap = self._build_loading_panel()
        self._login_wrap = self._build_login_panel()
        self._login_wrap.hide()

        self._loading_opacity = QGraphicsOpacityEffect(self._loading_wrap)
        self._loading_wrap.setGraphicsEffect(self._loading_opacity)
        self._loading_opacity.setOpacity(1.0)

        self._subtitle_opacity = QGraphicsOpacityEffect(self._subtitle)
        self._subtitle.setGraphicsEffect(self._subtitle_opacity)
        self._subtitle_opacity.setOpacity(1.0)

        self._login_opacity = QGraphicsOpacityEffect(self._login_wrap)
        self._login_wrap.setGraphicsEffect(self._login_opacity)
        self._login_opacity.setOpacity(0.0)

        self._apply_logo_size(self._loading_logo_size)
        self._update_transition_progress(0.0, force=True)
        self._update_login_slide_progress(0.0, force=True)

    def _build_logo_pixmap(self, logo_path: Path) -> QPixmap | None:
        if logo_path.suffix.lower() == ".svg":
            renderer = QSvgRenderer(str(logo_path))
            if not renderer.isValid():
                return None
            default_size = renderer.defaultSize()
            width = max(default_size.width(), 1)
            height = max(default_size.height(), 1)
            canvas = QPixmap(width, height)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            renderer.render(painter)
            painter.end()
            return canvas

        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            return None
        return pixmap

    def _apply_logo_size(self, size: int) -> None:
        self._logo_label.setFixedSize(size, size)
        if self._logo_source is None or self._logo_source.isNull():
            return
        scaled = self._logo_source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._logo_label.setPixmap(scaled)

    def _build_loading_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.setSpacing(10)

        self._spinner = QLabel("◌")
        self._spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner.setStyleSheet("font-size: 34px; color: #4a9eff;")
        layout.addWidget(self._spinner)

        return panel

    def _build_login_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setFixedWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(16)

        self._login_heading = QLabel("登录")
        self._login_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_heading.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(self._login_heading)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #ff8f8f;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self._url_edit = QLineEdit()
        self._user_edit = QLineEdit()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("URL", self._url_edit)
        form.addRow("用户名", self._user_edit)
        form.addRow("密码", self._password_edit)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self._settings_btn = QPushButton("设置")
        self._settings_btn.setObjectName("SecondaryButton")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        actions.addWidget(self._settings_btn)
        actions.addStretch()

        self._skip_btn = QPushButton("跳过登录")
        self._skip_btn.setObjectName("SecondaryButton")
        self._skip_btn.clicked.connect(self.skip_requested.emit)
        actions.addWidget(self._skip_btn)

        self._login_btn = QPushButton("登录")
        self._login_btn.setObjectName("PrimaryButton")
        self._login_btn.clicked.connect(self._emit_login_submitted)
        actions.addWidget(self._login_btn)
        layout.addLayout(actions)
        return panel

    def _emit_login_submitted(self) -> None:
        self.login_submitted.emit(
            self._url_edit.text().strip(),
            self._user_edit.text().strip(),
            self._password_edit.text(),
        )

    def _stop_transition(self) -> None:
        if self._transition_group is not None:
            self._transition_group.stop()
            self._transition_group = None

    @staticmethod
    def _lerp(start: float, end: float, progress: float) -> float:
        return start + (end - start) * progress

    def _update_transition_progress(self, value: float, *, force: bool = False) -> None:
        value = max(0.0, min(1.0, float(value)))
        if not force and abs(value - self._transition_progress_value) < 0.0001:
            return
        self._transition_progress_value = value
        logo_size = round(self._lerp(self._loading_logo_size, self._login_logo_size, value))
        self._apply_logo_size(logo_size)
        self._reposition_scene()

    def _get_transition_progress(self) -> float:
        return self._transition_progress_value

    def _set_transition_progress(self, value: float) -> None:
        self._update_transition_progress(value)

    transition_progress = Property(float, _get_transition_progress, _set_transition_progress)

    def _update_login_slide_progress(self, value: float, *, force: bool = False) -> None:
        value = max(0.0, min(1.0, float(value)))
        if not force and abs(value - self._login_slide_progress_value) < 0.0001:
            return
        self._login_slide_progress_value = value
        self._reposition_scene()

    def _get_login_slide_progress(self) -> float:
        return self._login_slide_progress_value

    def _set_login_slide_progress(self, value: float) -> None:
        self._update_login_slide_progress(value)

    login_slide_progress = Property(float, _get_login_slide_progress, _set_login_slide_progress)

    def _reposition_scene(self) -> None:
        self._brand_wrap.adjustSize()
        self._loading_wrap.adjustSize()
        self._login_wrap.adjustSize()

        brand_size = self._brand_wrap.sizeHint()
        loading_size = self._loading_wrap.sizeHint()
        login_size = self._login_wrap.sizeHint()

        loading_brand_top = max(
            (self.height() - (brand_size.height() + self._panel_gap + loading_size.height())) // 2,
            self._top_margin,
        )
        login_brand_top = max(
            (self.height() - (brand_size.height() + self._panel_gap + login_size.height())) // 2,
            self._top_margin,
        )
        brand_top = round(self._lerp(loading_brand_top, login_brand_top, self._transition_progress_value))
        brand_left = max((self.width() - brand_size.width()) // 2, 0)
        self._brand_wrap.setGeometry(brand_left, brand_top, brand_size.width(), brand_size.height())

        panel_top = brand_top + brand_size.height() + self._panel_gap

        loading_left = max((self.width() - loading_size.width()) // 2, 0)
        self._loading_wrap.setGeometry(loading_left, panel_top, loading_size.width(), loading_size.height())

        login_left = max((self.width() - login_size.width()) // 2, 0)
        login_end_top = panel_top
        login_start_top = login_end_top + self._panel_slide_distance
        login_top = round(self._lerp(login_start_top, login_end_top, self._login_slide_progress_value))
        self._login_wrap.setGeometry(login_left, login_top, login_size.width(), login_size.height())

    def _finalize_login_state(self) -> None:
        self._transition_group = None
        self._login_state_active = True
        self._update_transition_progress(1.0, force=True)
        self._update_login_slide_progress(1.0, force=True)
        self._loading_wrap.hide()
        self._loading_opacity.setOpacity(0.0)
        self._subtitle_opacity.setOpacity(0.0)
        self._login_opacity.setOpacity(1.0)
        self._url_edit.setFocus()

    def show_loading(self) -> None:
        self._stop_transition()
        self._login_state_active = False
        self._subtitle.setText("正在加载")
        self._loading_wrap.show()
        self._login_wrap.hide()
        self._loading_opacity.setOpacity(1.0)
        self._subtitle_opacity.setOpacity(1.0)
        self._login_opacity.setOpacity(0.0)
        self._update_transition_progress(0.0, force=True)
        self._update_login_slide_progress(0.0, force=True)

    def transition_to_login(self, config: ApiConfig | None, error_message: str = "") -> None:
        self._stop_transition()
        if config is not None:
            self._url_edit.setText(config.base_url)
            self._user_edit.setText(config.username)
            self._password_edit.setText(config.password)
        if error_message:
            self._error_label.setText(error_message)
            self._error_label.show()
        else:
            self._error_label.hide()
            self._error_label.clear()

        self._login_wrap.adjustSize()

        if self._login_state_active:
            self._login_wrap.show()
            self._loading_wrap.hide()
            self._loading_opacity.setOpacity(0.0)
            self._subtitle_opacity.setOpacity(0.0)
            self._login_opacity.setOpacity(1.0)
            self._update_transition_progress(1.0, force=True)
            self._update_login_slide_progress(1.0, force=True)
            self._url_edit.setFocus()
            return

        self._loading_wrap.show()
        self._login_wrap.show()
        self._loading_opacity.setOpacity(1.0)
        self._subtitle_opacity.setOpacity(1.0)
        self._login_opacity.setOpacity(0.0)
        self._update_transition_progress(0.0, force=True)
        self._update_login_slide_progress(0.0, force=True)

        group = QParallelAnimationGroup(self)

        brand_animation = QPropertyAnimation(self, b"transition_progress", self)
        brand_animation.setDuration(260)
        brand_animation.setStartValue(0.0)
        brand_animation.setEndValue(1.0)
        brand_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(brand_animation)

        subtitle_fade = QPropertyAnimation(self._subtitle_opacity, b"opacity", self)
        subtitle_fade.setDuration(150)
        subtitle_fade.setStartValue(1.0)
        subtitle_fade.setEndValue(0.0)
        subtitle_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(subtitle_fade)

        loading_fade = QPropertyAnimation(self._loading_opacity, b"opacity", self)
        loading_fade.setDuration(150)
        loading_fade.setStartValue(1.0)
        loading_fade.setEndValue(0.0)
        loading_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(loading_fade)

        login_slide = QPropertyAnimation(self, b"login_slide_progress", self)
        login_slide.setDuration(160)
        login_slide.setStartValue(0.0)
        login_slide.setEndValue(1.0)
        login_slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        login_slide_group = QSequentialAnimationGroup(self)
        login_slide_group.addAnimation(QPauseAnimation(100))
        login_slide_group.addAnimation(login_slide)
        group.addAnimation(login_slide_group)

        login_fade = QPropertyAnimation(self._login_opacity, b"opacity", self)
        login_fade.setDuration(160)
        login_fade.setStartValue(0.0)
        login_fade.setEndValue(1.0)
        login_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        login_fade_group = QSequentialAnimationGroup(self)
        login_fade_group.addAnimation(QPauseAnimation(100))
        login_fade_group.addAnimation(login_fade)
        group.addAnimation(login_fade_group)

        group.finished.connect(self._finalize_login_state)
        self._transition_group = group
        group.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_scene()
