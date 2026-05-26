"""工具函数：文本清洗、slug 生成、标准号提取、XML 文本提取"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from .constants import NS, W

STANDARD_NUMBER_RE = re.compile(r"(?<!\d)(\d{5}-\d+-\d+)(?!\d)")

CleanPatterns = list[re.Pattern[str]]


def clean_text(value: str) -> str:
    """合并连续空白为单个空格并去除首尾空白"""
    return " ".join((value or "").split())


def normalize_clause_leading_text(text: str) -> str:
    """去除条款文本前导的非字母数字字符，修正连续点号"""
    normalized = clean_text(text)
    normalized = re.sub(r"^[^\dA-Za-z]{0,8}", "", normalized)
    normalized = normalized.replace("..", ".")
    return normalized


def has_title_text(text: str) -> bool:
    """判断文本是否包含至少 3 个连续英文字母（即有实质标题内容）"""
    return bool(re.search(r"[A-Za-z]{3,}", text or ""))


def get_major_version(clause_id: str) -> str:
    """从条款 ID 提取主版本号"""
    if clause_id.startswith("Annex_"):
        if "_TABLE" in clause_id:
            return "Annex_TABLE"
        return "Annex"
    return clause_id.split(".", 1)[0]


def safe_name(value: str) -> str:
    """将字符串转为安全的文件名（替换非法字符）"""
    return re.sub(r'[<>:"/\\|?*]+', "_", value).strip().rstrip(".")


def extract_standard_number(value: str) -> str | None:
    """从文件名中提取标准号（如 62233-1-2008）"""
    match = STANDARD_NUMBER_RE.search(value or "")
    return match.group(1) if match else None


def slugify(value: str) -> str:
    """生成 URL/文件名友好的 slug"""
    value = normalize_clause_leading_text(value)
    value = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()
    return value[:80] or "section"


# ── XML 文本提取（供 parsing 和 cleaning 共用） ──────────────


def paragraph_text(paragraph: ET.Element) -> str:
    """提取段落元素的纯文本内容"""
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append(" ")
        elif node.tag == W + "br":
            parts.append(" | ")
    return clean_text("".join(parts))


def cell_text(cell: ET.Element) -> str:
    """提取单元格的纯文本（多段落用 | 分隔）"""
    values = []
    for p in cell.findall(".//w:p", NS):
        text = paragraph_text(p)
        if text:
            values.append(text)
    return clean_text(" | ".join(values))


def cell_text_bold_aware(cell: ET.Element) -> str:
    """提取单元格文本，用 [B]...[/B] 标记加粗 run"""
    parts: list[str] = []
    for p in cell.findall(".//w:p", NS):
        para_parts: list[str] = []
        for r in p.findall(".//w:r", NS):
            is_bold = r.find("w:rPr/w:b", NS) is not None
            t = r.find("w:t", NS)
            text = (t.text or "") if t is not None else ""
            if is_bold:
                para_parts.append(f"[B]{text}[/B]")
            else:
                para_parts.append(text)
        if para_parts:
            parts.append("".join(para_parts))
    return clean_text(" | ".join(parts))


def clause_title_font_consistent(cell: ET.Element, clause_id: str) -> bool:
    """条款号与紧随其后的标题是否在同一 Bold run 中（字体一致）"""
    plain = cell_text(cell)
    marked = cell_text_bold_aware(cell)
    pos = plain.find(clause_id)
    if pos < 0:
        return True
    # 去除标记，定位条款号结束位置
    clean = marked.replace("[B]", "").replace("[/B]", "")
    clean_end = clean.find(clause_id) + len(clause_id)
    if clean_end >= len(clean):
        return True
    # 条款号后第一个非空白非 Bold 标记的内容如果是 [/B]，说明 Bold 在此结束
    m_idx = 0
    c_idx = 0
    while c_idx < clean_end and m_idx < len(marked):
        tag3 = marked[m_idx:m_idx+3]
        tag4 = marked[m_idx:m_idx+4]
        if tag4 == "[/B]":
            m_idx += 4
        elif tag3 == "[B]":
            m_idx += 3
        else:
            m_idx += 1
            c_idx += 1
    # 条款号结束后，允许连续的 [/B][B] 边界，只要首个实质字符仍处于 Bold 即视为一致
    while m_idx < len(marked):
        if marked[m_idx:m_idx+3] == "[B]":
            m_idx += 3
            continue
        if marked[m_idx:m_idx+4] == "[/B]":
            probe = m_idx + 4
            while probe < len(marked):
                if marked[probe:probe+3] == "[B]":
                    m_idx = probe + 3
                    break
                if marked[probe:probe+4] == "[/B]":
                    probe += 4
                    continue
                if marked[probe] in " \t":
                    probe += 1
                    continue
                return False
            else:
                return True
            continue
        if marked[m_idx] in " \t":
            m_idx += 1
            continue
        break  # 遇到非空白非标签内容 → 仍在 Bold 中或已到普通文本
    return True


def run_visible_text(run: ET.Element) -> str:
    """提取单个 run 元素的可见文本（用于清洗时的精确定位）"""
    parts: list[str] = []
    for node in run.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append(" ")
        elif node.tag == W + "br":
            parts.append(" ")
    return "".join(parts)
