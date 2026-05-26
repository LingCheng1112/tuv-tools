"""DOCX 输出：基于模板 ZIP 复制生成拆分后的 docx 文件"""

from __future__ import annotations

import copy
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from .cleaning import clean_table_xml, clone_paragraph
from .constants import NS, W
from .models import (
    CancelCallback,
    CoreProgressCallback,
    CoreProgressEvent,
    Section,
    SplitCancelled,
    TableSlice,
)
from .utils import CleanPatterns, clean_text, extract_standard_number, safe_name, slugify

_REVISION_HISTORY_PARA_RE = re.compile(r"^History\s+of\s+Revision\s*:?\s*$", re.IGNORECASE)

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


def _is_revision_history_paragraph(paragraph: str) -> bool:
    return bool(_REVISION_HISTORY_PARA_RE.fullmatch(clean_text(paragraph)))


def _is_revision_history_table(table_slice: TableSlice) -> bool:
    if not table_slice.rows:
        return False
    first_row = clean_text(" | ".join(value for value in table_slice.rows[0] if clean_text(value)))
    lowered = first_row.lower()
    return "date" in lowered and "brief" in lowered and "briefing" not in lowered


def _build_document_blocks(
    sections: list[Section],
    inline_clean_patterns: CleanPatterns,
    *,
    filter_revision_history: bool = False,
) -> list[ET.Element]:
    blocks: list[ET.Element] = []

    for section in sections:
        section_blocks: list[ET.Element] = []
        awaiting_revision_history_table = False

        for para_idx, paragraph in enumerate(section.paragraphs):
            if not clean_text(paragraph):
                continue
            if filter_revision_history and _is_revision_history_paragraph(paragraph):
                awaiting_revision_history_table = True
                continue
            if para_idx < len(section.paragraph_elements):
                section_blocks.append(copy.deepcopy(section.paragraph_elements[para_idx]))
            else:
                section_blocks.append(clone_paragraph(paragraph))
        for table_slice in section.table_slices:
            filtered_table = clean_table_xml(table_slice.xml, inline_clean_patterns)
            if filtered_table is None:
                continue
            if filter_revision_history and awaiting_revision_history_table:
                if _is_revision_history_table(table_slice):
                    awaiting_revision_history_table = False
                    continue
            section_blocks.append(filtered_table)
        if not section_blocks:
            continue
        if blocks:
            blocks.append(clone_paragraph(""))
        blocks.extend(section_blocks)
    return blocks


def _build_document_xml(
    sections: list[Section],
    inline_clean_patterns: CleanPatterns,
    *,
    filter_revision_history: bool = False,
) -> bytes:
    document = ET.Element(W + "document", {"xmlns:w": NS["w"]})
    body = ET.SubElement(document, W + "body")

    for block in _build_document_blocks(
        sections,
        inline_clean_patterns,
        filter_revision_history=filter_revision_history,
    ):
        body.append(block)

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

    def flush() -> None:
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
    should_cancel: CancelCallback | None = None,
) -> None:
    _check_cancel(should_cancel)
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    if collapse_shared_tables:
        sections = _collapse_sections_for_version(sections)
    _check_cancel(should_cancel)
    document_xml = _build_document_xml(
        sections,
        inline_clean_patterns,
        filter_revision_history=collapse_shared_tables,
    )
    with zipfile.ZipFile(template_docx, "r") as src, \
         zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            _check_cancel(should_cancel)
            if item.filename == "word/document.xml":
                dst.writestr(item, document_xml)
            else:
                dst.writestr(item, src.read(item.filename))


def get_output_base_dir_name(docx_path: Path) -> str:
    standard_number = extract_standard_number(docx_path.stem)
    return safe_name(standard_number or docx_path.stem)


def _get_output_base_dir_name(docx_path: Path) -> str:
    return get_output_base_dir_name(docx_path)


