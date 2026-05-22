"""全局配置管理 — 通过 DatabaseManager 统一读写"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass
class AppSettings:
    """应用全局配置，底层通过 DatabaseManager 读写 SQLite"""
    default_rules_path: Path = field(default_factory=lambda: RESOURCES_DIR / "inline_clean_rules.json")

    @property
    def _db(self):
        from tuv_tools.config.database import DatabaseManager
        return DatabaseManager()

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
            return config
        return self._db.load_api_config()

    def save_api_config(self, config, config_path: Path | None = None) -> None:
        """保存 API 配置。指定 path 时写旧 JSON 文件，否则写 DB。"""
        from dataclasses import asdict
        if config_path is not None:
            data = asdict(config)
            data.pop("rsa_private_key", None)
            config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            return
        self._db.save_api_config(config)
