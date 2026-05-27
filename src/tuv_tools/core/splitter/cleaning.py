"""行内文本清洗：按正则规则移除表格单元格中的匹配内容"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .constants import NS, W
from .utils import CleanPatterns, cell_text, clean_text, paragraph_text, run_visible_text


_METADATA_LABEL_RE = re.compile(
    r"^(?:\d+|CH\d+)?\s*[:\-]?\s*"
    r"(?:Test date|Ambient(?:\s+of\s+temperature)?|Equipment(?:\s+No\.?)?|Equipment ID|Sample No\.?|Sample ID)"
    r"(?:\s*:)?$",
    re.IGNORECASE,
)

_METADATA_TOKEN = (
    r"(?:Test date|Ambient(?:\s+of\s+temperature|\s+temperature)?|"
    r"Equipment(?:\s+No\.?)?|Equipment ID|Sample No\.?|Sample ID)"
)

_INLINE_METADATA_ONLY_RE = re.compile(
    rf"^(?:\s*{_METADATA_TOKEN}\s*:\s*(?:\.\s*)?)+$",
    re.IGNORECASE,
)

_INLINE_METADATA_FRAGMENT_PATTERNS = [
    re.compile(
        rf"Equipment(?:\s+ID)?\s*:\s*Sample\s+ID\s*:\s*(?:\.\s*)?",
        re.IGNORECASE,
    ),
    re.compile(rf"{_METADATA_TOKEN}\s*:\s*(?:\.\s*)?", re.IGNORECASE),
]


def _should_drop_text_by_rules(text: str, patterns: CleanPatterns) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in patterns)


def _paragraph_removal_ranges(text: str, patterns: CleanPatterns) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    inline_metadata_with_content = _has_inline_metadata_with_content(text)
    if inline_metadata_with_content:
        ranges.extend(_metadata_fragment_ranges(text))
    for pattern in patterns:
        if inline_metadata_with_content and _is_metadata_rule(pattern):
            continue
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
    if _INLINE_METADATA_ONLY_RE.fullmatch(clean_text(paragraph_visible)):
        for child in list(paragraph):
            paragraph.remove(child)
        return
    ranges = _paragraph_removal_ranges(paragraph_visible, patterns)
    if not ranges:
        return
    _trim_ranges_from_paragraph_text(paragraph, ranges)

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


def _ensure_tc_borders(cell: ET.Element) -> ET.Element:
    tc_pr = cell.find("./w:tcPr", NS)
    if tc_pr is None:
        tc_pr = ET.Element(W + "tcPr")
        cell.insert(0, tc_pr)
    tc_borders = tc_pr.find("w:tcBorders", NS)
    if tc_borders is None:
        tc_borders = ET.SubElement(tc_pr, W + "tcBorders")
    return tc_borders


def _border_copy(cell: ET.Element, border_name: str) -> ET.Element | None:
    tc_pr = cell.find("./w:tcPr", NS)
    if tc_pr is None:
        return None
    tc_borders = tc_pr.find("w:tcBorders", NS)
    if tc_borders is None:
        return None
    border = tc_borders.find(f"w:{border_name}", NS)
    if border is None:
        return None
    return ET.fromstring(ET.tostring(border, encoding="unicode"))


def _table_border_copy(table: ET.Element, border_name: str) -> ET.Element | None:
    tbl_pr = table.find("./w:tblPr", NS)
    if tbl_pr is None:
        return None
    tbl_borders = tbl_pr.find("w:tblBorders", NS)
    if tbl_borders is None:
        return None
    border = tbl_borders.find(f"w:{border_name}", NS)
    if border is None:
        return None
    return ET.fromstring(ET.tostring(border, encoding="unicode"))


def _apply_border_to_row(row: ET.Element, border_name: str, border_template: ET.Element | None) -> None:
    _apply_border_to_cells(row.findall("./w:tc", NS), border_name, border_template)


def _apply_border_to_cells(
    cells: list[ET.Element],
    border_name: str,
    border_template: ET.Element | None,
) -> None:
    if border_template is None:
        return
    for cell in cells:
        tc_borders = _ensure_tc_borders(cell)
        existing = tc_borders.find(f"w:{border_name}", NS)
        if existing is not None:
            tc_borders.remove(existing)
        cloned_border = ET.fromstring(ET.tostring(border_template, encoding="unicode"))
        cloned_border.tag = W + border_name
        tc_borders.append(cloned_border)


def _first_available_border(rows: list[ET.Element], border_name: str) -> ET.Element | None:
    for row in rows:
        for cell in row.findall("./w:tc", NS):
            border = _border_copy(cell, border_name)
            if border is not None:
                return border
    return None


def _last_available_border(rows: list[ET.Element], border_name: str) -> ET.Element | None:
    for row in reversed(rows):
        for cell in row.findall("./w:tc", NS):
            border = _border_copy(cell, border_name)
            if border is not None:
                return border
    return None


def _first_available_side_border(rows: list[ET.Element], border_name: str) -> ET.Element | None:
    for row in rows:
        cells = row.findall("./w:tc", NS)
        candidates = cells if border_name == "left" else list(reversed(cells))
        for cell in candidates:
            border = _border_copy(cell, border_name)
            if border is not None:
                return border
    return None


def _coalesce_border(*candidates: ET.Element | None) -> ET.Element | None:
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _preserve_outer_borders_after_cleanup(source_table: ET.Element, cleaned_table: ET.Element) -> None:
    source_rows = source_table.findall("./w:tr", NS)
    cleaned_rows = cleaned_table.findall("./w:tr", NS)
    if not source_rows or not cleaned_rows:
        return

    left_border = _coalesce_border(
        _table_border_copy(source_table, "left"),
        _first_available_side_border(source_rows, "left"),
    )
    right_border = _coalesce_border(
        _table_border_copy(source_table, "right"),
        _first_available_side_border(source_rows, "right"),
    )
    top_border = _coalesce_border(
        _table_border_copy(source_table, "top"),
        _first_available_border(source_rows, "top"),
        left_border,
        right_border,
    )
    bottom_border = _coalesce_border(
        _table_border_copy(source_table, "bottom"),
        _last_available_border(source_rows, "bottom"),
        left_border,
        right_border,
        top_border,
    )

    _apply_border_to_row(cleaned_rows[0], "top", top_border)
    _apply_border_to_row(cleaned_rows[-1], "bottom", bottom_border)
    for row in cleaned_rows:
        cells = row.findall("./w:tc", NS)
        if not cells:
            continue
        _apply_border_to_cells([cells[0]], "left", left_border)
        _apply_border_to_cells([cells[-1]], "right", right_border)


def _metadata_fragment_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for pattern in _INLINE_METADATA_FRAGMENT_PATTERNS:
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
    return [(start, end) for start, end in merged]


def _remove_ranges_from_text(text: str, ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        if cursor < start:
            parts.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        parts.append(text[cursor:])
    return "".join(parts)


def _trim_ranges_from_paragraph_text(paragraph: ET.Element, ranges: list[tuple[int, int]]) -> None:
    if not ranges:
        return
    cursor = 0
    for parent in paragraph.iter():
        for child in list(parent):
            if child.tag == W + "tab" or child.tag == W + "br":
                node_start = cursor
                node_end = cursor + 1
                if any(range_start <= node_start and node_end <= range_end for range_start, range_end in ranges):
                    parent.remove(child)
                cursor = node_end
                continue
            if child.tag != W + "t":
                continue
            text = child.text or ""
            if not text:
                continue
            node_start = cursor
            node_end = cursor + len(text)
            parts: list[str] = []
            local_cursor = node_start
            for range_start, range_end in ranges:
                overlap_start = max(node_start, range_start)
                overlap_end = min(node_end, range_end)
                if overlap_start >= overlap_end:
                    continue
                if local_cursor < overlap_start:
                    parts.append(text[local_cursor - node_start:overlap_start - node_start])
                local_cursor = overlap_end
            if local_cursor < node_end:
                parts.append(text[local_cursor - node_start:node_end - node_start])
            child.text = "".join(parts)
            cursor = node_end


def _has_inline_metadata_with_content(text: str) -> bool:
    ranges = _metadata_fragment_ranges(text)
    if not ranges:
        return False
    residual = clean_text(_remove_ranges_from_text(text, ranges))
    return bool(re.search(r"[A-Za-z]{3,}", residual))


def _is_metadata_rule(pattern: re.Pattern[str]) -> bool:
    lowered = pattern.pattern.lower()
    return any(token in lowered for token in ("test date", "ambient", "equipment", "sample"))


def _is_metadata_row(after_cells: list[str]) -> bool:
    normalized = [clean_text(value) for value in after_cells if clean_text(value)]
    if not normalized:
        return False
    first_two = normalized[:2]
    if any(_METADATA_LABEL_RE.match(value) for value in first_two):
        return True
    joined = " ".join(first_two)
    return bool(_INLINE_METADATA_ONLY_RE.fullmatch(joined))


def _looks_like_metadata_value_row(after_cells: list[str]) -> bool:
    normalized = [clean_text(value) for value in after_cells if clean_text(value)]
    if not normalized:
        return False
    if len(normalized) != 1:
        return False
    value = normalized[0]
    if len(re.findall(r"[A-Za-z]{3,}", value)) >= 3 and not re.fullmatch(r"See\s+below", value, re.IGNORECASE):
        return False
    if re.search(r"\d", value):
        return True
    return any(token in value for token in ("℃", "%", "/", ",", "---", "--"))


def _metadata_row_reduced_to_values(before_cells: list[str], after_cells: list[str]) -> bool:
    before_normalized = [clean_text(value) for value in before_cells if clean_text(value)]
    after_normalized = [clean_text(value) for value in after_cells if clean_text(value)]
    if not before_normalized or not after_normalized:
        return False
    if not _is_metadata_row(before_cells):
        return False
    if len(after_normalized) > 2:
        return False

    saw_value_signal = False
    for value in after_normalized:
        if len(re.findall(r"[A-Za-z]{3,}", value)) >= 3 and not re.fullmatch(r"See\s+below", value, re.IGNORECASE):
            return False
        if re.search(r"\d", value) or any(token in value for token in ("℃", "%", "/", ",", "---", "--")):
            saw_value_signal = True
    return saw_value_signal


def _clean_table_element(table: ET.Element, patterns: CleanPatterns) -> ET.Element | None:
    source_table = ET.fromstring(ET.tostring(table, encoding="unicode"))
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
        if _metadata_row_reduced_to_values(before_parts, after_cells):
            table.remove(row)
            previous_row_was_metadata_label = False
            continue
        if previous_row_was_metadata_label and _looks_like_metadata_value_row(after_cells):
            table.remove(row)
            previous_row_was_metadata_label = False
            continue
        previous_row_was_metadata_label = False
        if _INLINE_METADATA_ONLY_RE.fullmatch(after_text):
            table.remove(row)
            continue
        if not after_text and _INLINE_METADATA_ONLY_RE.fullmatch(before_text):
            table.remove(row)
            continue
        if not after_text and before_text and _should_drop_text_by_rules(before_text, patterns):
            table.remove(row)
            continue
        kept += 1

    if kept == 0:
        return None
    _preserve_outer_borders_after_cleanup(source_table, table)
    return table


def clean_table_xml(table_xml: str, patterns: CleanPatterns) -> ET.Element | None:
    """对表格 XML 应用清洗规则，返回清洗后的表格元素（全部行被清空时返回 None）"""
    table = ET.fromstring(table_xml)
    return _clean_table_element(table, patterns)
