"""常量定义：XML 命名空间、条款号正则、忽略模式"""

import re

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{%s}" % NS["w"]

# 条款号正则：匹配 "10.2"、"1.2.3" 格式，支持 & 连接的复合引用
CLAUSE_HEAD_RE = re.compile(
    r"^(?P<primary>(?:\d+\.)+\d+|\d+)"
    r"(?:\s*&\s*(?P<secondary>(?:\d+\.)+\d+|\d+))?"
    r"(?P<rest>.*)$"
)

# 附录标题正则
ANNEX_HEAD_RE = re.compile(r"^Annex\s+(?P<letter>[A-Z])(?P<rest>.*)$", re.IGNORECASE)

# 应忽略的表格模式（这些表格中的条款号按行切分处理）
IGNORED_TABLE_PATTERNS = [
    re.compile(r"preparing of tests", re.IGNORECASE),
    re.compile(r"tests item", re.IGNORECASE),
    re.compile(r"testing starting date", re.IGNORECASE),
]
