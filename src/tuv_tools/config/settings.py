"""全局配置管理 — 通过 DatabaseManager 统一读写"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
import shutil
import sys


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _detect_runtime_root() -> Path | None:
    """冻结运行时返回可执行文件目录，否则返回 None。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _find_project_root() -> Path:
    """从当前文件向上查找包含 pyproject.toml 的目录作为项目根。"""
    runtime_root = _detect_runtime_root()
    if runtime_root is not None:
        return runtime_root
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


def _resolve_resources_dir(project_root: Path | None = None) -> Path:
    """解析资源目录，优先兼容 PyInstaller 等冻结运行时。"""
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bundled = Path(meipass).resolve() / "resources"
        if bundled.exists():
            return bundled
    root = _normalize_path(project_root or PROJECT_ROOT)
    candidate = root / "resources"
    if candidate.exists():
        return candidate
    fallback = _normalize_path(PROJECT_ROOT) / "resources"
    if fallback.exists():
        return fallback
    return candidate


def _resolve_from_root(path: str | Path, root: Path) -> Path:
    raw_path = Path(path).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (root / raw_path).resolve()


def _path_text_for_storage(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


PROJECT_ROOT = _find_project_root()
RESOURCES_DIR = _resolve_resources_dir(PROJECT_ROOT)
API_CONFIG_FILE = PROJECT_ROOT / "api_config.json"
RSA_KEY_FILE = PROJECT_ROOT / "rsa_private.key"
APP_DATA_DIR_NAME = ".tuv-tools"
APP_DATA_BOOTSTRAP_FILE = ".tuv-tools-config.json"
APP_DATA_BOOTSTRAP_KEY = "appDataRoot"
SPLITTER_OUTPUT_BOOTSTRAP_KEY = "splitterOutputRoot"
DEFAULT_TOKEN_CACHE_FILE = ".token_cache"
DEFAULT_DB_FILE = "tuv-tools.db"
DEFAULT_SPLITTER_OUTPUT_DIR_NAME = "doc_output"
CHAPTER_BATCH_DIR_NAME = "chapter-batch"
APP_DATA_CERTS_DIR_NAME = "certs"
APP_DATA_PREPARING_DIR_NAME = "preparing"
PACKAGING_DEFAULTS_DIR_NAME = "defaults"
DEFAULTS_API_CONFIG_FILE = "api_config.json"
DEFAULTS_RSA_KEY_FILE = "rsa_private.key"
DEFAULTS_CLEAN_RULES_FILE = "inline_clean_rules.json"
DEFAULT_CHECKBOX_BAS_FILE = "unify_checkboxes.bas"
LEGACY_APP_DATA_ROOT = Path.home() / APP_DATA_DIR_NAME
TRACKED_APP_DATA_ENTRIES = (
    DEFAULT_DB_FILE,
    DEFAULT_TOKEN_CACHE_FILE,
    CHAPTER_BATCH_DIR_NAME,
    APP_DATA_CERTS_DIR_NAME,
    APP_DATA_PREPARING_DIR_NAME,
)


def get_bootstrap_config_path(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    return root / APP_DATA_BOOTSTRAP_FILE


def load_bootstrap_config(project_root: Path | None = None) -> dict:
    config_path = get_bootstrap_config_path(project_root)
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_default_app_data_root(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    return root / APP_DATA_DIR_NAME


def resolve_app_data_root(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    bootstrap = load_bootstrap_config(project_root)
    configured = str(bootstrap.get(APP_DATA_BOOTSTRAP_KEY, "")).strip()
    if configured:
        return _resolve_from_root(configured, root)
    return resolve_default_app_data_root(root)


def resolve_default_splitter_output_root(project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    bootstrap = load_bootstrap_config(project_root)
    configured = str(bootstrap.get(SPLITTER_OUTPUT_BOOTSTRAP_KEY, "")).strip()
    if configured:
        return _resolve_from_root(configured, root)
    return root / DEFAULT_SPLITTER_OUTPUT_DIR_NAME


def normalize_splitter_output_path(output_path: str | Path | None, project_root: Path | None = None) -> str:
    root = _normalize_path(project_root or PROJECT_ROOT)
    normalized = str(output_path or "").strip()
    if not normalized:
        return DEFAULT_SPLITTER_OUTPUT_DIR_NAME
    return _path_text_for_storage(_resolve_from_root(normalized, root), root)


def resolve_splitter_output_root(output_path: str | Path | None, project_root: Path | None = None) -> Path:
    root = _normalize_path(project_root or PROJECT_ROOT)
    normalized = str(output_path or "").strip()
    if not normalized:
        return resolve_default_splitter_output_root(root)
    return _resolve_from_root(normalized, root)


def resolve_database_path(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / DEFAULT_DB_FILE


def resolve_chapter_batch_root(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / CHAPTER_BATCH_DIR_NAME


def resolve_chapter_batch_output_root(
    output_path: str | Path | None,
    project_root: Path | None = None,
) -> Path:
    return resolve_splitter_output_root(output_path, project_root) / CHAPTER_BATCH_DIR_NAME


def resolve_app_data_certs_root(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / APP_DATA_CERTS_DIR_NAME


def resolve_app_data_preparing_root(project_root: Path | None = None) -> Path:
    return resolve_app_data_root(project_root) / APP_DATA_PREPARING_DIR_NAME


def normalize_token_cache_file(token_cache_file: str | None) -> str:
    normalized = (token_cache_file or "").strip()
    if not normalized:
        return DEFAULT_TOKEN_CACHE_FILE
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return DEFAULT_TOKEN_CACHE_FILE
    return normalized


def normalize_ca_cert_file(ca_cert_file: str | Path | None) -> str:
    if ca_cert_file is None:
        return ""
    return str(ca_cert_file).strip()


def resolve_token_cache_path(token_cache_file: str, project_root: Path | None = None) -> Path:
    normalized = normalize_token_cache_file(token_cache_file)
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return path.resolve()
    return resolve_app_data_root(project_root) / normalized


def resolve_ca_cert_path(ca_cert_file: str, project_root: Path | None = None) -> Path:
    normalized = normalize_ca_cert_file(ca_cert_file)
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return path.resolve()
    app_data_candidate = resolve_app_data_root(project_root) / normalized
    if app_data_candidate.exists():
        return app_data_candidate.resolve()
    return (_normalize_path(project_root or PROJECT_ROOT) / normalized).resolve()


def store_bootstrap_config(data_root: Path, project_root: Path | None = None) -> None:
    root = _normalize_path(project_root or PROJECT_ROOT)
    config_path = get_bootstrap_config_path(root)
    bootstrap = load_bootstrap_config(root)
    normalized_data_root = _normalize_path(data_root)
    if normalized_data_root == resolve_default_app_data_root(root):
        bootstrap.pop(APP_DATA_BOOTSTRAP_KEY, None)
    else:
        bootstrap[APP_DATA_BOOTSTRAP_KEY] = _path_text_for_storage(normalized_data_root, root)

    if not bootstrap:
        if config_path.exists():
            config_path.unlink()
        return

    config_path.write_text(
        json.dumps(bootstrap, ensure_ascii=False, indent=2),
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
            self.default_rules_path = self.get_resources_dir() / "inline_clean_rules.json"

    @property
    def _db(self):
        from tuv_tools.config.database import DatabaseManager
        return DatabaseManager(self.get_database_path())

    def get_bootstrap_config_path(self) -> Path:
        return get_bootstrap_config_path(self.project_root)

    def get_resources_dir(self) -> Path:
        return _resolve_resources_dir(self.project_root)

    def get_packaging_defaults_dir(self) -> Path:
        return self.get_resources_dir() / PACKAGING_DEFAULTS_DIR_NAME

    def has_explicit_app_data_root(self) -> bool:
        bootstrap = load_bootstrap_config(self.project_root)
        return bool(str(bootstrap.get(APP_DATA_BOOTSTRAP_KEY, "")).strip())

    def get_app_data_root(self) -> Path:
        return resolve_app_data_root(self.project_root)

    def get_default_splitter_output_root(self) -> Path:
        return resolve_default_splitter_output_root(self.project_root)

    def get_splitter_output_root(self, output_path: str | Path | None) -> Path:
        return resolve_splitter_output_root(output_path, self.project_root)

    def normalize_splitter_output_path(self, output_path: str | Path | None) -> str:
        return normalize_splitter_output_path(output_path, self.project_root)

    def get_database_path(self) -> Path:
        return resolve_database_path(self.project_root)

    def get_chapter_batch_root(self) -> Path:
        return resolve_chapter_batch_root(self.project_root)

    def get_chapter_batch_output_root(self) -> Path:
        output_path = self._db.get_config("splitter.output_path", "")
        return resolve_chapter_batch_output_root(output_path, self.project_root)

    def get_app_data_certs_root(self) -> Path:
        return resolve_app_data_certs_root(self.project_root)

    def get_app_data_preparing_root(self) -> Path:
        return resolve_app_data_preparing_root(self.project_root)

    def get_default_checkbox_bas_path(self) -> Path:
        self._ensure_default_checkbox_bas(self.get_app_data_root())
        return self.get_app_data_preparing_root() / DEFAULT_CHECKBOX_BAS_FILE

    def get_checkbox_bas_path(self, checkbox_bas_file: str | Path | None) -> Path:
        normalized = str(checkbox_bas_file or "").strip()
        if not normalized:
            return self.get_default_checkbox_bas_path()
        return _resolve_from_root(normalized, self.get_app_data_root())

    def get_token_cache_path(self, token_cache_file: str = DEFAULT_TOKEN_CACHE_FILE) -> Path:
        return resolve_token_cache_path(token_cache_file, self.project_root)

    def get_ca_cert_path(self, ca_cert_file: str) -> Path:
        return resolve_ca_cert_path(ca_cert_file, self.project_root)

    def copy_checkbox_bas_to_app_data(
        self,
        checkbox_bas_file: str | Path | None,
        *,
        target_root: Path | None = None,
    ) -> str:
        normalized = str(checkbox_bas_file or "").strip()
        if not normalized:
            return ""

        source_path = Path(normalized).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Checkbox BAS file not found: {source_path}")

        target_root = _normalize_path(target_root or self.get_app_data_root())
        target_dir = target_root / APP_DATA_PREPARING_DIR_NAME
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            relative_existing = source_path.relative_to(target_root)
        except ValueError:
            relative_existing = None

        if relative_existing is not None:
            return Path(relative_existing).as_posix()

        target_path = target_dir / source_path.name
        shutil.copy2(source_path, target_path)
        return Path(APP_DATA_PREPARING_DIR_NAME, source_path.name).as_posix()

    def set_app_data_root(self, data_root: str | Path) -> None:
        store_bootstrap_config(_normalize_path(data_root), self.project_root)

    def switch_app_data_root(self, data_root: str | Path, *, source_root: Path | None = None) -> bool:
        target_root = _normalize_path(data_root)
        current_root = _normalize_path(source_root or self.get_app_data_root())
        if target_root == current_root:
            target_root.mkdir(parents=True, exist_ok=True)
            self.set_app_data_root(target_root)
            return False

        tracked_entries = [entry for entry in TRACKED_APP_DATA_ENTRIES if (current_root / entry).exists()]
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
        tracked_entries = [entry for entry in TRACKED_APP_DATA_ENTRIES if (source / entry).exists()]
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
        store_bootstrap_config(app_data_root, self.project_root)
        self._seed_packaging_defaults(app_data_root)
        self._ensure_default_checkbox_bas(app_data_root)
        return app_data_root

    @staticmethod
    def _load_default_rules_from_file(rules_path: Path) -> list[dict]:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        rules = data.get("inline_clean_rules", [])
        return rules if isinstance(rules, list) else []

    @staticmethod
    def _load_default_api_config_from_file(config_path: Path):
        from tuv_tools.core.chapter.models import ApiConfig

        data = json.loads(config_path.read_text(encoding="utf-8"))
        filtered = {
            key: value
            for key, value in data.items()
            if key in ApiConfig.__dataclass_fields__ and key != "rsa_private_key"
        }
        return ApiConfig(**filtered)

    def _seed_packaging_defaults(self, app_data_root: Path) -> bool:
        defaults_dir = self.get_packaging_defaults_dir()
        if not defaults_dir.exists():
            return False

        seeded = False
        db = self._db

        rules_path = defaults_dir / DEFAULTS_CLEAN_RULES_FILE
        if not db.load_clean_rules() and rules_path.exists():
            db.save_clean_rules(self._load_default_rules_from_file(rules_path))
            seeded = True

        rsa_path = defaults_dir / DEFAULTS_RSA_KEY_FILE
        rsa_missing = not db.load_rsa_private_key()
        rsa_text = ""
        if rsa_missing and rsa_path.exists():
            rsa_text = rsa_path.read_text(encoding="utf-8").strip()

        api_config_path = defaults_dir / DEFAULTS_API_CONFIG_FILE
        if db.load_api_config() is None and api_config_path.exists():
            config = self._load_default_api_config_from_file(api_config_path)
            default_ca_value = normalize_ca_cert_file(config.ca_cert_file)
            if default_ca_value:
                ca_source = defaults_dir / Path(default_ca_value).name
                if ca_source.exists():
                    config = replace(
                        config,
                        ca_cert_file=self.copy_ca_cert_to_app_data(ca_source, target_root=app_data_root),
                    )
                else:
                    config = replace(config, ca_cert_file="")
            db.save_api_config(config)
            seeded = True

        if rsa_missing and rsa_text:
            db.save_rsa_private_key(rsa_text)
            seeded = True

        return seeded

    def _ensure_default_checkbox_bas(self, app_data_root: Path) -> None:
        source = self.get_resources_dir() / DEFAULT_CHECKBOX_BAS_FILE
        if not source.exists():
            return
        target_dir = app_data_root / APP_DATA_PREPARING_DIR_NAME
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / DEFAULT_CHECKBOX_BAS_FILE
        if target_path.exists():
            return
        shutil.copy2(source, target_path)

    def copy_ca_cert_to_app_data(
        self,
        ca_cert_file: str | Path | None,
        *,
        target_root: Path | None = None,
    ) -> str:
        normalized = normalize_ca_cert_file(ca_cert_file)
        if not normalized:
            return ""

        source_path = Path(normalized).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"CA certificate file not found: {source_path}")

        target_root = _normalize_path(target_root or self.get_app_data_root())
        target_dir = target_root / APP_DATA_CERTS_DIR_NAME
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            relative_existing = source_path.relative_to(target_root)
        except ValueError:
            relative_existing = None

        if relative_existing is not None:
            return Path(relative_existing).as_posix()

        target_path = target_dir / source_path.name
        shutil.copy2(source_path, target_path)
        return Path(APP_DATA_CERTS_DIR_NAME, source_path.name).as_posix()

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

        candidate_entries = list(TRACKED_APP_DATA_ENTRIES)
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
            config.ca_cert_file = (
                str(self.get_ca_cert_path(config.ca_cert_file))
                if normalize_ca_cert_file(config.ca_cert_file)
                else ""
            )
            return config
        config = self._db.load_api_config()
        if config is None:
            return None
        config.token_cache_file = str(
            self.get_token_cache_path(normalize_token_cache_file(config.token_cache_file))
        )
        config.ca_cert_file = (
            str(self.get_ca_cert_path(config.ca_cert_file))
            if normalize_ca_cert_file(config.ca_cert_file)
            else ""
        )
        return config

    def save_api_config(self, config, config_path: Path | None = None) -> None:
        """保存 API 配置。指定 path 时写旧 JSON 文件，否则写 DB。"""
        from dataclasses import asdict
        config = replace(
            config,
            token_cache_file=normalize_token_cache_file(config.token_cache_file),
            ca_cert_file=normalize_ca_cert_file(config.ca_cert_file),
        )
        if config_path is not None:
            data = asdict(config)
            data.pop("rsa_private_key", None)
            config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            return
        self._db.save_api_config(config)
