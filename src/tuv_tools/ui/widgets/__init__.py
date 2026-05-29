"""UI 组件"""

from tuv_tools.config.settings import RESOURCES_DIR

_CHECKMARK_PATH = (RESOURCES_DIR / "checkmark.png").as_posix()

CHECKBOX_STYLE = f"""
    QCheckBox {{
        spacing: 0px;
        margin: 0px;
        padding: 0px;
    }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: 1px solid #666; border-radius: 3px;
        background-color: #2b2d30;
    }}
    QCheckBox::indicator:checked {{
        background-color: #555; border-color: #888;
        image: url("{_CHECKMARK_PATH}");
    }}
    QCheckBox::indicator:hover {{
        border-color: #aaa;
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
