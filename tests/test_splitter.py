"""测试 Splitter 模块核心逻辑"""

import re
from pathlib import Path

import pytest

from tuv_tools.core.splitter import build_sections, export_docx_outputs
from tuv_tools.core.splitter.constants import ANNEX_HEAD_RE, CLAUSE_HEAD_RE, IGNORED_TABLE_PATTERNS
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
from tuv_tools.ui.views.splitter_view import resolve_output_root
from tuv_tools.ui.widgets.document_list import DocumentTable

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
        assert DocumentTable._is_importable_docx("sample.docx") is True
        assert DocumentTable._is_importable_docx("~$sample.docx") is False
        assert DocumentTable._is_importable_docx("sample.doc") is False
