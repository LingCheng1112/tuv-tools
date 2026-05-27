"""全局配置管理 — 通过 DatabaseManager 统一读写"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
import shutil


def _find_project_root() -> Path:
    """从当前文件向上查找包含 pyproject.toml 的目录作为项目根"""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


PROJECT_ROOT = _find_project_root()
RESOURCES_DIR = PROJECT_ROOT / "resources"
API_CONFIG_FILE = PROJECT_ROOT / "api_config.json"
RSA_KEY_FILE = PROJECT_ROOT / "rsa_private.key"
APP_DATA_DIR_NAME = ".tuv-tools"
APP_DATA_BOOTSTRAP_FILE = ".tuv-tools-config.json"
APP_DATA_BOOTSTRAP_KEY = "appDataRoot"
DEFAULT_TOKEN_CACHE_FILE = ".token_cache"
DEFAULT_DB_FILE = "tuv-tools.db"
CHAPTER_BATCH_DIR_NAME = "chapter-batch"
LEGACY_APP_DATA_ROOT = Path.home() / APP_DATA_DIR_NAME


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def get_bootstrap_config_path(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    return root / APP_DATA_BOOTSTRAP_FILE


def load_bootstrap_config(project_root: Path | None = None) -> dict:
    config_path = get_bootstrap_config_path(project_root)
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_default_app_data_root(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    return root / APP_DATA_DIR_NAME


def resolve_app_data_root(project_root: Path | None = None) -> Path:
    bootstrap = load_bootstrap_config(project_root)
    configured = str(bootstrap.get(APP_DATA_BOOTSTRAP_KEY, "")).strip()
    if configured:
        return _normalize_path(configured)
    return resolve_default_app_data_root(project_root)


def resolve_database_path(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / DEFAULT_DB_FILE


def resolve_chapter_batch_root(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / CHAPTER_BATCH_DIR_NAME


def normalize_token_cache_file(token_cache_file: str | None) -> str:
    normalized = (token_cache_file or "").strip()
    if not normalized:
        return DEFAULT_TOKEN_CACHE_FILE
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return DEFAULT_TOKEN_CACHE_FILE
    return normalized


def resolve_token_cache_path(token_cache_file: str, project_root: Path | None = None) -> Path:
    normalized = normalize_token_cache_file(token_cache_file)
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return path.resolve()
    return resolve_app_data_root(project_root) / normalized


def store_bootstrap_config(data_root: Path, project_root: Path | None = None) -> None:
    config_path = get_bootstrap_config_path(project_root)
    config_path.write_text(
        json.dumps({APP_DATA_BOOTSTRAP_KEY: str(_normalize_path(data_root))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass
class AppSettings:
    """应用全局配置，底层通过 DatabaseManager 读写 SQLite"""

    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    default_rules_path: Path | None = None

    def __post_init__(self) -> None:
        self.project_root = _normalize_path(self.project_root)
        if self.default_rules_path is None:
            self.default_rules_path = self.project_root / "resources" / "inline_clean_rules.json"

    @property
    def _db(self):
        from tuv_tools.config.database import DatabaseManager
        return DatabaseManager(self.get_database_path())

    def get_bootstrap_config_path(self) -> Path:
        return get_bootstrap_config_path(self.project_root)

    def has_explicit_app_data_root(self) -> bool:
        bootstrap = load_bootstrap_config(self.project_root)
        return bool(str(bootstrap.get(APP_DATA_BOOTSTRAP_KEY, "")).strip())

    def get_app_data_root(self) -> Path:
        return resolve_app_data_root(self.project_root)

    def get_database_path(self) -> Path:
        return resolve_database_path(self.project_root)

    def get_chapter_batch_root(self) -> Path:
        return resolve_chapter_batch_root(self.project_root)

    def get_token_cache_path(self, token_cache_file: str = DEFAULT_TOKEN_CACHE_FILE) -> Path:
        return resolve_token_cache_path(token_cache_file, self.project_root)

    def set_app_data_root(self, data_root: str | Path) -> None:
        store_bootstrap_config(_normalize_path(data_root), self.project_root)

    def switch_app_data_root(self, data_root: str | Path, *, source_root: Path | None = None) -> bool:
        target_root = _normalize_path(data_root)
        current_root = _normalize_path(source_root or self.get_app_data_root())
        if target_root == current_root:
            target_root.mkdir(parents=True, exist_ok=True)
            self.set_app_data_root(target_root)
            return False

        tracked_entries = [
            entry
            for entry in (DEFAULT_DB_FILE, DEFAULT_TOKEN_CACHE_FILE, CHAPTER_BATCH_DIR_NAME)
            if (current_root / entry).exists()
        ]
        target_root.mkdir(parents=True, exist_ok=True)
        for entry in tracked_entries:
            source_path = current_root / entry
            target_path = target_root / entry
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

        if any(not (target_root / entry).exists() for entry in tracked_entries):
            raise RuntimeError("Failed to copy application data to the selected directory")

        self.set_app_data_root(target_root)
        return True

    def import_app_data_root(self, target_root: str | Path, *, source_root: Path | None = None) -> bool:
        target = _normalize_path(target_root)
        source = _normalize_path(source_root or self.get_app_data_root())
        if target == source or not source.exists():
            return False
        tracked_entries = [
            entry
            for entry in (DEFAULT_DB_FILE, DEFAULT_TOKEN_CACHE_FILE, CHAPTER_BATCH_DIR_NAME)
            if (source / entry).exists()
        ]
        if not tracked_entries:
            return False
        target.mkdir(parents=True, exist_ok=True)
        for entry in tracked_entries:
            source_path = source / entry
            target_path = target / entry
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
        return all((target / entry).exists() for entry in tracked_entries)

    @staticmethod
    def remove_app_data_root(data_root: str | Path) -> None:
        root = _normalize_path(data_root)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def ensure_app_data_root_ready(self) -> Path:
        self.migrate_legacy_app_data_root()
        app_data_root = self.get_app_data_root()
        app_data_root.mkdir(parents=True, exist_ok=True)
        return app_data_root

    def migrate_legacy_app_data_root(
        self,
        *,
        legacy_root: Path | None = None,
        required_files: tuple[str, ...] = (),
    ) -> bool:
        if self.has_explicit_app_data_root():
            return False

        source_root = _normalize_path(legacy_root or LEGACY_APP_DATA_ROOT)
        target_root = self.get_app_data_root()
        if source_root == target_root or not source_root.exists():
            return False

        must_exist = tuple(required_files)
        if must_exist and any(not (source_root / entry).exists() for entry in must_exist):
            return False

        candidate_entries = [
            DEFAULT_DB_FILE,
            DEFAULT_TOKEN_CACHE_FILE,
            CHAPTER_BATCH_DIR_NAME,
        ]
        tracked_entries = [entry for entry in candidate_entries if (source_root / entry).exists()]
        if not tracked_entries:
            return False

        target_root.mkdir(parents=True, exist_ok=True)
        for entry in tracked_entries:
            source_path = source_root / entry
            target_path = target_root / entry
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

        validation_entries = must_exist or tuple(tracked_entries)
        if any(not (target_root / entry).exists() for entry in validation_entries):
            return False

        shutil.rmtree(source_root, ignore_errors=True)
        return True

    def load_inline_clean_patterns(self, rules_path: Path | None = None) -> list[re.Pattern[str]]:
        """加载清洗规则为编译后的正则列表。指定 path 时从文件加载，否则从 DB 加载。"""
        if rules_path is not None:
            data = json.loads(rules_path.read_text(encoding="utf-8"))
            rules = data.get("inline_clean_rules", [])
            patterns: list[re.Pattern[str]] = []
            for rule in rules:
                pattern = rule.get("pattern", "").strip()
                if not pattern:
                    continue
                patterns.append(re.compile(pattern, re.IGNORECASE))
            return patterns
        return self._db.load_clean_patterns()

    def load_api_config(self, config_path: Path | None = None):
        """加载 API 配置。指定 path 时从旧 JSON 文件加载，否则从 DB 加载。"""
        from tuv_tools.core.chapter.models import ApiConfig
        if config_path is not None:
            if not config_path.exists():
                return None
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                data.pop("rsa_private_key", None)
                config = ApiConfig(**{k: v for k, v in data.items()
                                      if k in ApiConfig.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                return None
            key_path = RSA_KEY_FILE
            if key_path.exists():
                config.rsa_private_key = key_path.read_text(encoding="utf-8").strip()
            config.token_cache_file = str(
                self.get_token_cache_path(normalize_token_cache_file(config.token_cache_file))
            )
            return config
        config = self._db.load_api_config()
        if config is None:
            return None
        config.token_cache_file = str(
            self.get_token_cache_path(normalize_token_cache_file(config.token_cache_file))
        )
        return config

    def save_api_config(self, config, config_path: Path | None = None) -> None:
        """保存 API 配置。指定 path 时写旧 JSON 文件，否则写 DB。"""
        from dataclasses import asdict
        config = replace(config, token_cache_file=normalize_token_cache_file(config.token_cache_file))
        if config_path is not None:
            data = asdict(config)
            data.pop("rsa_private_key", None)
            config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            return
        self._db.save_api_config(config)
