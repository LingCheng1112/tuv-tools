"""SQLite 统一数据管理 — 替代 api_config.json / rsa_private.key / inline_clean_rules.json"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from tuv_tools.core.chapter.models import ApiConfig

DB_DIR = Path.home() / ".tuv-tools"
DB_PATH = DB_DIR / "tuv-tools.db"

_STANDARD_PATTERNS = [
    re.compile(r"IEC[\s_]*(\d+[-\d]*)", re.IGNORECASE),
    re.compile(r"EN[\s_]*(\d+[-\d]*)", re.IGNORECASE),
    re.compile(r"UL[\s_]*(\d+[-\d]*)", re.IGNORECASE),
    re.compile(r"ISO[\s_]*(\d+[-\d]*)", re.IGNORECASE),
    re.compile(r"GB[\s_]*(\d+(?:\.\d+)?(?:-\d+)?)", re.IGNORECASE),
    # 通用无前缀模式：数字-数字-数字 如 60335-2-23
    re.compile(r"(?<!\d)(\d{2,}-\d+[-\d]*)", re.IGNORECASE),
]


def _extract_standard_number(file_name: str) -> str | None:
    """从文件名中提取标准号，如 60335-2-24"""
    for pattern in _STANDARD_PATTERNS:
        match = pattern.search(file_name)
        if match:
            return match.group(1).replace("_", " ").strip()
    return None


def validate_clean_rules(rules: list[dict[str, Any]]) -> None:
    """校验用户配置的清洗正则，保存前阻断非法表达式。"""
    for idx, rule in enumerate(rules):
        pattern = rule.get("pattern", "").strip()
        if not pattern:
            continue
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            name = rule.get("name", "") or f"row {idx + 1}"
            raise ValueError(f"Invalid clean rule regex ({name}): {exc}") from exc


_SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rsa_key (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    private_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clean_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    pattern    TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS imported_documents (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path          TEXT NOT NULL UNIQUE,
    file_name          TEXT NOT NULL,
    standard_number    TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',
    last_section_count INTEGER,
    last_split_at      TEXT,
    error_message      TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
"""


