"""主题管理 — 暗色/亮色/跟随系统三种模式。

所有 UI 颜色集中在此模块，通过 ThemeManager 单例访问。
切换主题时发射 theme_changed Signal，各 widget 重新生成 stylesheet。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Signal


class ThemeMode(StrEnum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


# ── 功能性颜色（跨主题不变，用户选择保持） ──────────────────────

ACCENT_PRIMARY = "#4a9eff"       # 首要操作蓝
ACCENT_DANGER = "#d9534f"        # 危险/删除
ACCENT_SUCCESS = "#4caf50"        # 成功/绿色指示
ACCENT_DESTRUCTIVE = "#f44336"    # 删除文字红
ACCENT_ERROR = "#ff6b6b"         # 连接错误红
ACCENT_ERROR_LIGHT = "#ff8f8f"   # 错误提示浅红

# ── 主题色板 ─────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ThemeColors:
    # ── 背景 ──
    bg_primary: str          # 主背景（导航栏、表格、面板）
    bg_secondary: str        # 页面级背景（启动页）
    bg_tertiary: str         # 表格交替行
    bg_input: str            # 输入框背景
    bg_hover: str            # hover 态
    bg_selected: str         # 选中态
    bg_overlay: str          # 模态遮罩层，格式 "rgba(r,g,b,a)"
    bg_badge_success: str    # 已连接 badge
    bg_badge_loading: str    # 连接中 badge
    bg_badge_error: str      # 断开/错误 badge

    # ── 文字 ──
    text_primary: str        # 主文字
    text_secondary: str      # 次要文字（标签、副标题）
    text_muted: str          # 辅助文字（表头、提示）
    text_heading: str        # 标题/面板标题
    text_inverse: str        # 深色背景上的反色文字（如选中项文字）
    text_link: str           # 链接/强调文字（跟随 accent_primary 或独立）

    # ── 边框 ──
    border_primary: str      # 主边框（输入框、容器）
    border_secondary: str    # 次边框（分隔线）
    border_subtle: str       # 微边框（badge 顶部分隔）

    # ── 其他 ──
    scrollbar_bg: str        # 滚动条轨道
    scrollbar_thumb: str     # 滚动条滑块
    spinner_track: str       # 加载圈轨道色
    disabled_bg: str         # 禁用态背景
    checkbox_border: str     # 复选框边框
    checkbox_bg: str         # 复选框选中背景


DARK = ThemeColors(
    # 背景
    bg_primary="#2b2d30",
    bg_secondary="#1f2329",
    bg_tertiary="#303336",
    bg_input="#181c22",
    bg_hover="#333537",
    bg_selected="#3c3f41",
    bg_overlay="rgba(0, 0, 0, 80)",
    bg_badge_success="#1f3a2b",
    bg_badge_loading="#1e3248",
    bg_badge_error="#3b2424",
    # 文字
    text_primary="#dcdcdc",
    text_secondary="#c8d0db",
    text_muted="#999999",
    text_heading="#f4f5f7",
    text_inverse="#ffffff",
    text_link=ACCENT_PRIMARY,
    # 边框
    border_primary="#495466",
    border_secondary="#555555",
    border_subtle="#3a3d41",
    # 其他
    scrollbar_bg="#2b2d30",
    scrollbar_thumb="#555555",
    spinner_track="#38414f",
    disabled_bg="#666666",
    checkbox_border="#7a818a",
    checkbox_bg="#6f7782",
)

LIGHT = ThemeColors(
    # 背景
    bg_primary="#ffffff",
    bg_secondary="#eef3f8",
    bg_tertiary="#f6f8fb",
    bg_input="#ffffff",
    bg_hover="#e9f0f8",
    bg_selected="#6f94c2",
    bg_overlay="rgba(0, 0, 0, 40)",
    bg_badge_success="#e9f7ee",
    bg_badge_loading="#e8f2ff",
    bg_badge_error="#fff0f0",
    # 文字
    text_primary="#18212d",
    text_secondary="#435164",
    text_muted="#6f7f91",
    text_heading="#0f1722",
    text_inverse="#ffffff",
    text_link="#2f74c3",
    # 边框
    border_primary="#d3dbe5",
    border_secondary="#dde5ee",
    border_subtle="#e9eef4",
    # 其他
    scrollbar_bg="#e9eef4",
    scrollbar_thumb="#c4ced9",
    spinner_track="#dde5ee",
    disabled_bg="#c6d0db",
    checkbox_border="#aab7c6",
    checkbox_bg="#4a9eff",
)


# ── 系统主题检测 ────────────────────────────────────────────

def _detect_system_theme() -> ThemeMode:
    """读取 Windows 注册表检测系统主题偏好。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return ThemeMode.LIGHT if value == 1 else ThemeMode.DARK
    except (OSError, ImportError):
        return ThemeMode.DARK


