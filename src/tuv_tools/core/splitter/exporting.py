"""DOCX 输出：基于模板 ZIP 复制生成拆分后的 docx 文件"""

from __future__ import annotations

import copy
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from .cleaning import clean_table_xml, clone_paragraph
from .constants import NS, W
from .models import Section, TableSlice
from .utils import CleanPatterns, clean_text, extract_standard_number, safe_name, slugify


def _merge_table_slices_xml(table_slices: list[TableSlice]) -> str:
    sorted_slices = sorted(table_slices, key=lambda item: item.row_start)
    merged_table = ET.fromstring(sorted_slices[0].xml)
    for row in list(merged_table.findall("./w:tr", NS)):
        merged_table.remove(row)
    for table_slice in sorted_slices:
        slice_table = ET.fromstring(table_slice.xml)
        for row in slice_table.findall("./w:tr", NS):
            merged_table.append(copy.deepcopy(row))
    return ET.tostring(merged_table, encoding="unicode")


def _build_document_xml(sections: list[Section], inline_clean_patterns: CleanPatterns) -> bytes:
    document = ET.Element(W + "document", {"xmlns:w": NS["w"]})
    body = ET.SubElement(document, W + "body")

    for index, section in enumerate(sections):
        for para_idx, paragraph in enumerate(section.paragraphs):
            if clean_text(paragraph):
                if para_idx < len(section.paragraph_elements):
                    body.append(copy.deepcopy(section.paragraph_elements[para_idx]))
                else:
                    body.append(clone_paragraph(paragraph))
        for table_slice in section.table_slices:
            filtered_table = clean_table_xml(table_slice.xml, inline_clean_patterns)
            if filtered_table is not None:
                body.append(filtered_table)
        if index < len(sections) - 1:
            body.append(clone_paragraph(""))

    sect_pr = ET.SubElement(body, W + "sectPr")
    ET.SubElement(sect_pr, W + "pgSz", {W + "w": "11906", W + "h": "16838"})
    ET.SubElement(sect_pr, W + "pgMar", {
        W + "top": "1440", W + "right": "1800",
        W + "bottom": "1440", W + "left": "1800",
        W + "header": "851", W + "footer": "992", W + "gutter": "0",
    })
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)


def _collapse_sections_for_version(sections: list[Section]) -> list[Section]:
    """合并同一表格的多个 TableSlice 为连续行"""
    if not sections:
        return []

    merged_sections: list[Section] = []
    current_table_group: list[TableSlice] = []
    current_table_key: int | None = None

    sections_by_block: dict[int, list[Section]] = defaultdict(list)
    for section in sections:
        for ts in section.table_slices:
            sections_by_block[ts.table_block_index].append(section)

    def flush():
        nonlocal current_table_group, current_table_key
        if not current_table_group:
            return
        first_slice = current_table_group[0]
        source = sections_by_block[current_table_key][0]
        merged = Section(
            clause_id=source.clause_id,
            major_version=source.major_version,
            source_file=source.source_file,
            title=source.title,
            secondary_refs=[],
        )
        merged_xml = _merge_table_slices_xml(current_table_group)
        merged_rows: list[list[str]] = []
        for item in sorted(current_table_group, key=lambda p: p.row_start):
            merged_rows.extend(item.rows)
        merged.table_slices.append(TableSlice(
            table_block_index=first_slice.table_block_index,
            table_index=first_slice.table_index,
            row_start=min(item.row_start for item in current_table_group),
            row_end=max(item.row_end for item in current_table_group),
            title=first_slice.title,
            rows=merged_rows,
            xml=merged_xml,
        ))
        merged_sections.append(merged)
        current_table_group = []
        current_table_key = None

    for section in sections:
        if not section.table_slices or len(section.table_slices) != 1:
            flush()
            merged_sections.append(section)
            continue
        ts = section.table_slices[0]
        if current_table_key is None:
            current_table_key = ts.table_block_index
            current_table_group = [ts]
        elif ts.table_block_index == current_table_key:
            current_table_group.append(ts)
        else:
            flush()
            current_table_key = ts.table_block_index
            current_table_group = [ts]

    flush()
    return merged_sections


def _write_docx_from_template(
    template_docx: Path,
    output_docx: Path,
    sections: list[Section],
    inline_clean_patterns: CleanPatterns,
    collapse_shared_tables: bool = False,
) -> None:
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    if collapse_shared_tables:
        sections = _collapse_sections_for_version(sections)
    document_xml = _build_document_xml(sections, inline_clean_patterns)
    with zipfile.ZipFile(template_docx, "r") as src, \
         zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == "word/document.xml":
                dst.writestr(item, document_xml)
            else:
                dst.writestr(item, src.read(item.filename))


def _get_output_base_dir_name(docx_path: Path) -> str:
    standard_number = extract_standard_number(docx_path.stem)
    return safe_name(standard_number or docx_path.stem)


def export_docx_outputs(
    docx_path: Path,
    sections: list[Section],
    output_root: Path,
    inline_clean_patterns: CleanPatterns,
) -> None:
    """导出拆分结果：按条款生成独立 DOCX + 按主版本合并生成 DOCX"""
    base_dir = output_root / _get_output_base_dir_name(docx_path)
    clause_docx_dir = base_dir / "clauses_docx"
    version_docx_dir = base_dir / "versions_docx"

    clause_id_counts = Counter(s.clause_id for s in sections)
    clause_name_counts: dict[str, int] = defaultdict(int)
    for section in sections:
        title_slug = slugify(section.title)
        if clause_id_counts[section.clause_id] > 1:
            export_stem = safe_name(f"{section.clause_id}_{title_slug}")
        else:
            export_stem = safe_name(section.clause_id)
        clause_name_counts[export_stem] += 1
        if clause_name_counts[export_stem] > 1:
            export_stem = safe_name(f"{export_stem}_{clause_name_counts[export_stem]}")

        clause_docx_file = clause_docx_dir / f"{export_stem}.docx"
        _write_docx_from_template(docx_path, clause_docx_file, [section], inline_clean_patterns)

    grouped: dict[str, list[Section]] = defaultdict(list)
    for section in sections:
        grouped[section.major_version].append(section)

    for major_version, group_sections in grouped.items():
        version_docx_file = version_docx_dir / f"{safe_name(major_version)}.docx"
        _write_docx_from_template(
            docx_path, version_docx_file, group_sections,
            inline_clean_patterns, collapse_shared_tables=True,
        )
