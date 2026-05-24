"""Chapter 批量导入文档级公共字段表单。"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLineEdit, QWidget

from .chapter_folder_selector import ChapterFolderSelector


class ChapterBatchDocumentForm(QWidget):
    """承载文档级公共字段编辑。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)

        self._standard_edit = QLineEdit()
        self._folder_selector = ChapterFolderSelector(self)
        self._product_type_edit = QLineEdit()
        self._plan_sr_edit = QLineEdit()
        self._standard_version_edit = QLineEdit()
        self._chapter_version_edit = QLineEdit()
        self._specific_product_edit = QLineEdit()

        layout.addRow("标准", self._standard_edit)
        layout.addRow("归属文件夹", self._folder_selector)
        layout.addRow("产品类别", self._product_type_edit)
        layout.addRow("PlanSR", self._plan_sr_edit)
        layout.addRow("标准版本", self._standard_version_edit)
        layout.addRow("条款版本", self._chapter_version_edit)
        layout.addRow("具体产品", self._specific_product_edit)

    def load_document(self, document: dict) -> None:
        self._standard_edit.setText(document.get("standard", ""))
        self._folder_selector.set_selected_folder(
            document.get("folder_id"),
            document.get("folder_name", ""),
        )
        self._product_type_edit.setText(document.get("product_type", ""))
        self._plan_sr_edit.setText(document.get("plan_sr", "1"))
        self._standard_version_edit.setText(document.get("standard_version", ""))
        self._chapter_version_edit.setText(document.get("chapter_version", "1.0"))
        self._specific_product_edit.setText(document.get("specific_product", ""))

    def to_document_fields(self) -> dict:
        folder_id, folder_name = self._folder_selector.selected_folder()
        return {
            "standard": self._standard_edit.text().strip(),
            "folder_id": folder_id,
            "folder_name": folder_name,
            "product_type": self._product_type_edit.text().strip(),
            "plan_sr": self._plan_sr_edit.text().strip(),
            "standard_version": self._standard_version_edit.text().strip(),
            "chapter_version": self._chapter_version_edit.text().strip(),
            "specific_product": self._specific_product_edit.text().strip(),
        }
