"""全局配置管理"""

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