def _promote_staging_directory(staging_dir: Path, final_dir: Path) -> None:
    """将 partial 目录提升为正式输出，失败时尽量恢复旧输出。"""
    backup_dir = final_dir.with_name(f"{final_dir.name}.backup-{os.getpid()}")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    moved_existing = False
    if final_dir.exists():
        final_dir.rename(backup_dir)
        moved_existing = True

    try:
        staging_dir.rename(final_dir)
    except Exception:
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        if moved_existing and backup_dir.exists():
            backup_dir.rename(final_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def _export_docx_outputs_to_base_dir(
    docx_path: Path,
    sections: list[Section],
    base_dir: Path,
    inline_clean_patterns: CleanPatterns,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> None:
    clause_docx_dir = base_dir / "clauses_docx"
    version_docx_dir = base_dir / "versions_docx"

    _check_cancel(should_cancel)
    clause_id_counts = Counter(s.clause_id for s in sections)
    clause_name_counts: dict[str, int] = defaultdict(int)

    duplicate_bodies: dict[str, list[str]] = {}
    for clause_id, count in clause_id_counts.items():
        if count > 1:
            bodies = [
                re.sub(r"^[\d.,&\s]+", "", s.title).strip()
                for s in sections if s.clause_id == clause_id
            ]
            duplicate_bodies[clause_id] = bodies

    total_clauses = len(sections)
    for index, section in enumerate(sections, 1):
        _check_cancel(should_cancel)
        _emit_progress(
            progress,
            "exporting_clauses",
            "导出条款文件",
            index,
            total_clauses,
            f"导出条款文件 {index}/{total_clauses}: {section.clause_id}",
        )
        if clause_id_counts[section.clause_id] > 1:
            bodies = duplicate_bodies[section.clause_id]
            body = re.sub(r"^[\d.,&\s]+", "", section.title).strip()
            min_len = min(len(b) for b in bodies)
            common_prefix_len = 0
            for char_index in range(min_len):
                if len({b[char_index] for b in bodies}) > 1:
                    break
                common_prefix_len = char_index + 1
            diff = body[common_prefix_len:].strip()
            if diff and diff != body:
                short_slug = slugify(diff)[:30].strip("-")
            elif body:
                short_slug = slugify(body)[:40].strip("-")
            else:
                short_slug = "variant"
            export_stem = safe_name(f"{section.clause_id}_{short_slug or 'variant'}")
        else:
            export_stem = safe_name(section.clause_id)
        clause_name_counts[export_stem] += 1
        if clause_name_counts[export_stem] > 1:
            export_stem = safe_name(f"{export_stem}_{clause_name_counts[export_stem]}")

        clause_docx_file = clause_docx_dir / f"{export_stem}.docx"
        _write_docx_from_template(
            docx_path,
            clause_docx_file,
            [section],
            inline_clean_patterns,
            should_cancel=should_cancel,
        )

    grouped: dict[str, list[Section]] = defaultdict(list)
    for section in sections:
        grouped[section.major_version].append(section)

    grouped_items = list(grouped.items())
    total_versions = len(grouped_items)
    for index, (major_version, group_sections) in enumerate(grouped_items, 1):
        _check_cancel(should_cancel)
        _emit_progress(
            progress,
            "exporting_versions",
            "导出版本文件",
            index,
            total_versions,
            f"导出版本文件 {index}/{total_versions}: {major_version}",
        )
        version_docx_file = version_docx_dir / f"{safe_name(major_version)}.docx"
        _write_docx_from_template(
            docx_path,
            version_docx_file,
            group_sections,
            inline_clean_patterns,
            collapse_shared_tables=True,
            should_cancel=should_cancel,
        )


def export_docx_outputs(
    docx_path: Path,
    sections: list[Section],
    output_root: Path,
    inline_clean_patterns: CleanPatterns,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    staging_root: Path | None = None,
) -> None:
    """导出拆分结果：按条款生成独立 DOCX + 按主版本合并生成 DOCX"""
    final_base_dir = output_root / _get_output_base_dir_name(docx_path)
    base_dir = staging_root if staging_root is not None else final_base_dir

    if staging_root is not None:
        if staging_root.resolve() == final_base_dir.resolve():
            raise ValueError("staging_root must not be the final output directory")
        if staging_root.exists():
            shutil.rmtree(staging_root)
        staging_root.parent.mkdir(parents=True, exist_ok=True)

    try:
        _export_docx_outputs_to_base_dir(
            docx_path,
            sections,
            base_dir,
            inline_clean_patterns,
            progress=progress,
            should_cancel=should_cancel,
        )
        if staging_root is not None:
            _check_cancel(should_cancel)
            _promote_staging_directory(staging_root, final_base_dir)
        _emit_progress(progress, "completed", "完成", 1, 1, "当前文档导出完成")
    except Exception:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise
