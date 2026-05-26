"""行内文本清洗：按正则规则移除表格单元格中的匹配内容"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .constants import NS, W
from .utils import CleanPatterns, cell_text, clean_text, paragraph_text, run_visible_text


_METADATA_LABEL_RE = re.compile(
    r"^(?:\d+|CH\d+)?\s*[:\-]?\s*"
    r"(?:Test date|Ambient(?:\s+of\s+temperature)?|Equipment No\.?|Equipment ID|Sample No\.?|Sample ID)"
    r"(?:\s*:)?$",
    re.IGNORECASE,
)


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


def _iter_cell_paragraphs(cell: ET.Element) -> list[ET.Element]:
    """返回单元格内所有段落，包含嵌套表格中的段落。"""
    return cell.findall(".//w:p", NS)


def _iter_nested_tables(cell: ET.Element) -> list[ET.Element]:
    """返回单元格内的嵌套表格。"""
    return cell.findall("./w:tbl", NS)


def _strip_empty_nested_tables(cell: ET.Element) -> None:
    """删除单元格内已被清空的嵌套表格。"""
    for table in list(_iter_nested_tables(cell)):
        rows = table.findall("./w:tr", NS)
        has_visible_text = False
        for row in rows:
            row_text = clean_text(" | ".join(
                cell_text(inner_cell) for inner_cell in row.findall("./w:tc", NS)
            ))
            if row_text:
                has_visible_text = True
                break
        if not has_visible_text:
            cell.remove(table)


def _remove_empty_paragraphs_from_cell(cell: ET.Element) -> None:
    paragraphs = cell.findall("./w:p", NS)
    for paragraph in list(paragraphs):
        if clean_text(paragraph_text(paragraph)):
            continue
        cell.remove(paragraph)
    if not cell.findall("./w:p", NS):
        cell.append(clone_paragraph(""))


def _is_metadata_row(after_cells: list[str]) -> bool:
    normalized = [clean_text(value) for value in after_cells if clean_text(value)]
    if not normalized:
        return False
    first_two = normalized[:2]
    return any(_METADATA_LABEL_RE.match(value) for value in first_two)


def _looks_like_metadata_value_row(after_cells: list[str]) -> bool:
    normalized = [clean_text(value) for value in after_cells if clean_text(value)]
    if not normalized:
        return False
    if len(normalized) != 1:
        return False
    value = normalized[0]
    if re.search(r"\d", value):
        return True
    return any(token in value for token in ("℃", "%", "/", ",", "---", "--"))


def _clean_table_element(table: ET.Element, patterns: CleanPatterns) -> ET.Element | None:
    rows = table.findall("./w:tr", NS)

    kept = 0
    previous_row_was_metadata_label = False
    for row in list(rows):
        cells = row.findall("./w:tc", NS)

        before_parts: list[str] = []
        for cell in cells:
            texts = [paragraph_text(p) for p in _iter_cell_paragraphs(cell)]
            before_parts.append(clean_text(" ".join(texts)))
        before_text = clean_text(" | ".join(v for v in before_parts if v))

        for cell in cells:
            for nested_table in list(_iter_nested_tables(cell)):
                cleaned_nested = _clean_table_element(nested_table, patterns)
                if cleaned_nested is None:
                    cell.remove(nested_table)
            for paragraph in _iter_cell_paragraphs(cell):
                _clean_paragraph_inline(paragraph, patterns)
            _strip_empty_nested_tables(cell)
            _remove_empty_paragraphs_from_cell(cell)

        after_cells = [cell_text(cell) for cell in cells]
        after_text = clean_text(" | ".join(v for v in after_cells if clean_text(v)))

        is_metadata_label = _is_metadata_row(after_cells)
        if is_metadata_label:
            table.remove(row)
            previous_row_was_metadata_label = True
            continue
        if previous_row_was_metadata_label and _looks_like_metadata_value_row(after_cells):
            table.remove(row)
            previous_row_was_metadata_label = False
            continue
        previous_row_was_metadata_label = False
        if not after_text and before_text and _should_drop_text_by_rules(before_text, patterns):
            table.remove(row)
            continue
        kept += 1

    if kept == 0:
        return None
    return table


def clean_table_xml(table_xml: str, patterns: CleanPatterns) -> ET.Element | None:
    """对表格 XML 应用清洗规则，返回清洗后的表格元素（全部行被清空时返回 None）"""
    table = ET.fromstring(table_xml)
    return _clean_table_element(table, patterns)