# ── ThemeManager 单例 ────────────────────────────────────────


class ThemeManager(QObject):
    """全局主题管理器。

    用法:
        tm = ThemeManager.instance()
        colors = tm.colors  # ThemeColors

        # 在 widget 中监听主题变化:
        tm.theme_changed.connect(self._on_theme_changed)
    """

    theme_changed = Signal()

    _instance: ThemeManager | None = None

    def __init__(self, db=None):
        super().__init__()
        self._db = db
        self._mode = ThemeMode.SYSTEM
        self._current_effective = ThemeMode.DARK

    @classmethod
    def instance(cls) -> ThemeManager:
        """获取全局单例。"""
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    @classmethod
    def init(cls, db) -> ThemeManager:
        """初始化单例。若已存在但未关联 DB，补设并加载配置。"""
        if cls._instance is not None:
            if cls._instance._db is None:
                cls._instance._db = db
                cls._instance._load()
            return cls._instance
        cls._instance = ThemeManager(db=db)
        cls._instance._load()
        return cls._instance

    # ── 属性 ──

    @property
    def mode(self) -> ThemeMode:
        """用户选择的主题模式。"""
        return self._mode

    @mode.setter
    def mode(self, value: ThemeMode) -> None:
        if value == self._mode:
            return
        old_effective = self._effective
        self._mode = value
        self._save()
        self._current_effective = self._resolve_effective()
        if self._current_effective != old_effective:
            self.theme_changed.emit()

    @property
    def colors(self) -> ThemeColors:
        """当前生效的色板。"""
        return LIGHT if self._effective == ThemeMode.LIGHT else DARK

    @property
    def is_dark(self) -> bool:
        return self._effective == ThemeMode.DARK

    @property
    def is_light(self) -> bool:
        return self._effective == ThemeMode.LIGHT

    @property
    def _effective(self) -> ThemeMode:
        if self._mode == ThemeMode.SYSTEM:
            return _detect_system_theme()
        return self._mode

    # ── 持久化 ──

    def _load(self) -> None:
        if self._db is None:
            return
        raw = self._db.get_config("theme.mode", ThemeMode.SYSTEM.value)
        try:
            self._mode = ThemeMode(raw)
        except ValueError:
            self._mode = ThemeMode.SYSTEM
        # 立即根据 mode 计算当前生效的主题，避免 poll 首次触发前的状态不一致
        self._current_effective = self._resolve_effective()

    def _save(self) -> None:
        if self._db is None:
            return
        self._db.set_config("theme.mode", self._mode.value)

    # ── 系统主题监听 ──

    def start_system_watch(self) -> None:
        """启动系统主题轮询（每 2 秒检测 WM_SETTINGCHANGE 等效变化）。"""
        from PySide6.QtCore import QTimer

        if hasattr(self, "_watch_timer"):
            return
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(2000)
        self._watch_timer.timeout.connect(self._poll_system_theme)
        self._watch_timer.start()

    def _resolve_effective(self) -> ThemeMode:
        if self._mode == ThemeMode.SYSTEM:
            return _detect_system_theme()
        return self._mode

    def _poll_system_theme(self) -> None:
        """轮询检测系统主题是否变化（仅在 SYSTEM 模式下生效）。"""
        if self._mode != ThemeMode.SYSTEM:
            return
        detected = _detect_system_theme()
        if detected != self._current_effective:
            self._current_effective = detected
            self.theme_changed.emit()
