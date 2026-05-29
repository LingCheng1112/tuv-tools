"""UI 组件"""

from tuv_tools.config.settings import RESOURCES_DIR
from tuv_tools.ui.theme import ThemeManager, ACCENT_PRIMARY

_CHECKMARK_PATH = (RESOURCES_DIR / "checkmark.png").as_posix()


def checkbox_style() -> str:
    """返回当前主题下的复选框样式表。"""
    c = ThemeManager.instance().colors
    return f"""
    QCheckBox {{
        spacing: 6px;
        margin: 0px;
        padding: 0px;
        color: {c.text_primary};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {c.checkbox_border};
        border-radius: 4px;
        background-color: {c.bg_input};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c.checkbox_bg};
        border-color: {c.checkbox_bg};
        image: url("{_CHECKMARK_PATH}");
    }}
    QCheckBox::indicator:hover {{
        border-color: {c.border_primary};
    }}
"""

# CHECKBOX_STYLE 保留向后兼容别名；新代码请用 checkbox_style()
CHECKBOX_STYLE = checkbox_style()


def scrollbar_style() -> str:
    """返回当前主题下的滚动条样式表。"""
    c = ThemeManager.instance().colors
    return f"""
    QScrollBar:vertical {{
        background-color: {c.scrollbar_bg};
        width: 12px;
        margin: 0px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {c.scrollbar_thumb};
        min-height: 28px;
        border-radius: 6px;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background-color: {c.scrollbar_bg};
        height: 12px;
        margin: 0px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {c.scrollbar_thumb};
        min-width: 28px;
        border-radius: 6px;
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        background: transparent;
        width: 0px;
    }}
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""

FOCUS_STYLE = """
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid #4a9eff;
        outline: none;
    }
    QPushButton:focus {
        border: 1px solid #4a9eff;
        outline: none;
    }
"""
