"""DOCX 解析核心：段落/表格分块、条款号检测、Section 构建"""

from __future__ import annotations

import copy
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from .constants import ANNEX_HEAD_RE, CLAUSE_HEAD_RE, IGNORED_TABLE_PATTERNS, NS, W
from .models import (
    Block,
    CancelCallback,
    ClauseMatch,
    CoreProgressCallback,
    CoreProgressEvent,
    Section,
    SplitCancelled,
    TableSlice,
)
from .utils import (
    CleanPatterns,
    cell_text,
    clean_text,
    get_major_version,
    has_title_text,
    normalize_clause_leading_text,
    paragraph_has_visible_text,
    paragraph_text,
)


def _emit_progress(
    progress: CoreProgressCallback | None,
    phase: str,
    phase_label: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress is None:
        return
    try:
        progress(CoreProgressEvent(phase, phase_label, current, total, message))
    except Exception:
        return


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise SplitCancelled("Document split cancelled")


def iter_body_blocks(body: ET.Element) -> Iterable[ET.Element]:
    """遍历 document body 下的顶层段落和表格"""
    for child in list(body):
        if child.tag in {W + "p", W + "tbl"}:
            yield child


def _parse_compound_clause(compound: str) -> tuple[str, str, list[str]]:
    """解析复合条款号 13.3,16.3,24.5 → (primary, clause_id, secondary_refs)"""
    parts = re.split(r"\s*[,&]\s*", compound)
    primary = parts[0]
    secondary_refs = parts[1:] if len(parts) > 1 else []
    clause_id = re.sub(r"\s*([,&])\s*", r"\1", compound)
    return primary, clause_id, secondary_refs


def _build_clause_match(clause_id: str, title_hint: str, secondary_refs: list[str] | None = None) -> ClauseMatch:
    return ClauseMatch(
        clause_id=clause_id,
        major_version=get_major_version(clause_id),
        title_hint=clean_text(title_hint),
        secondary_refs=secondary_refs or [],
    )


def detect_clause_in_text(text: str) -> ClauseMatch | None:
    """从段落文本中检测条款号"""
    normalized = normalize_clause_leading_text(text)
    if not normalized:
        return None

    annex_match = ANNEX_HEAD_RE.match(normalized)
    if annex_match:
        letter = annex_match.group("letter").upper()
        suffix = annex_match.group("suffix")
        clause_id = f"Annex_{letter}"
        if suffix:
            clause_id = f"{clause_id} & {suffix}"
        rest = clean_text(annex_match.group("rest") or "")
        if rest.upper().startswith("TABLE"):
            clause_id = f"{clause_id}_TABLE"
        if has_title_text(rest):
            return _build_clause_match(clause_id, rest)
        return None

    clause_match = CLAUSE_HEAD_RE.match(normalized)
    if not clause_match:
        return None

    compound = clause_match.group("compound")
    primary, clause_id, secondary_refs = _parse_compound_clause(compound)
    if "." not in primary:
        if len(primary) < 2:
            return None
    rest = clean_text((clause_match.group("rest") or "").lstrip(".:|- "))
    if rest:
        if rest[0] == "(":
            # 以 ( 开头是模板字段（如 (Testing equipment ID:...)），非条款标题
            return None
        if "." not in primary and not rest[0].isupper():
            return None
        if not has_title_text(rest):
            return None
    elif "." not in primary:
        # 裸数字且无后续文本 → 大概率误检
        return None
    # 点号条款号允许无标题（如 "19.14"），后续段落/表格行会补充内容
    return _build_clause_match(clause_id, normalized, secondary_refs)


def _try_detect_in_first_cell(first: str) -> ClauseMatch | None:
    """路径 1：直接对第一格文本做条款号检测。无实质标题内容时返回 None，留给跨列检测"""
    match = detect_clause_in_text(first)
    if match and match.title_hint:
        # 剥离条款号后检查是否还有实质文本
        body = re.sub(r"^[\d.,&\s]+", "", match.title_hint).strip()
        if body and re.search(r"[A-Za-z]{2,}", body):
            return match
    return None


def _try_detect_in_segments(first: str) -> ClauseMatch | None:
    """路径 2：按 | 拆分第一格，逐段检测条款号"""
    for segment in first.split(" | "):
        segment_match = detect_clause_in_text(segment.strip())
        if not segment_match:
            continue
        seg_stripped = segment.strip().lstrip(" \t☐☒")
        if not seg_stripped.startswith(segment_match.clause_id):
            continue
        after = seg_stripped[len(segment_match.clause_id):].lstrip(".:|- ")
        if not re.match(r"[A-Za-z]{2,}", after):
            continue
        return _build_clause_match(
            segment_match.clause_id,
            after,
            segment_match.secondary_refs,
        )
    return None


def _try_detect_across_cells(first: str, second: str) -> ClauseMatch | None:
    """路径 3+4：首格取条款号（数字或 Annex），次格取标题"""
    if not second or not has_title_text(second):
        return None

    normalized = normalize_clause_leading_text(first)

    clause_match = CLAUSE_HEAD_RE.match(normalized)
    if clause_match:
        compound = clause_match.group("compound")
        primary, clause_id, secondary_refs = _parse_compound_clause(compound)
        if "-" in primary:
            return None
        if "." not in primary and len(primary) < 2:
            return None
        return _build_clause_match(clause_id, second, secondary_refs)

    annex_match = ANNEX_HEAD_RE.match(normalized)
    if annex_match:
        letter = annex_match.group("letter").upper()
        suffix = annex_match.group("suffix")
        clause_id = f"Annex_{letter}"
        if suffix:
            clause_id = f"{clause_id} & {suffix}"
        if second.upper().startswith("TABLE"):
            clause_id = f"{clause_id}_TABLE"
        return _build_clause_match(clause_id, second)
    return None


def _collect_compound_clause_from_single_cell(cells: list[str]) -> ClauseMatch | None:
    """仅当同一个单元格内出现多个条款号时，识别为复合条款。"""
    for cell in cells:
        normalized = clean_text(cell)
        if not normalized:
            continue
        nums = _clause_numbers_in_text(normalized)
        if len(nums) > 1:
            return _build_clause_match("&".join(nums), normalized)
    return None


def detect_clause_in_cells(cells: list[str],
                            cell_elements: list[ET.Element] | None = None) -> list[ClauseMatch]:
    """从表格行的单元格列表中检测条款号。返回所有检测到的条款（支持同单元格多条款）"""
    if not cells:
        return []
    first = clean_text(cells[0])
    if not first:
        return []

    matches: list[ClauseMatch] = []
    if compound_match := _collect_compound_clause_from_single_cell(cells):
        matches.append(compound_match)
        if matches and cell_elements:
            matches = [_check_font_consistency(m, cell_elements, cells) for m in matches]
        return matches

    # 标准单条款检测
    match: ClauseMatch | None = None
    if m := _try_detect_in_first_cell(first):
        match = m
    elif m := _try_detect_in_segments(first):
        match = m
    else:
        non_empty_cells = [clean_text(v) for v in cells if clean_text(v)]
        second = next((value for value in non_empty_cells[1:] if value), "")
        if m := _try_detect_across_cells(first, second):
            if "." not in m.clause_id and len(non_empty_cells) > 2:
                match = None
            else:
                match = m
        else:
            cm = CLAUSE_HEAD_RE.match(normalize_clause_leading_text(first))
            if cm and "." in cm.group("compound"):
                compound = cm.group("compound")
                primary, clause_id, secondary_refs = _parse_compound_clause(compound)
                if "." not in primary or len(primary) >= 2:
                    match = _build_clause_match(clause_id, first, secondary_refs)

    if match and cell_elements:
        match = _check_font_consistency(match, cell_elements, cells)
    return [match] if match else []


def _check_font_consistency(match: ClauseMatch, cell_elements, cells) -> ClauseMatch:
    """如果条款号后的标题字体不一致，清空标题"""
    from tuv_tools.core.splitter.utils import clause_title_font_consistent
    # 找到包含条款号的 cell
    search_id = match.clause_id
    if "&" in search_id:
        search_id = search_id.split("&")[0].strip()
    for i, cell_el in enumerate(cell_elements):
        if i >= len(cells):
            break
        if search_id in clean_text(cells[i]):
            if not clause_title_font_consistent(cell_el, search_id):
                return _build_clause_match(match.clause_id, match.clause_id, match.secondary_refs)
            break
    return match


def parse_document(
    docx_path: Path,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[Block]:
    """解析 DOCX 文件为 Block 列表

    Raises:
        ValueError: DOCX 文件损坏或缺少 word/document.xml
    """
    blocks: list[Block] = []
    _check_cancel(should_cancel)
    _emit_progress(progress, "reading", "读取文档", 0, 1, f"读取 {docx_path.name}")
    try:
        with zipfile.ZipFile(docx_path) as archive:
            _check_cancel(should_cancel)
            if "word/document.xml" not in archive.namelist():
                raise ValueError(f"Invalid DOCX: missing word/document.xml in {docx_path.name}")
            root = ET.fromstring(archive.read("word/document.xml"))
            _emit_progress(progress, "reading", "读取文档", 1, 1, "已读取 word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Corrupt DOCX file: {docx_path.name} ({exc})") from exc

    body = root.find("w:body", NS)
    if body is None:
        return blocks

    table_index = 0
    body_blocks = list(iter_body_blocks(body))
    total_blocks = len(body_blocks)
    for block_index, element in enumerate(body_blocks, 1):
        _check_cancel(should_cancel)
        _emit_progress(
            progress,
            "parsing_blocks",
            "解析内容块",
            block_index,
            total_blocks,
            f"解析内容块 {block_index}/{total_blocks}",
        )
        if element.tag == W + "p":
            blocks.append(Block(
                block_type="paragraph",
                index=block_index,
                element=element,
                text=paragraph_text(element),
            ))
        else:
            table_index += 1
            rows = []
            for row in element.findall("./w:tr", NS):
                row_values = [cell_text(cell) for cell in row.findall("./w:tc", NS)]
                rows.append(" | ".join([v for v in row_values if v]))
            blocks.append(Block(
                block_type="table",
                index=block_index,
                element=element,
                text="\n".join([line for line in rows if line]),
                table_index=table_index,
            ))
    return blocks


def _should_ignore_table(block: Block) -> bool:
    preview = block.text.splitlines()[0] if block.text else ""
    preview = clean_text(preview)
    return any(pattern.search(preview) for pattern in IGNORED_TABLE_PATTERNS)


def _find_outer_row_border(rows: list[ET.Element], row_index: int, border_name: str) -> ET.Element | None:
    if row_index < 0 or row_index >= len(rows):
        return None
    for cell in rows[row_index].findall("./w:tc", NS):
        tc_pr = cell.find("./w:tcPr", NS)
        if tc_pr is None:
            continue
        tc_borders = tc_pr.find("w:tcBorders", NS)
        if tc_borders is None:
            continue
        border = tc_borders.find(f"w:{border_name}", NS)
        if border is not None:
            return copy.deepcopy(border)
    return None


def _ensure_tc_borders(cell: ET.Element) -> ET.Element:
    tc_pr = cell.find("./w:tcPr", NS)
    if tc_pr is None:
        tc_pr = ET.Element(W + "tcPr")
        cell.insert(0, tc_pr)
    tc_borders = tc_pr.find("w:tcBorders", NS)
    if tc_borders is None:
        tc_borders = ET.SubElement(tc_pr, W + "tcBorders")
    return tc_borders


def _apply_row_border(row: ET.Element, border_name: str, border_template: ET.Element | None) -> None:
    if border_template is None:
        return
    for cell in row.findall("./w:tc", NS):
        tc_borders = _ensure_tc_borders(cell)
        existing = tc_borders.find(f"w:{border_name}", NS)
        if existing is not None:
            tc_borders.remove(existing)
        tc_borders.append(copy.deepcopy(border_template))


def _clone_table_with_rows(table_element: ET.Element, row_start: int, row_end: int) -> ET.Element:
    source_rows = table_element.findall("./w:tr", NS)
    top_border = _find_outer_row_border(source_rows, 0, "top")
    bottom_border = _find_outer_row_border(source_rows, len(source_rows) - 1, "bottom")
    table_copy = copy.deepcopy(table_element)
    rows = table_copy.findall("./w:tr", NS)
    for idx, row in enumerate(rows):
        if idx < row_start or idx >= row_end:
            table_copy.remove(row)
    sliced_rows = table_copy.findall("./w:tr", NS)
    if sliced_rows and row_start > 0:
        _apply_row_border(sliced_rows[0], "top", top_border)
    if sliced_rows and row_end < len(source_rows):
        _apply_row_border(sliced_rows[-1], "bottom", bottom_border)
    return table_copy


def _build_table_slice(block: Block, row_start: int, row_end: int, clause_id: str) -> TableSlice:
    rows = block.element.findall("./w:tr", NS)
    selected_rows = rows[row_start:row_end]
    rendered_rows: list[list[str]] = []
    for row in selected_rows:
        rendered_rows.append([cell_text(cell) for cell in row.findall("./w:tc", NS)])
    cloned = _clone_table_with_rows(block.element, row_start, row_end)
    return TableSlice(
        table_block_index=block.index,
        table_index=block.table_index or 0,
        row_start=row_start,
        row_end=row_end,
        title=clause_id,
        rows=rendered_rows,
        xml=ET.tostring(cloned, encoding="unicode"),
    )


_HEADING_CLAUSE_RE = re.compile(r"^\s*(\d+\.\d+(?:\.\d+)?)")


def _clause_numbers_in_text(text: str) -> list[str]:
    """按 ☐ 分段，统计各段开头的条款号数量（首段即使无☐也检查）"""
    nums: list[str] = []
    segments = text.split("☐")
    for i, seg in enumerate(segments):
        m = _HEADING_CLAUSE_RE.match(seg)
        if m:
            nums.append(m.group(1))
    return nums


def _share_prefix(nums: list[str]) -> str | None:
    """多个条款号共享的父级前缀（如 22.107.1/22.107.2 返回 '22.107'），无共享返回 None"""
    if len(nums) < 2:
        return None
    prefixes = set()
    for n in nums:
        parts = n.rsplit(".", 1)
        prefixes.add(parts[0] if len(parts) > 1 else n)
    return prefixes.pop() if len(prefixes) == 1 else None


def _split_table_into_sections(
    block: Block,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    scanned_row_offset: int = 0,
    scanned_row_total: int | None = None,
) -> list[tuple[ClauseMatch, TableSlice]]:
    """将表格按行中的条款号切分为多个 (ClauseMatch, TableSlice) 对"""
    rows = block.element.findall("./w:tr", NS)
    row_hits: list[tuple[int, ClauseMatch]] = []
    total_rows = len(rows)
    for idx, row in enumerate(rows):
        _check_cancel(should_cancel)
        current = scanned_row_offset + idx + 1
        total = scanned_row_total if scanned_row_total is not None else total_rows
        _emit_progress(
            progress,
            "splitting_tables",
            "拆分表格",
            current,
            total,
            f"解析表格行 {current}/{total}",
        )
        cell_els = row.findall("./w:tc", NS)
        row_cells = [cell_text(cell) for cell in cell_els]
        clauses = detect_clause_in_cells(row_cells, cell_els)
        for clause in clauses:
            parent_ids = {c.clause_id for _, c in row_hits}
            all_nums: list[str] = []
            for c in row_cells:
                all_nums.extend(_clause_numbers_in_text(clean_text(c)))
            shared_prefix = _share_prefix(all_nums)
            if shared_prefix and shared_prefix in parent_ids:
                continue
            if any(clause.clause_id.startswith(pid + ".") for pid in parent_ids):
                continue
            row_hits.append((idx, clause))

    if not row_hits:
        return []

    sections: list[tuple[ClauseMatch, TableSlice]] = []
    for hit_index, (row_start, clause) in enumerate(row_hits):
        row_end = row_hits[hit_index + 1][0] if hit_index + 1 < len(row_hits) else len(rows)
        sections.append((clause, _build_table_slice(block, row_start, row_end, clause.clause_id)))
    return sections


def _deduplicate_sections(sections: list[Section]) -> list[Section]:
    seen: set[tuple] = set()
    deduped: list[Section] = []
    for section in sections:
        # 用 (clause_id, block_indexes, table_slice row ranges) 作为去重键
        slice_ranges = tuple((ts.row_start, ts.row_end) for ts in section.table_slices)
        key = (section.clause_id, tuple(section.block_indexes), slice_ranges)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(section)
    return deduped


def build_sections(
    docx_path: Path,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[Section]:
    """解析 DOCX 并构建 Section 列表（主入口）"""
    blocks = parse_document(docx_path, progress=progress, should_cancel=should_cancel)
    sections: list[Section] = []
    current: Section | None = None
    total_scanned_table_rows = sum(
        len(block.element.findall("./w:tr", NS))
        for block in blocks
        if block.block_type == "table"
    )
    scanned_row_offset = 0

    for block in blocks:
        _check_cancel(should_cancel)
        if block.block_type == "paragraph":
            clause = detect_clause_in_text(block.text)
            if clause:
                current = Section(
                    clause_id=clause.clause_id,
                    major_version=clause.major_version,
                    source_file=docx_path.name,
                    title=block.text,
                    secondary_refs=clause.secondary_refs,
                )
                current.add_paragraph(block.index, block.text, block.element)
                sections.append(current)
            elif current and paragraph_has_visible_text(block.element):
                current.add_paragraph(block.index, block.text, block.element)
            continue

        table_sections = _split_table_into_sections(
            block,
            progress=progress,
            should_cancel=should_cancel,
            scanned_row_offset=scanned_row_offset,
            scanned_row_total=total_scanned_table_rows,
        )
        scanned_row_offset += len(block.element.findall("./w:tr", NS))
        is_ignored = _should_ignore_table(block)

        for clause, table_slice in table_sections:
            current = Section(
                clause_id=clause.clause_id,
                major_version=clause.major_version,
                source_file=docx_path.name,
                title=clause.title_hint or (
                    table_slice.rows[0][0] if table_slice.rows and table_slice.rows[0] else clause.clause_id
                ),
                secondary_refs=clause.secondary_refs,
            )
            current.add_table_slice(block.index, table_slice)
            sections.append(current)

        if not table_sections and not is_ignored and current:
            whole_table = _build_table_slice(
                block=block,
                row_start=0,
                row_end=len(block.element.findall("./w:tr", NS)),
                clause_id=current.clause_id,
            )
            current.add_table_slice(block.index, whole_table)

    _emit_progress(
        progress,
        "deduplicating",
        "整理条款",
        0,
        1,
        "整理条款并移除重复结果",
    )
    sections = [s for s in sections if s.major_version != "1"]
    result = _deduplicate_sections(sections)
    _emit_progress(progress, "deduplicating", "整理条款", 1, 1, f"识别到 {len(result)} 个条款")
    return result
