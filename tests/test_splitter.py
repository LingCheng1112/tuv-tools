"""测试 Splitter 模块核心逻辑"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tuv_tools.core.splitter import build_sections, export_docx_outputs
from tuv_tools.core.splitter.constants import ANNEX_HEAD_RE, CLAUSE_HEAD_RE, IGNORED_TABLE_PATTERNS, NS
from tuv_tools.core.splitter.models import (
    Block,
    ClauseMatch,
    CoreProgressEvent,
    Section,
    SplitCancelled,
    TableSlice,
)
from tuv_tools.core.splitter.parsing import (
    _clone_table_with_rows,
    _should_ignore_table,
    _split_table_into_sections,
    detect_clause_in_cells,
    detect_clause_in_text,
    parse_document,
)
from tuv_tools.core.splitter.cleaning import (
    _clean_paragraph_inline,
    _paragraph_removal_ranges,
    _should_drop_text_by_rules,
    clean_table_xml,
    clone_paragraph,
)
from tuv_tools.core.splitter.utils import (
    cell_text,
    clause_title_font_consistent,
    clean_text,
    extract_standard_number,
    get_major_version,
    has_title_text,
    normalize_clause_leading_text,
    paragraph_text,
    safe_name,
    slugify,
)
from tuv_tools.core.splitter.exporting import (
    _build_document_xml,
    _collapse_sections_for_version,
    _merge_table_slices_xml,
)
from tuv_tools.core.splitter.ui_helpers import (
    STATUS_LABELS,
    extract_clause_test_content,
    is_importable_docx,
    is_selectable_document_status,
    resolve_output_root,
)

FIXTURE = Path(__file__).parent / "fixtures" / "Test Plan for IEC 60335-2-24.doc.docx"


# ═══════════════════════════════════════════════════
# utils 测试
# ═══════════════════════════════════════════════════


class TestCleanText:
    def test_basic(self):
        assert clean_text("  hello  world  ") == "hello world"

    def test_multiline_whitespace(self):
        assert clean_text("line1\n  line2\r\n\tline3") == "line1 line2 line3"

    def test_empty(self):
        assert clean_text("") == ""
        assert clean_text("   ") == ""

    def test_none(self):
        assert clean_text(None) == ""

    def test_preserves_internal_spacing(self):
        assert clean_text("10.2  Test  item") == "10.2 Test item"


class TestGetMajorVersion:
    def test_numeric(self):
        assert get_major_version("10.2") == "10"
        assert get_major_version("22.42.3") == "22"

    def test_single_digit(self):
        assert get_major_version("7.14") == "7"

    def test_annex(self):
        assert get_major_version("Annex_A") == "Annex"


class TestNormalizeClauseLeadingText:
    def test_removes_checkbox_prefix(self):
        result = normalize_clause_leading_text("☐ 10.2 Test item")
        assert result.startswith("10.2")

    def test_fixes_double_dots(self):
        result = normalize_clause_leading_text("10..2 Test")
        assert result == "10.2 Test"

    def test_strips_leading_non_alnum(self):
        result = normalize_clause_leading_text("   --- 7.14 Test")
        assert result == "7.14 Test"


class TestHasTitleText:
    def test_has_letters(self):
        assert has_title_text("Test item description") is True

    def test_no_letters(self):
        assert has_title_text("10.2") is False

    def test_less_than_three_letters(self):
        assert has_title_text("10.2 Te") is False


class TestSafeName:
    def test_replaces_special_chars(self):
        assert safe_name("10.2/3:test") == "10.2_3_test"

    def test_trailing_dot(self):
        assert safe_name("10.2.") == "10.2"


class TestExtractStandardNumber:
    def test_iec_format(self):
        assert extract_standard_number("Test Plan for IEC 60335-2-24.doc") == "60335-2-24"

    def test_none(self):
        assert extract_standard_number("no standard here") is None


class TestSlugify:
    def test_basic(self):
        assert slugify("10.2 Test item") == "10-2-test-item"

    def test_truncated(self):
        long_slug = slugify("a" * 100)
        assert len(long_slug) <= 80


class TestClauseTitleFontConsistent:
    def test_allows_consecutive_bold_runs_after_clause_id(self):
        xml = (
            '<w:tc xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p>"
            "<w:r><w:rPr><w:b/></w:rPr><w:t>19.11</w:t></w:r>"
            "<w:r><w:rPr><w:b/></w:rPr><w:t>2 </w:t></w:r>"
            "<w:r><w:rPr><w:b/></w:rPr><w:t>Abnormal operation</w:t></w:r>"
            "</w:p>"
            "</w:tc>"
        )
        cell = ET.fromstring(xml)
        assert clause_title_font_consistent(cell, "19.112") is True

    def test_rejects_normal_text_after_bold_clause_id(self):
        xml = (
            '<w:tc xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p>"
            "<w:r><w:rPr><w:b/></w:rPr><w:t>10.2</w:t></w:r>"
            "<w:r><w:t> Measured value</w:t></w:r>"
            "</w:p>"
            "</w:tc>"
        )
        cell = ET.fromstring(xml)
        assert clause_title_font_consistent(cell, "10.2") is False


# ═══════════════════════════════════════════════════
# parsing 测试
# ═══════════════════════════════════════════════════


class TestDetectClauseInText:
    def test_numeric_clause(self):
        result = detect_clause_in_text("10.2 Test item description")
        assert result is not None
        assert result.clause_id == "10.2"
        assert result.major_version == "10"

    def test_multi_level_clause(self):
        result = detect_clause_in_text("22.42.3 Test item description")
        assert result is not None
        assert result.clause_id == "22.42.3"

    def test_ampersand_clause(self):
        result = detect_clause_in_text("8.1.4& 22.42 Test for protective impedance")
        assert result is not None
        assert result.clause_id == "8.1.4&22.42"
        assert "22.42" in result.secondary_refs

    def test_annex(self):
        result = detect_clause_in_text("Annex A Normative references")
        assert result is not None
        assert result.clause_id == "Annex_A"

    def test_no_title_text_ignored(self):
        # 条款号后必须有实质标题文字（至少 3 个连续字母）
        result = detect_clause_in_text("10.2 1.2")
        assert result is None

    def test_no_clause_match(self):
        result = detect_clause_in_text("Just a regular paragraph")
        assert result is None

    def test_single_digit_too_short(self):
        result = detect_clause_in_text("1 Test")
        assert result is None


class TestDetectClauseInCells:
    def test_first_cell_clause(self):
        results = detect_clause_in_cells(["10.2 Test item description", "extra info"])
        assert len(results) == 1
        assert results[0].clause_id == "10.2"

    def test_segmented_cell(self):
        # 第一格有多个用 | 分隔的条目
        results = detect_clause_in_cells(["10.2 Test | 10.3 Other test", ""])
        assert len(results) == 1
        assert results[0].clause_id == "10.2"

    def test_second_cell_title(self):
        # 第一格只有条款号，第二格有标题文字
        results = detect_clause_in_cells(["10.2", "Test item description here"])
        assert len(results) == 1
        assert results[0].clause_id == "10.2"

    def test_annex_in_cell(self):
        results = detect_clause_in_cells(["Annex A Normative references", ""])
        assert len(results) == 1
        assert results[0].clause_id == "Annex_A"

    def test_empty_cells(self):
        results = detect_clause_in_cells([])
        assert results == []

    def test_no_match(self):
        results = detect_clause_in_cells(["No clause here", "Still no clause"])
        assert results == []

    def test_measurement_row_is_not_detected_as_clause(self):
        results = detect_clause_in_cells(["Test voltage(V)", "260.3", "Current(A)", "12.04", "Power input(W)", "3130.3"])
        assert results == []

    def test_numbered_data_row_is_not_detected_as_clause(self):
        results = detect_clause_in_cells(["1", "Power cord", "46.6", "25.4", "50"])
        assert results == []

    def test_result_row_is_not_detected_as_clause(self):
        results = detect_clause_in_cells(["L/N and plastic panel", "0.003", "0.35(peak)"])
        assert results == []


class TestParseDocument:
    def test_returns_blocks(self):
        blocks = parse_document(FIXTURE)
        assert len(blocks) > 0
        types = {b.block_type for b in blocks}
        assert types <= {"paragraph", "table"}

    def test_block_index_ordered(self):
        blocks = parse_document(FIXTURE)
        indices = [b.index for b in blocks]
        assert indices == sorted(indices)

    def test_table_block_has_table_index(self):
        blocks = parse_document(FIXTURE)
        tables = [b for b in blocks if b.block_type == "table"]
        if tables:
            for t in tables:
                assert t.table_index is not None
                assert t.table_index >= 1

    def test_bad_file_raises_value_error(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_text("not a zip file")
        with pytest.raises(ValueError):
            parse_document(bad)


class TestBuildSections:
    def test_produces_sections(self):
        sections = build_sections(FIXTURE)
        assert len(sections) > 0
        for s in sections:
            assert s.clause_id
            assert s.major_version
            assert s.source_file == FIXTURE.name
            assert s.block_indexes or s.table_slices

    def test_all_have_block_indexes(self):
        sections = build_sections(FIXTURE)
        for s in sections:
            assert len(s.block_indexes) > 0

    def test_no_empty_title(self):
        sections = build_sections(FIXTURE)
        for s in sections:
            assert s.title

    def test_version_1_filtered_out(self):
        sections = build_sections(FIXTURE)
        for s in sections:
            assert s.major_version != "1"

    def test_no_duplicates(self):
        sections = build_sections(FIXTURE)
        keys = [(s.clause_id, tuple(s.block_indexes)) for s in sections]
        assert len(keys) == len(set(keys))

    def test_emits_progress_events(self):
        events: list[CoreProgressEvent] = []

        sections = build_sections(FIXTURE, progress=events.append)

        assert sections
        phases = [event.phase for event in events]
        assert "reading" in phases
        assert "parsing_blocks" in phases
        assert "deduplicating" in phases
        assert all(event.current >= 0 for event in events)
        assert all(event.total >= 0 for event in events)

    def test_progress_callback_error_does_not_break_parsing(self):
        def broken_progress(_event: CoreProgressEvent) -> None:
            raise RuntimeError("ui callback failed")

        sections = build_sections(FIXTURE, progress=broken_progress)

        assert sections

    def test_cancel_during_build_sections_raises_split_cancelled(self):
        def should_cancel() -> bool:
            return True

        with pytest.raises(SplitCancelled):
            build_sections(FIXTURE, should_cancel=should_cancel)

    def test_data_heavy_table_document_does_not_create_measurement_fake_sections(self):
        sample = Path(r"D:\Data\1类机械式油汀-机械式-60335-2-30.docx")
        if not sample.exists():
            pytest.skip("sample document not available")

        sections = build_sections(sample)
        clause_ids = {section.clause_id for section in sections}

        assert "10.1" in clause_ids
        assert "10.2" in clause_ids
        assert "13.2" in clause_ids
        assert "13.3" in clause_ids
        assert "16.2" in clause_ids
        assert "16.3" in clause_ids

        assert "260.3&12.04&3130.3" not in clause_ids
        assert "46.6&25.4" not in clause_ids
        assert "0.003&0.35" not in clause_ids
        assert "0.003&0.25" not in clause_ids
        assert "3.89&1.2" not in clause_ids
        assert "0.279&7.3" not in clause_ids

    def test_data_heavy_table_document_keeps_19112_test_content(self):
        sample = next(Path(r"D:\Data").glob("*60335-2-30.docx"), None)
        if sample is None:
            pytest.skip("sample document not available")

        sections = build_sections(sample)
        section = next((item for item in sections if item.clause_id == "19.112"), None)

        assert section is not None
        assert "Abnormal operation" in section.title
        assert extract_clause_test_content(section.title).startswith("Abnormal operation")


# ═══════════════════════════════════════════════════
# cleaning 测试
# ═══════════════════════════════════════════════════


class TestShouldDropTextByRules:
    @pytest.fixture
    def patterns(self):
        return [re.compile(r"Test date\s*:[^\n]*", re.IGNORECASE)]

    def test_matching_text(self, patterns):
        assert _should_drop_text_by_rules("Test date: 2024-01-01", patterns) is True

    def test_non_matching_text(self, patterns):
        assert _should_drop_text_by_rules("Normal content here", patterns) is False

    def test_empty_text(self, patterns):
        assert _should_drop_text_by_rules("", patterns) is False


class TestParagraphRemovalRanges:
    @pytest.fixture
    def patterns(self):
        return [re.compile(r"Test date:[^\n]*", re.IGNORECASE)]

    def test_single_match(self, patterns):
        ranges = _paragraph_removal_ranges("prefix Test date: 2024-01-01 suffix", patterns)
        assert len(ranges) >= 1

    def test_no_match(self, patterns):
        ranges = _paragraph_removal_ranges("No match here", patterns)
        assert ranges == []

    def test_overlapping_ranges_merged(self, patterns):
        p2 = [re.compile(r"date:[^\n]*"), re.compile(r"date: 2024")]
        ranges = _paragraph_removal_ranges("Test date: 2024-01-01", p2)
        assert len(ranges) >= 1


class TestCloneParagraph:
    def test_creates_valid_element(self):
        p = clone_paragraph("test content")
        assert p.tag.endswith("p")
        text_nodes = list(p.iter())
        t_nodes = [n for n in text_nodes if n.text == "test content"]
        assert len(t_nodes) == 1


class TestCloneTableWithRows:
    def test_adds_bottom_border_to_truncated_last_row(self):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc><w:tcPr><w:tcBorders><w:top w:val=\"single\" w:sz=\"12\" /></w:tcBorders></w:tcPr><w:p><w:r><w:t>head</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>middle</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:tcPr><w:tcBorders><w:bottom w:val=\"single\" w:sz=\"12\" /></w:tcBorders></w:tcPr><w:p><w:r><w:t>end</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )
        table = ET.fromstring(xml)

        cloned = _clone_table_with_rows(table, 0, 2)
        last_cell = cloned.findall("./w:tr", NS)[-1].find("./w:tc", NS)
        bottom = last_cell.find("./w:tcPr/w:tcBorders/w:bottom", NS)

        assert bottom is not None
        assert bottom.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sz") == "12"

    def test_adds_top_border_to_mid_table_first_row(self):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc><w:tcPr><w:tcBorders><w:top w:val=\"single\" w:sz=\"12\" /></w:tcBorders></w:tcPr><w:p><w:r><w:t>head</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>middle</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:tcPr><w:tcBorders><w:bottom w:val=\"single\" w:sz=\"12\" /></w:tcBorders></w:tcPr><w:p><w:r><w:t>end</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )
        table = ET.fromstring(xml)

        cloned = _clone_table_with_rows(table, 1, 3)
        first_cell = cloned.findall("./w:tr", NS)[0].find("./w:tc", NS)
        top = first_cell.find("./w:tcPr/w:tcBorders/w:top", NS)

        assert top is not None
        assert top.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sz") == "12"


class TestCleanTableXml:
    @pytest.fixture
    def patterns(self):
        return [re.compile(r"Test date\s*:[^\n]*", re.IGNORECASE)]

    def test_returns_element_for_valid_table(self, patterns):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>10.2 Test item</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Normal content</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )
        result = clean_table_xml(xml, patterns)
        assert result is not None

    def test_removes_matching_row(self, patterns):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>Test date: 2024-01-01</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>Normal row</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )
        result = clean_table_xml(xml, patterns)
        assert result is not None
        rows = result.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr")
        assert len(rows) == 1

    def test_removes_nested_metadata_table_but_keeps_title_and_content(self, patterns):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc>"
            "<w:p><w:r><w:t>19.101 Abnormal operation</w:t></w:r></w:p>"
            "<w:tbl>"
            "<w:tr><w:tc><w:p><w:r><w:t>Test date</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>2025.10.30</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>Ambient</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>22.6℃,55.0%</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>Equipment No.</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>G1809691,9020774</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>Sample No.</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>A004122687-001</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl>"
            "<w:p><w:r><w:t>Heaters operated at 1.24Pn</w:t></w:r></w:p>"
            "</w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )

        result = clean_table_xml(xml, patterns)

        assert result is not None
        rendered = ET.tostring(result, encoding="unicode")
        assert "19.101 Abnormal operation" in rendered
        assert "Heaters operated at 1.24Pn" in rendered
        assert "Test date" not in rendered
        assert "2025.10.30" not in rendered
        assert "Equipment No." not in rendered
        assert "A004122687-001" not in rendered

    def test_removes_ambient_metadata_row_with_values(self, patterns):
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>15</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Ambient</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>21.2</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>---</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>--</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>16</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Power cord</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>46.6</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )

        result = clean_table_xml(xml, patterns)

        assert result is not None
        rendered = ET.tostring(result, encoding="unicode")
        assert "Ambient" not in rendered
        assert "21.2" not in rendered
        assert "Power cord" in rendered


# ═══════════════════════════════════════════════════
# exporting 测试
# ═══════════════════════════════════════════════════


class TestMergeTableSlicesXml:
    def test_merges_two_slices(self):
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        slice1 = TableSlice(
            table_block_index=5,
            table_index=1,
            row_start=0,
            row_end=2,
            title="test",
            rows=[["cell1"], ["cell2"]],
            xml=(
                f'<w:tbl xmlns:w="{w}">'
                "<w:tr><w:tc><w:p><w:r><w:t>cell1</w:t></w:r></w:p></w:tc></w:tr>"
                "<w:tr><w:tc><w:p><w:r><w:t>cell2</w:t></w:r></w:p></w:tc></w:tr>"
                "</w:tbl>"
            ),
        )
        slice2 = TableSlice(
            table_block_index=5,
            table_index=1,
            row_start=2,
            row_end=3,
            title="test",
            rows=[["cell3"]],
            xml=(
                f'<w:tbl xmlns:w="{w}">'
                "<w:tr><w:tc><w:p><w:r><w:t>cell3</w:t></w:r></w:p></w:tc></w:tr>"
                "</w:tbl>"
            ),
        )
        merged_xml = _merge_table_slices_xml([slice1, slice2])
        assert "cell1" in merged_xml
        assert "cell2" in merged_xml
        assert "cell3" in merged_xml


class TestBuildDocumentXml:
    @pytest.fixture
    def empty_patterns(self):
        return []

    def test_produces_valid_xml(self, empty_patterns):
        section = Section(
            clause_id="10.2",
            major_version="10",
            source_file="test.docx",
            title="10.2 Test item",
        )
        section.add_paragraph(1, "Test content", None)
        xml = _build_document_xml([section], empty_patterns)
        assert b"xml version" in xml
        assert b"10.2 Test item" in xml or b"Test content" in xml


class TestCollapseSectionsForVersion:
    def test_single_section_unchanged(self):
        section = Section(
            clause_id="10.2",
            major_version="10",
            source_file="test.docx",
            title="10.2 Test",
            block_indexes=[5],
        )
        result = _collapse_sections_for_version([section])
        assert len(result) == 1
        assert result[0].clause_id == "10.2"

    def test_same_table_sections_merged(self):
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        s1 = Section(
            clause_id="10.2", major_version="10", source_file="t.docx",
            title="10.2 Test", block_indexes=[5],
        )
        s1.table_slices.append(TableSlice(
            table_block_index=5, table_index=1,
            row_start=0, row_end=2, title="10.2 Test",
            rows=[["a"], ["b"]],
            xml=f'<w:tbl xmlns:w="{w}"><w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc></w:tr></w:tbl>',
        ))
        s2 = Section(
            clause_id="10.3", major_version="10", source_file="t.docx",
            title="10.3 Test", block_indexes=[5],
        )
        s2.table_slices.append(TableSlice(
            table_block_index=5, table_index=1,
            row_start=2, row_end=3, title="10.3 Test",
            rows=[["c"]],
            xml=f'<w:tbl xmlns:w="{w}"><w:tr><w:tc><w:p><w:r><w:t>c</w:t></w:r></w:p></w:tc></w:tr></w:tbl>',
        ))
        result = _collapse_sections_for_version([s1, s2])
        assert len(result) == 1
        # merged section should have both row contents
        rows = result[0].table_slices[0].rows
        assert len(rows) == 3


# ═══════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════


class TestExportIntegration:
    def test_creates_output_files(self, tmp_path):
        from tuv_tools.core.splitter.utils import extract_standard_number, safe_name

        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        patterns: list = []
        export_docx_outputs(FIXTURE, sections, output_root, patterns)

        # 输出目录名基于标准号或文件名
        std_num = extract_standard_number(FIXTURE.stem)
        base_name = safe_name(std_num or FIXTURE.stem)

        clause_dir = output_root / base_name / "clauses_docx"
        assert clause_dir.exists()
        clause_files = list(clause_dir.glob("*.docx"))
        assert len(clause_files) == len(sections)

        version_dir = output_root / base_name / "versions_docx"
        assert version_dir.exists()
        version_files = list(version_dir.glob("*.docx"))
        assert len(version_files) > 0

    def test_outputs_are_valid_docx(self, tmp_path):
        import zipfile

        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        patterns: list = []
        export_docx_outputs(FIXTURE, sections, output_root, patterns)

        base_name = safe_name(extract_standard_number(FIXTURE.stem) or FIXTURE.stem)
        clause_dir = output_root / base_name / "clauses_docx"
        for docx_file in clause_dir.glob("*.docx"):
            with zipfile.ZipFile(docx_file) as z:
                assert "word/document.xml" in z.namelist()

    def test_export_emits_clause_and_version_progress(self, tmp_path):
        events = []
        sections = build_sections(FIXTURE)

        export_docx_outputs(FIXTURE, sections, tmp_path / "output", [], progress=events.append)

        phases = [event.phase for event in events]
        assert "exporting_clauses" in phases
        assert "exporting_versions" in phases
        assert phases[-1] == "completed"

    def test_export_callback_error_does_not_break_export(self, tmp_path):
        sections = build_sections(FIXTURE)

        def broken_progress(_event):
            raise RuntimeError("ui callback failed")

        export_docx_outputs(FIXTURE, sections, tmp_path / "output", [], progress=broken_progress)

        assert any((tmp_path / "output").rglob("*.docx"))

    def test_export_cancel_cleans_partial_and_keeps_previous_output(self, tmp_path):
        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        base_name = safe_name(extract_standard_number(FIXTURE.stem) or FIXTURE.stem)
        final_dir = output_root / base_name
        partial_dir = output_root / f"{base_name}.partial-42"

        export_docx_outputs(FIXTURE, sections[:1], output_root, [])
        marker = final_dir / "marker.txt"
        marker.write_text("previous output", encoding="utf-8")

        def should_cancel() -> bool:
            return True

        with pytest.raises(SplitCancelled):
            export_docx_outputs(
                FIXTURE,
                sections,
                output_root,
                [],
                should_cancel=should_cancel,
                staging_root=partial_dir,
            )

        assert marker.read_text(encoding="utf-8") == "previous output"
        assert not partial_dir.exists()

    def test_export_success_promotes_partial_directory(self, tmp_path):
        sections = build_sections(FIXTURE)
        output_root = tmp_path / "output"
        base_name = safe_name(extract_standard_number(FIXTURE.stem) or FIXTURE.stem)
        final_dir = output_root / base_name
        partial_dir = output_root / f"{base_name}.partial-99"

        export_docx_outputs(
            FIXTURE,
            sections[:2],
            output_root,
            [],
            staging_root=partial_dir,
        )

        assert final_dir.exists()
        assert not partial_dir.exists()
        assert any((final_dir / "clauses_docx").glob("*.docx"))


class TestSplitterUiHelpers:
    def test_resolve_output_root_defaults_to_document_directory(self, tmp_path):
        docx_path = tmp_path / "source" / "sample.docx"
        docx_path.parent.mkdir()

        assert resolve_output_root(docx_path, "") == docx_path.parent

    def test_resolve_output_root_prefers_configured_output_root(self, tmp_path):
        docx_path = tmp_path / "source.docx"
        output_root = tmp_path / "output"

        assert resolve_output_root(docx_path, str(output_root)) == output_root

    def test_document_table_filters_word_lock_files(self):
        assert is_importable_docx("sample.docx") is True
        assert is_importable_docx("~$sample.docx") is False
        assert is_importable_docx("sample.doc") is False

    def test_document_table_cancelled_status_label_exists(self):
        assert STATUS_LABELS["cancelled"]

    def test_preparing_status_label_exists(self):
        assert STATUS_LABELS["preparing"] == "⟳ 预处理中"

    def test_selectable_status_helper(self):
        assert is_selectable_document_status("pending") is True
        assert is_selectable_document_status("completed") is True
        assert is_selectable_document_status("preparing") is False
        assert is_selectable_document_status("processing") is False
        assert is_selectable_document_status("prepare_paused") is True
        assert is_selectable_document_status("prepare_failed") is True
