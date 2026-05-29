"""统一设置弹窗：拆分配置 / 登录设置 / 清洗规则。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

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

from tuv_tools.config import AppSettings
from tuv_tools.core.chapter.models import ApiConfig
from tuv_tools.core.chapter.session import ChapterSessionManager
from tuv_tools.ui.widgets import CHECKBOX_STYLE


class SettingsDialog(QDialog):
    """统一设置弹窗，三页签。"""

    def __init__(
        self,
        parent=None,
        settings: AppSettings | None = None,
        session_manager: ChapterSessionManager | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(560, 460)
        self.resize(620, 520)
        self._settings = settings or AppSettings()
        self._session_manager = session_manager
        self._db = self._get_db()
        self._original_app_data_root = self._settings.get_app_data_root()
        self._initial_api_config = self._settings.load_api_config() or ApiConfig()

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_splitter_tab(), "文档拆分")
        self._tabs.addTab(self._build_api_tab(), "登录")
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
        resolved_output_root = self._settings.get_splitter_output_root(output_path)
        self._output_edit = QLineEdit(str(resolved_output_root))
        self._output_edit.setPlaceholderText(str(self._settings.get_default_splitter_output_root()))
        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit)
        output_btn = QPushButton("选择...")
        output_btn.clicked.connect(self._choose_output_dir)
        output_row.addWidget(output_btn)
        layout.addRow("默认输出路径:", output_row)

        self._auto_open_cb = QCheckBox("拆分完成后自动打开输出目录")
        self._auto_open_cb.setStyleSheet(CHECKBOX_STYLE)
        self._auto_open_cb.setChecked(self._db.get_config("splitter.auto_open", "false") == "true")
        layout.addRow(self._auto_open_cb)
        return widget

    def _build_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        api_config = self._initial_api_config
        self._api_url_edit = QLineEdit(api_config.base_url or "http://127.0.0.1:8080")
        self._api_user_edit = QLineEdit(api_config.username)
        self._api_pass_edit = QLineEdit(api_config.password)
        self._api_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._ca_cert_path = (api_config.ca_cert_file or "").strip()
        self._ca_cert_status = QLabel()
        self._ca_cert_status.setStyleSheet("color: #4caf50; font-weight: bold;" if self._ca_cert_path else "color: #888;")
        self._update_ca_cert_status()

        ca_row = QHBoxLayout()
        ca_row.addWidget(self._ca_cert_status)
        ca_row.addStretch()
        ca_btn = QPushButton("选择...")
        ca_btn.clicked.connect(self._choose_ca_cert)
        ca_row.addWidget(ca_btn)
        self._ca_clear_btn = QPushButton("清除")
        self._ca_clear_btn.clicked.connect(self._clear_ca_cert)
        ca_row.addWidget(self._ca_clear_btn)
        self._ca_clear_btn.setVisible(bool(self._ca_cert_path))

        form.addRow("URL:", self._api_url_edit)
        form.addRow("用户名:", self._api_user_edit)
        form.addRow("密码:", self._api_pass_edit)
        form.addRow("CA 证书:", ca_row)

        rsa_key = api_config.rsa_private_key
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
        form.addRow("RSA 私钥:", rsa_row)

        layout.addLayout(form)
        layout.addStretch()
        return widget

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

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            self._output_edit.text().strip() or str(self._settings.get_default_splitter_output_root()),
        )
        if path:
            self._output_edit.setText(str(Path(path).resolve()))

    def _choose_app_data_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择本地数据目录",
            self._app_data_root_edit.text().strip() or str(self._original_app_data_root),
        )
        if path:
            self._app_data_root_edit.setText(str(Path(path).resolve()))

    def _choose_ca_cert(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 CA 证书",
            "",
            "Certificate Files (*.pem *.crt *.cer);;All Files (*)",
        )
        if path:
            self._ca_cert_path = str(Path(path).resolve())
            self._update_ca_cert_status()

    def _clear_ca_cert(self) -> None:
        self._ca_cert_path = ""
        self._update_ca_cert_status()

    def _update_ca_cert_status(self) -> None:
        has_cert = bool(self._ca_cert_path.strip())
        self._ca_cert_status.setText("已配置" if has_cert else "未配置")
        self._ca_cert_status.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if has_cert else "color: #888;"
        )
        if hasattr(self, "_ca_clear_btn"):
            self._ca_clear_btn.setVisible(has_cert)

    def _update_rsa_status(self) -> None:
        has_key = bool(self._rsa_edit.text().strip())
        self._rsa_status.setText("已配置" if has_key else "未配置")
        self._rsa_status.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if has_key else "color: #888;"
        )
        self._rsa_clear_btn.setVisible(has_key)

    def _load_rsa_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 RSA 私钥文件",
            "",
            "Key Files (*.key *.pem);;All Files (*)",
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
            self,
            "导入清洗规则",
            "",
            "JSON Files (*.json);;All Files (*)",
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
            self,
            "导出清洗规则",
            "inline_clean_rules.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            rules = self._collect_rules()
            data = {"inline_clean_rules": rules}
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
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

    def _login_signature(self, config: ApiConfig) -> tuple[str, str, str, str, str]:
        return (
            config.base_url.strip(),
            config.username.strip(),
            config.password,
            config.ca_cert_file.strip(),
            config.rsa_private_key.strip(),
        )

    def _current_login_signature(self) -> tuple[str, str, str, str, str]:
        return (
            self._api_url_edit.text().strip(),
            self._api_user_edit.text().strip(),
            self._api_pass_edit.text(),
            self._ca_cert_path.strip(),
            self._rsa_edit.text().strip(),
        )

    def _current_ca_cert_path(self) -> str:
        ca_cert_path = self._ca_cert_path.strip()
        if not ca_cert_path:
            return ""
        candidate = Path(ca_cert_path)
        if candidate.is_absolute():
            return str(candidate)
        return str(self._settings.get_ca_cert_path(ca_cert_path))

    def _build_api_config(self) -> ApiConfig:
        existing = self._settings.load_api_config() or ApiConfig()
        ca_cert_source = self._current_ca_cert_path()
        ca_cert_file = self._settings.copy_ca_cert_to_app_data(ca_cert_source) if ca_cert_source else ""
        return replace(
            existing,
            base_url=self._api_url_edit.text().strip(),
            username=self._api_user_edit.text().strip(),
            password=self._api_pass_edit.text(),
            rsa_private_key=self._rsa_edit.text().strip(),
            ca_cert_file=ca_cert_file,
        )

    def _validate_login_config(self, config: ApiConfig) -> None:
        error = ChapterSessionManager._validate_login_config(config)
        if error:
            raise ValueError(error)

    def _persist_changes(self) -> tuple[bool, bool, ApiConfig, bool]:
        rules = self._collect_rules()
        self._validate_rules(rules)
        login_changed = self._current_login_signature() != self._login_signature(self._initial_api_config)

        selected_app_data_root = Path(self._app_data_root_edit.text().strip()).resolve()
        app_data_root_changed = selected_app_data_root != self._original_app_data_root
        copied = False
        if app_data_root_changed:
            self._db.close()
            old_db_path = self._original_app_data_root / "tuv-tools.db"
            from tuv_tools.config.database import DatabaseManager

            DatabaseManager(old_db_path).close()
            copied = self._settings.import_app_data_root(
                selected_app_data_root,
                source_root=self._original_app_data_root,
            )
            self._settings.set_app_data_root(selected_app_data_root)
            self._db = self._get_db()

        self._db.set_config(
            "splitter.output_path",
            self._settings.normalize_splitter_output_path(self._output_edit.text().strip()),
        )
        self._db.set_config("splitter.auto_open", "true" if self._auto_open_cb.isChecked() else "false")
        api_config = self._build_api_config()
        self._validate_login_config(api_config)
        self._settings.save_api_config(api_config)
        self._db.save_clean_rules(rules)
        return app_data_root_changed, copied, api_config, login_changed

    def _save_and_accept(self) -> None:
        try:
            app_data_root_changed, copied, _api_config, login_changed = self._persist_changes()
        except FileNotFoundError as exc:
            self._show_warning("登录配置错误", str(exc))
            return
        except ValueError as exc:
            title = "登录配置错误" if "HTTPS" in str(exc) or "CA" in str(exc) else "清洗规则错误"
            self._show_warning(title, str(exc))
            return

        if login_changed and self._session_manager is not None and not app_data_root_changed:
            self._session_manager.refresh_login()

        if app_data_root_changed:
            old_root_has_payload = any(self._original_app_data_root.iterdir()) if self._original_app_data_root.exists() else False
            if copied and old_root_has_payload:
                reply = self._ask_delete_old_root()
                if reply == QMessageBox.StandardButton.Yes:
                    self._settings.remove_app_data_root(self._original_app_data_root)
            self._show_information("设置已保存", "本地数据目录已更新，重启工具后生效。")

        self.accept()

    @staticmethod
    def _validate_rules(rules: list[dict]) -> None:
        from tuv_tools.config.database import validate_clean_rules

        validate_clean_rules(rules)

    def _show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def _show_information(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def _ask_delete_old_root(self):
        return QMessageBox.question(
            self,
            "删除旧目录",
            "旧的本地数据目录数据已导入到新路径。是否删除旧文件夹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
