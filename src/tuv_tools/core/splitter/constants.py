"""常量定义：XML 命名空间、条款号正则、忽略模式"""

import re

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{%s}" % NS["w"]

# 条款号正则：匹配 "10.2"、"13.3,16.3,24.5"、"10.2 & 10.3" 等复合引用
CLAUSE_HEAD_RE = re.compile(
    r"^(?P<compound>(?:\d+\.)+\d+"
    r"(?:\s*[,&]\s*(?:\d+\.)+\d+)*)"
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
