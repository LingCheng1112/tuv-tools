"""统一设置弹窗 — 拆分配置 / API 配置 / 清洗规则"""

from __future__ import annotations

import json
from pathlib import Path
from tuv_tools.config import AppSettings
from tuv_tools.ui.widgets import CHECKBOX_STYLE
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    """统一设置弹窗，三个标签页"""

    def __init__(self, parent=None, settings: AppSettings | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(520, 420)
        self.resize(550, 480)
        self._settings = settings or AppSettings()
        self._db = self._get_db()
        self._original_app_data_root = self._settings.get_app_data_root()

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_splitter_tab(), "文档拆分")
        self._tabs.addTab(self._build_api_tab(), "API 配置")
        self._tabs.addTab(self._build_clean_rules_tab(), "清洗规则")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _get_db(self):
        from tuv_tools.config.database import DatabaseManager
        return DatabaseManager(self._settings.get_database_path())

    # ---- 拆分配置标签页 ----

    def _build_splitter_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self._app_data_root_edit = QLineEdit(str(self._original_app_data_root))
        self._app_data_root_edit.setReadOnly(True)
        data_row = QHBoxLayout()
        data_row.addWidget(self._app_data_root_edit)
        data_btn = QPushButton("选择...")
        data_btn.clicked.connect(self._choose_app_data_root)
        data_row.addWidget(data_btn)
        layout.addRow("本地数据目录:", data_row)

        output_path = self._db.get_config("splitter.output_path", "")
        self._output_edit = QLineEdit(output_path)
        self._output_edit.setPlaceholderText("默认: 文档所在目录下的 clauses_docx 和 versions_docx")
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        btn = QPushButton("选择...")
        btn.clicked.connect(self._choose_output_dir)
        row.addWidget(btn)
        layout.addRow("默认输出路径:", row)

        self._auto_open_cb = QCheckBox("拆分完成后自动打开输出目录")
        self._auto_open_cb.setStyleSheet(CHECKBOX_STYLE)
        self._auto_open_cb.setChecked(
            self._db.get_config("splitter.auto_open", "false") == "true"
        )
        layout.addRow(self._auto_open_cb)

        return widget

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._output_edit.setText(path)

    def _choose_app_data_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择本地数据目录",
            self._app_data_root_edit.text().strip() or str(self._original_app_data_root),
        )
        if path:
            self._app_data_root_edit.setText(str(Path(path).resolve()))

    # ---- API 配置标签页 ----

    def _build_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        api_config = self._settings.load_api_config()
        self._api_url_edit = QLineEdit(api_config.base_url if api_config else "http://127.0.0.1:8080")
        layout.addRow("API URL:", self._api_url_edit)
        self._api_user_edit = QLineEdit(api_config.username if api_config else "")
        layout.addRow("用户名:", self._api_user_edit)
        self._api_pass_edit = QLineEdit(api_config.password if api_config else "")
        self._api_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("密码:", self._api_pass_edit)

        rsa_key = api_config.rsa_private_key if api_config else ""
        self._rsa_edit = QLineEdit(rsa_key)
        self._rsa_edit.setVisible(False)

        rsa_row = QHBoxLayout()
        self._rsa_status = QLabel("已配置" if rsa_key else "未配置")
        self._rsa_status.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if rsa_key else "color: #888;"
        )
        rsa_row.addWidget(self._rsa_status)
        rsa_row.addStretch()
        rsa_btn = QPushButton("从文件加载...")
        rsa_btn.clicked.connect(self._load_rsa_file)
        rsa_row.addWidget(rsa_btn)
        self._rsa_clear_btn = QPushButton("清除")
        self._rsa_clear_btn.clicked.connect(self._clear_rsa)
        self._rsa_clear_btn.setVisible(bool(rsa_key))
        rsa_row.addWidget(self._rsa_clear_btn)
        layout.addRow("RSA 私钥:", rsa_row)

        return widget

    def _update_rsa_status(self) -> None:
        has_key = bool(self._rsa_edit.text().strip())
        self._rsa_status.setText("已配置" if has_key else "未配置")
        self._rsa_status.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if has_key else "color: #888;"
        )
        self._rsa_clear_btn.setVisible(has_key)

    def _load_rsa_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 RSA 私钥文件", "", "Key Files (*.key *.pem);;All Files (*)"
        )
        if path:
            try:
                self._rsa_edit.setText(Path(path).read_text(encoding="utf-8").strip())
                self._update_rsa_status()
            except Exception as exc:
                QMessageBox.warning(self, "加载失败", f"无法读取文件: {exc}")

    def _clear_rsa(self) -> None:
        self._rsa_edit.clear()
        self._update_rsa_status()

    # ---- 清洗规则标签页 ----

    def _build_clean_rules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._rules_table = QTableWidget(0, 3)
        self._rules_table.setHorizontalHeaderLabels(["名称", "正则 Pattern", "排序"])
        self._rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._rules_table.setColumnWidth(0, 130)
        self._rules_table.setColumnWidth(2, 50)

        rules = self._db.load_clean_rules()
        self._rules_table.setRowCount(len(rules))
        for idx, rule in enumerate(rules):
            self._rules_table.setItem(idx, 0, QTableWidgetItem(rule["name"]))
            self._rules_table.setItem(idx, 1, QTableWidgetItem(rule["pattern"]))
            self._rules_table.setItem(idx, 2, QTableWidgetItem(str(rule.get("sort_order", idx))))

        layout.addWidget(self._rules_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增行")
        add_btn.clicked.connect(self._add_rule_row)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("删除选中行")
        del_btn.clicked.connect(self._delete_rule_row)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        import_btn = QPushButton("从 JSON 导入...")
        import_btn.clicked.connect(self._import_rules)
        btn_row.addWidget(import_btn)
        export_btn = QPushButton("导出为 JSON...")
        export_btn.clicked.connect(self._export_rules)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

        return widget

    def _add_rule_row(self) -> None:
        row = self._rules_table.rowCount()
        self._rules_table.insertRow(row)
        self._rules_table.setItem(row, 0, QTableWidgetItem(""))
        self._rules_table.setItem(row, 1, QTableWidgetItem(""))
        self._rules_table.setItem(row, 2, QTableWidgetItem(str(row)))

    def _delete_rule_row(self) -> None:
        current = self._rules_table.currentRow()
        if current >= 0:
            self._rules_table.removeRow(current)

    def _import_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入清洗规则", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            rules = data.get("inline_clean_rules", [])
            self._rules_table.setRowCount(len(rules))
            for idx, rule in enumerate(rules):
                self._rules_table.setItem(idx, 0, QTableWidgetItem(rule.get("name", "")))
                self._rules_table.setItem(idx, 1, QTableWidgetItem(rule.get("pattern", "")))
                self._rules_table.setItem(idx, 2, QTableWidgetItem(str(rule.get("sort_order", idx))))
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _export_rules(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出清洗规则", "inline_clean_rules.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            rules = self._collect_rules()
            data = {"inline_clean_rules": rules}
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _collect_rules(self) -> list[dict]:
        rules: list[dict] = []
        for row in range(self._rules_table.rowCount()):
            name_item = self._rules_table.item(row, 0)
            pattern_item = self._rules_table.item(row, 1)
            order_item = self._rules_table.item(row, 2)
            if not name_item and not pattern_item:
                continue
            name = name_item.text().strip() if name_item else ""
            pattern = pattern_item.text().strip() if pattern_item else ""
            if not name and not pattern:
                continue
            try:
                sort_order = int(order_item.text()) if order_item else row
            except (ValueError, AttributeError):
                sort_order = row
            rules.append({"name": name, "pattern": pattern, "sort_order": sort_order})
        return rules

    # ---- 保存 ----

    def _save_and_accept(self) -> None:
        from dataclasses import replace
        from tuv_tools.core.chapter.models import ApiConfig

        rules = self._collect_rules()
        try:
            self._validate_rules(rules)
        except ValueError as exc:
            QMessageBox.warning(self, "清洗规则错误", str(exc))
            return

        existing = self._settings.load_api_config() or ApiConfig()
        api_config = replace(
            existing,
            base_url=self._api_url_edit.text().strip(),
            username=self._api_user_edit.text().strip(),
            password=self._api_pass_edit.text(),
            rsa_private_key=self._rsa_edit.text().strip(),
        )
        selected_app_data_root = Path(self._app_data_root_edit.text().strip()).resolve()
        app_data_root_changed = selected_app_data_root != self._original_app_data_root
        if app_data_root_changed:
            self._settings.switch_app_data_root(selected_app_data_root, source_root=self._original_app_data_root)
            self._db = self._get_db()
        self._db.set_config("splitter.output_path", self._output_edit.text().strip())
        self._db.set_config("splitter.auto_open",
                            "true" if self._auto_open_cb.isChecked() else "false")
        self._settings.save_api_config(api_config)
        self._db.save_clean_rules(rules)
        if app_data_root_changed:
            QMessageBox.information(self, "设置已保存", "本地数据目录已更新，重启工具后生效。")
        self.accept()

    @staticmethod
    def _validate_rules(rules: list[dict]) -> None:
        from tuv_tools.config.database import validate_clean_rules

        validate_clean_rules(rules)
