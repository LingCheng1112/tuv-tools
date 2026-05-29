"""标准号补录对话框与导入前统一预处理 helper。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from tuv_tools.config.database import _extract_standard_number


def _normalize_path(path: str) -> str:
    return str(Path(path).resolve())


class StandardNumberPromptDialog(QDialog):
    """统一补录缺失标准号的轻量对话框。"""

    def __init__(self, missing_items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("补录标准号")
        self.setMinimumWidth(520)
        self._edits: dict[str, QLineEdit] = {}
        self._build_ui(missing_items)

    def _build_ui(self, missing_items: list[tuple[str, str]]) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel("以下文档未识别到标准号，请在导入前补录。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form_container = QWidget(self)
        form = QFormLayout(form_container)
        form.setContentsMargins(0, 0, 0, 0)

        for normalized_path, file_name in missing_items:
            label = QLabel(file_name)
            label.setToolTip(normalized_path)
            edit = QLineEdit()
            edit.setPlaceholderText("例如 60335-2-35")
            form.addRow(label, edit)
            self._edits[normalized_path] = edit

        layout.addWidget(form_container)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {path: edit.text().strip() for path, edit in self._edits.items()}

    def _accept_if_valid(self) -> None:
        if any(not value for value in self.values().values()):
            QMessageBox.warning(self, "标准号不能为空", "请补全所有缺失标准号后再继续导入。")
            return
        self.accept()


def resolve_standard_number_overrides(parent, paths: list[str]) -> dict[str, str] | None:
    """统一计算导入文件最终使用的标准号。"""
    overrides: dict[str, str] = {}
    missing_items: list[tuple[str, str]] = []

    for raw_path in paths:
        normalized_path = _normalize_path(raw_path)
        file_name = Path(raw_path).name
        standard = (_extract_standard_number(file_name) or "").strip()
        if standard:
            overrides[normalized_path] = standard
            continue
        missing_items.append((normalized_path, file_name))

    if not missing_items:
        return overrides

    dialog = StandardNumberPromptDialog(missing_items, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    overrides.update(dialog.values())
    return overrides
