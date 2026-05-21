"""DOCX 解析核心：段落/表格分块、条款号检测、Section 构建"""

from __future__ import annotations

import copy
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from .constants import ANNEX_HEAD_RE, CLAUSE_HEAD_RE, IGNORED_TABLE_PATTERNS, NS, W
from .models import Block, ClauseMatch, Section, TableSlice
from .utils import (
    CleanPatterns,
    cell_text,
    clean_text,
    get_major_version,
    has_title_text,
    normalize_clause_leading_text,
    paragraph_text,
)


def iter_body_blocks(body: ET.Element) -> Iterable[ET.Element]:
    """遍历 document body 下的顶层段落和表格"""
    for child in list(body):
        if child.tag in {W + "p", W + "tbl"}:
            yield child


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
        clause_id = f"Annex_{annex_match.group('letter').upper()}"
        rest = clean_text(annex_match.group("rest"))
        if has_title_text(rest):
            return _build_clause_match(clause_id, normalized)
        return None

    clause_match = CLAUSE_HEAD_RE.match(normalized)
    if not clause_match:
        return None

    primary = clause_match.group("primary")
    if "." not in primary:
        if len(primary) < 2:
            return None
    secondary = clause_match.group("secondary")
    rest = clean_text((clause_match.group("rest") or "").lstrip(".:|- "))
    if "." not in primary and rest and not rest[0].isupper():
        # 裸数字后紧跟小写字母开头的一般是误检（如 "72hours"、"10 times"）
        return None
    if not has_title_text(rest):
        return None
    secondary_refs = [secondary] if secondary else []
    return _build_clause_match(primary, normalized, secondary_refs)


def _try_detect_in_first_cell(first: str) -> ClauseMatch | None:
    """路径 1：直接对第一格文本做条款号检测"""
    return detect_clause_in_text(first)


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
            first,
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
        primary = clause_match.group("primary")
        if "-" in primary:
            return None
        if "." not in primary and len(primary) < 2:
            return None
        secondary = clause_match.group("secondary")
        secondary_refs = [secondary] if secondary else []
        return _build_clause_match(primary, f"{normalized} | {second}", secondary_refs)

    annex_match = ANNEX_HEAD_RE.match(normalized)
    if annex_match:
        clause_id = f"Annex_{annex_match.group('letter').upper()}"
        return _build_clause_match(clause_id, f"{normalized} | {second}")
    return None


def detect_clause_in_cells(cells: list[str]) -> ClauseMatch | None:
    """从表格行的单元格列表中检测条款号"""
    if not cells:
        return None
    first = clean_text(cells[0])
    if not first:
        return None

    if match := _try_detect_in_first_cell(first):
        return match
    if match := _try_detect_in_segments(first):
        return match

    second = next((clean_text(v) for v in cells[1:] if clean_text(v)), "")
    return _try_detect_across_cells(first, second)


def parse_document(docx_path: Path) -> list[Block]:
    """解析 DOCX 文件为 Block 列表

    Raises:
        ValueError: DOCX 文件损坏或缺少 word/document.xml
    """
    blocks: list[Block] = []
    try:
        with zipfile.ZipFile(docx_path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError(f"Invalid DOCX: missing word/document.xml in {docx_path.name}")
            root = ET.fromstring(archive.read("word/document.xml"))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Corrupt DOCX file: {docx_path.name} ({exc})") from exc

    body = root.find("w:body", NS)
    if body is None:
        return blocks

    table_index = 0
    for block_index, element in enumerate(iter_body_blocks(body), 1):
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


def _clone_table_with_rows(table_element: ET.Element, row_start: int, row_end: int) -> ET.Element:
    table_copy = copy.deepcopy(table_element)
    rows = table_copy.findall("./w:tr", NS)
    for idx, row in enumerate(rows):
        if idx < row_start or idx >= row_end:
            table_copy.remove(row)
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


def _split_table_into_sections(block: Block) -> list[tuple[ClauseMatch, TableSlice]]:
    """将表格按行中的条款号切分为多个 (ClauseMatch, TableSlice) 对"""
    rows = block.element.findall("./w:tr", NS)
    row_hits: list[tuple[int, ClauseMatch]] = []
    for idx, row in enumerate(rows):
        row_cells = [cell_text(cell) for cell in row.findall("./w:tc", NS)]
        clause = detect_clause_in_cells(row_cells)
        if clause:
            row_hits.append((idx, clause))

    if not row_hits:
        return []

    sections: list[tuple[ClauseMatch, TableSlice]] = []
    for hit_index, (row_start, clause) in enumerate(row_hits):
        row_end = row_hits[hit_index + 1][0] if hit_index + 1 < len(row_hits) else len(rows)
        sections.append((clause, _build_table_slice(block, row_start, row_end, clause.clause_id)))
    return sections


def _deduplicate_sections(sections: list[Section]) -> list[Section]:
    seen: set[tuple[str, tuple[int, ...]]] = set()
    deduped: list[Section] = []
    for section in sections:
        key = (section.clause_id, tuple(section.block_indexes))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(section)
    return deduped


def build_sections(docx_path: Path) -> list[Section]:
    """解析 DOCX 并构建 Section 列表（主入口）"""
    blocks = parse_document(docx_path)
    sections: list[Section] = []
    current: Section | None = None

    for block in blocks:
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
            elif current and block.text:
                current.add_paragraph(block.index, block.text, block.element)
            continue

        table_sections = _split_table_into_sections(block)
        is_ignored = _should_ignore_table(block)

        for clause, table_slice in table_sections:
            if is_ignored and "." not in clause.clause_id:
                continue
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

    sections = [s for s in sections if s.major_version != "1"]
    return _deduplicate_sections(sections)