class DatabaseManager:
    """SQLite 数据管理，线程安全（WAL 模式 + 线程局部连接）。模块级单例。"""

    _instance: DatabaseManager | None = None
    _initialized: bool = False

    def __new__(cls, db_path: Path | None = None):
        if db_path is not None:
            instance = super().__new__(cls)
            return instance
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Path | None = None):
        if db_path is None and DatabaseManager._initialized:
            return
        self._db_path = db_path or DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()
        if db_path is None:
            DatabaseManager._initialized = True

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn
        conn.executescript(_SCHEMA)
        conn.commit()
        self._migrate_old_files()

    def _migrate_old_files(self) -> None:
        """首次启动：检测旧配置文件并导入 SQLite，全部成功后才删除旧文件并设标记"""
        migrated_key = self._conn.execute(
            "SELECT value FROM config WHERE key = 'migrated_from_legacy'"
        ).fetchone()

        if migrated_key:
            return

        from tuv_tools.config.settings import API_CONFIG_FILE, PROJECT_ROOT, RSA_KEY_FILE

        rules_path = PROJECT_ROOT / "resources" / "inline_clean_rules.json"
        rules_seen = rules_path.exists()
        rules_ok = False
        if rules_seen:
            try:
                data = json.loads(rules_path.read_text(encoding="utf-8"))
                rules = data.get("inline_clean_rules", [])
                for idx, rule in enumerate(rules):
                    name = rule.get("name", "")
                    pattern = rule.get("pattern", "")
                    if name or pattern:
                        self._conn.execute(
                            "INSERT INTO clean_rules (name, pattern, sort_order) VALUES (?, ?, ?)",
                            (name, pattern, idx),
                        )
                rules_ok = True
            except (json.JSONDecodeError, OSError):
                pass

        api_seen = API_CONFIG_FILE.exists()
        api_ok = False
        if api_seen:
            try:
                data = json.loads(API_CONFIG_FILE.read_text(encoding="utf-8"))
                for key, value in data.items():
                    if key in ("rsa_private_key",):
                        continue
                    self._conn.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                        (f"api.{key}", str(value)),
                    )
                api_ok = True
            except (json.JSONDecodeError, OSError):
                pass

        key_seen = RSA_KEY_FILE.exists()
        key_ok = False
        if key_seen:
            try:
                key_text = RSA_KEY_FILE.read_text(encoding="utf-8").strip()
                if key_text:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO rsa_key (id, private_key) VALUES (1, ?)",
                        (key_text,),
                    )
                key_ok = True
            except OSError:
                pass

        if not (rules_seen or api_seen or key_seen):
            self._conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('migrated_from_legacy', '1')"
            )
            self._conn.commit()
            return

        if (rules_seen and not rules_ok) or (api_seen and not api_ok) or (key_seen and not key_ok):
            self._conn.rollback()
            return

        if rules_ok:
            try:
                rules_path.unlink()
            except OSError:
                pass
        if api_ok:
            try:
                API_CONFIG_FILE.unlink()
            except OSError:
                pass
        if key_ok:
            try:
                RSA_KEY_FILE.unlink()
            except OSError:
                pass

        self._conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('migrated_from_legacy', '1')"
        )
        self._conn.commit()

    # ---- 通用配置 ----

    def get_config(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
        )
        self._conn.commit()

    # ---- RSA 私钥 ----

    def load_rsa_private_key(self) -> str | None:
        row = self._conn.execute("SELECT private_key FROM rsa_key WHERE id = 1").fetchone()
        return row["private_key"] if row else None

    def save_rsa_private_key(self, key: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO rsa_key (id, private_key) VALUES (1, ?)", (key,)
        )
        self._conn.commit()

    def clear_rsa_private_key(self) -> None:
        self._conn.execute("DELETE FROM rsa_key WHERE id = 1")
        self._conn.commit()

    # ---- 清洗规则 ----

    def load_clean_rules(self) -> list[dict[str, Any]]:
        """返回清洗规则列表 [{name, pattern, sort_order}]"""
        rows = self._conn.execute(
            "SELECT name, pattern, sort_order FROM clean_rules ORDER BY sort_order"
        ).fetchall()
        return [{"name": r["name"], "pattern": r["pattern"], "sort_order": r["sort_order"]}
                for r in rows]

    def load_clean_patterns(self) -> list[re.Pattern[str]]:
        """返回编译后的正则列表"""
        rules = self.load_clean_rules()
        return [re.compile(r["pattern"], re.IGNORECASE) for r in rules if r["pattern"].strip()]

    def save_clean_rules(self, rules: list[dict[str, Any]]) -> None:
        """全量替换清洗规则"""
        validate_clean_rules(rules)
        self._conn.execute("DELETE FROM clean_rules")
        for idx, rule in enumerate(rules):
            self._conn.execute(
                "INSERT INTO clean_rules (name, pattern, sort_order) VALUES (?, ?, ?)",
                (rule.get("name", ""), rule.get("pattern", ""),
                 rule.get("sort_order", idx)),
            )
        self._conn.commit()

    # ---- API 配置 ----

    _API_INT_FIELDS = {"token_idle_timeout", "request_timeout"}

    def load_api_config(self) -> ApiConfig | None:
        rows = self._conn.execute(
            "SELECT key, value FROM config WHERE key LIKE 'api.%'"
        ).fetchall()
        if not rows:
            return None
        cfg: dict[str, Any] = {}
        for row in rows:
            field = row["key"][4:]
            val: Any = row["value"]
            if field in self._API_INT_FIELDS:
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    pass
            cfg[field] = val
        config = ApiConfig(**{k: v for k, v in cfg.items()
                              if k in ApiConfig.__dataclass_fields__})
        rsa_key = self.load_rsa_private_key()
        if rsa_key:
            config.rsa_private_key = rsa_key
        return config

    def save_api_config(self, config: ApiConfig) -> None:
        from dataclasses import asdict
        data = asdict(config)
        rsa_key = data.pop("rsa_private_key", "")
        for key, value in data.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (f"api.{key}", str(value)),
            )
        if rsa_key:
            self.save_rsa_private_key(rsa_key)
        else:
            self.clear_rsa_private_key()
        self._conn.commit()

    # ---- 导入文档 ----

    def get_documents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM imported_documents ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_preparing_documents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM imported_documents WHERE status = ? ORDER BY updated_at DESC",
            ("preparing",),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_document(self, file_path: str) -> int:
        """添加文档记录，已存在则跳过。返回记录 ID（已存在时返回已有 ID）"""
        from datetime import datetime
        file_path = str(Path(file_path).resolve())
        existing = self._conn.execute(
            "SELECT id FROM imported_documents WHERE file_path = ?", (file_path,)
        ).fetchone()
        if existing:
            return existing["id"]

        file_name = Path(file_path).name
        standard_number = _extract_standard_number(file_name)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._conn.execute(
            """INSERT INTO imported_documents
               (file_path, file_name, standard_number, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (file_path, file_name, standard_number, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_document(self, doc_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM imported_documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_document_status(
        self, doc_id: int, status: str,
        section_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """更新文档状态。

        status 为 "completed" 时：全量更新 status / last_section_count /
        last_split_at / error_message / updated_at。
        其他状态时：仅更新 status / error_message / updated_at，
        保留已有的 last_section_count 和 last_split_at。

        不传 error 参数时 error_message 会被设为 NULL（即清除旧错误信息）。
        """
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status == "completed":
            self._conn.execute(
                """UPDATE imported_documents
                   SET status = ?, last_section_count = ?, last_split_at = ?,
                       error_message = ?, updated_at = ?
                   WHERE id = ?""",
                (status, section_count, now, error, now, doc_id),
            )
        else:
            self._conn.execute(
                """UPDATE imported_documents
                   SET status = ?, error_message = ?, updated_at = ?
                   WHERE id = ?""",
                (status, error, now, doc_id),
            )
        self._conn.commit()

    def update_documents_status(
        self,
        doc_ids: list[int],
        status: str,
        error: str | None = None,
    ) -> None:
        for doc_id in doc_ids:
            self.update_document_status(doc_id, status, error=error)

    def delete_document(self, doc_id: int) -> None:
        self._conn.execute("DELETE FROM imported_documents WHERE id = ?", (doc_id,))
        self._conn.commit()

    def delete_documents(self, doc_ids: list[int]) -> None:
        if not doc_ids:
            return
        self._conn.executemany(
            "DELETE FROM imported_documents WHERE id = ?",
            [(doc_id,) for doc_id in doc_ids],
        )
        self._conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
