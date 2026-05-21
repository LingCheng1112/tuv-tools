"""行内文本清洗：按正则规则移除表格单元格中的匹配内容"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .constants import NS, W
from .utils import CleanPatterns, cell_text, clean_text, paragraph_text, run_visible_text


def _should_drop_text_by_rules(text: str, patterns: CleanPatterns) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in patterns)


def _paragraph_removal_ranges(text: str, patterns: CleanPatterns) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            ranges.append((match.start(), match.end()))
    if not ranges:
        return []
    ranges.sort()
    merged: list[list[int]] = [[ranges[0][0], ranges[0][1]]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _clean_paragraph_inline(paragraph: ET.Element, patterns: CleanPatterns) -> None:
    """移除段落中被规则完全覆盖的 run 元素

    只有当一个 run 的文本范围被 removal range 完全包含时才移除，
    避免误删部分重叠的内容。
    """
    children = list(paragraph)
    if not children:
        return

    spans: list[tuple[ET.Element, int, int]] = []
    cursor = 0
    visible_parts: list[str] = []
    for child in children:
        text = run_visible_text(child)
        visible_parts.append(text)
        start = cursor
        cursor += len(text)
        spans.append((child, start, cursor))

    paragraph_visible = "".join(visible_parts)
    ranges = _paragraph_removal_ranges(paragraph_visible, patterns)
    if not ranges:
        return

    for child, span_start, span_end in spans:
        if span_start == span_end:
            continue
        # 只移除被 removal range 完全包含的 run
        fully_covered = any(
            rs <= span_start and span_end <= re_
            for rs, re_ in ranges
        )
        if fully_covered:
            paragraph.remove(child)


def clone_paragraph(text: str) -> ET.Element:
    """创建一个仅包含纯文本的段落元素"""
    paragraph = ET.Element(W + "p")
    run = ET.SubElement(paragraph, W + "r")
    text_node = ET.SubElement(run, W + "t")
    if text.startswith(" ") or text.endswith(" "):
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return paragraph


def _remove_empty_paragraphs_from_cell(cell: ET.Element) -> None:
    paragraphs = cell.findall("./w:p", NS)
    for paragraph in list(paragraphs):
        if clean_text(paragraph_text(paragraph)):
            continue
        cell.remove(paragraph)
    if not cell.findall("./w:p", NS):
        cell.append(clone_paragraph(""))


def clean_table_xml(table_xml: str, patterns: CleanPatterns) -> ET.Element | None:
    """对表格 XML 应用清洗规则，返回清洗后的表格元素（全部行被清空时返回 None）"""
    table = ET.fromstring(table_xml)
    rows = table.findall("./w:tr", NS)

    original_row_texts: list[str] = []
    for row in rows:
        before_cells = []
        for cell in row.findall("./w:tc", NS):
            texts = []
            for paragraph in cell.findall("./w:p", NS):
                texts.append(paragraph_text(paragraph))
            before_cells.append(clean_text(" ".join(texts)))
        original_row_texts.append(
            clean_text(" | ".join([v for v in before_cells if clean_text(v)]))
        )

    for cell in table.findall(".//w:tc", NS):
        for paragraph in cell.findall("./w:p", NS):
            _clean_paragraph_inline(paragraph, patterns)
        _remove_empty_paragraphs_from_cell(cell)

    kept = 0
    for row_index, row in enumerate(list(rows)):
        before_text = original_row_texts[row_index]
        row_cells = [cell_text(cell) for cell in row.findall("./w:tc", NS)]
        after_text = clean_text(" | ".join([v for v in row_cells if clean_text(v)]))

        if not after_text and before_text and _should_drop_text_by_rules(before_text, patterns):
            table.remove(row)
            continue
        kept += 1

    if kept == 0:
        return None
    return table
