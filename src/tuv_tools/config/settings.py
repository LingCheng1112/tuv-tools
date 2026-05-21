"""全局配置管理"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
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
    """应用全局配置"""
    default_rules_path: Path = field(default_factory=lambda: RESOURCES_DIR / "inline_clean_rules.json")

    def load_inline_clean_patterns(self, rules_path: Path | None = None) -> list[re.Pattern[str]]:
        """加载行内清洗规则为编译后的正则列表"""
        path = rules_path or self.default_rules_path
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = data.get("inline_clean_rules", [])
        patterns: list[re.Pattern[str]] = []
        for rule in rules:
            pattern = rule.get("pattern", "").strip()
            if not pattern:
                continue
            patterns.append(re.compile(pattern, re.IGNORECASE))
        return patterns

    @staticmethod
    def load_api_config(config_path: Path | None = None):
        """加载 API 配置，不存在则返回 None。私钥从独立文件加载。"""
        from tuv_tools.core.chapter.models import ApiConfig
        path = config_path or API_CONFIG_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("rsa_private_key", None)
            config = ApiConfig(**{k: v for k, v in data.items()
                                  if k in ApiConfig.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return None
        key_path = RSA_KEY_FILE
        if key_path.exists():
            config.rsa_private_key = key_path.read_text(encoding="utf-8").strip()
        return config

    @staticmethod
    def save_api_config(config, config_path: Path | None = None) -> None:
        """保存 API 配置到 JSON 文件（不含私钥）"""
        path = config_path or API_CONFIG_FILE
        data = asdict(config)
        data.pop("rsa_private_key", None)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8")
