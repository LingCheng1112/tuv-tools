"""Tests for preparing pure functions - no PySide6 dependency."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

from tuv_tools.core.preparing import (
    _STOP,
    create_isolated_word_application,
    normalize_plain_checkbox_controls,
    prepare_docx_file,
    prepare_single_doc,
    repair_docx_markup_compatibility,
)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
MARKUP_COMPATIBILITY_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WP14_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
NS = {"w": WORD_NS, "w14": WORD14_NS}


def _make_doc():
    """Create a MagicMock doc that won't infinite-loop in while find.Execute()."""
    doc = MagicMock()
    doc.ProtectionType = -1
    doc.Content.Find.Execute.return_value = False
    doc.FormFields.Count = 0
    return doc


def _build_test_docx(path: Path) -> None:
    root = ET.Element(f"{{{WORD_NS}}}document")
    body = ET.SubElement(root, f"{{{WORD_NS}}}body")
    para = ET.SubElement(body, f"{{{WORD_NS}}}p")
    run = ET.SubElement(para, f"{{{WORD_NS}}}r")
    text = ET.SubElement(run, f"{{{WORD_NS}}}t")
    text.text = "Result: ☐ PASS ☐FAIL"
    sect_pr = ET.SubElement(body, f"{{{WORD_NS}}}sectPr")
    ET.SubElement(sect_pr, f"{{{WORD_NS}}}pgSz", {f"{{{WORD_NS}}}w": "11906", f"{{{WORD_NS}}}h": "16838"})

    ET.register_namespace("w", WORD_NS)
    ET.register_namespace("w14", WORD14_NS)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml)


def _write_docx(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)


def _build_markup_compatibility_docx(path: Path, *, missing_doc_namespaces: bool) -> None:
    extra_namespaces = ""
    if not missing_doc_namespaces:
        extra_namespaces = (
            f' xmlns:wp14="{WP14_NS}"'
            f' xmlns:w15="{W15_NS}"'
        )
    document_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<w:document xmlns:w="{WORD_NS}" xmlns:w14="{WORD14_NS}" xmlns:mc="{MARKUP_COMPATIBILITY_NS}" mc:Ignorable="w14 wp14 w15"{extra_namespaces}>
  <w:body>
    <w:p>
      <w:r>
        <w:t>Result: ☐ PASS ☐FAIL</w:t>
      </w:r>
    </w:p>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838" />
    </w:sectPr>
  </w:body>
</w:document>
""".encode("utf-8")
    header_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<w:hdr xmlns:w="{WORD_NS}" xmlns:wp14="{WP14_NS}" xmlns:w15="{W15_NS}">
  <w:p />
</w:hdr>
""".encode("utf-8")
    _write_docx(
        path,
        {
            "word/document.xml": document_xml,
            "word/header1.xml": header_xml,
        },
    )


class TestPrepareSingleDoc:
    """Test prepare_single_doc on already-open document."""

    def test_runs_replacement_and_saves(self):
        doc = _make_doc()
        prepare_single_doc(doc, MagicMock())
        doc.Save.assert_called_once()

    def test_unprotects_protected_document(self):
        doc = _make_doc()
        doc.ProtectionType = 2
        prepare_single_doc(doc, MagicMock())
        doc.Unprotect.assert_called_once()

    def test_no_unprotect_when_no_protection(self):
        doc = _make_doc()
        doc.ProtectionType = -1
        prepare_single_doc(doc, MagicMock())
        doc.Unprotect.assert_not_called()

    def test_calls_replace_steps(self):
        doc = _make_doc()
        prepare_single_doc(doc, MagicMock())
        assert doc.Content.Find.Execute.called


class TestNormalizePlainCheckboxControls:
    def test_converts_plain_checkbox_text_to_content_controls(self, tmp_path):
        docx_path = tmp_path / "sample.docx"
        _build_test_docx(docx_path)

        changed = normalize_plain_checkbox_controls(docx_path)

        assert changed == 1
        with zipfile.ZipFile(docx_path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        assert len(root.findall(".//w:sdt", NS)) == 2
        assert len(root.findall(".//w14:checkbox", NS)) == 2
        texts = [node.text or "" for node in root.findall(".//w:t", NS)]
        assert "Result: " in "".join(texts)

    def test_preserves_ignorable_namespace_declarations(self, tmp_path):
        docx_path = tmp_path / "sample.docx"
        _build_markup_compatibility_docx(docx_path, missing_doc_namespaces=False)

        changed = normalize_plain_checkbox_controls(docx_path)

        assert changed == 1
        with zipfile.ZipFile(docx_path) as zf:
            payload = zf.read("word/document.xml")
            root = ET.fromstring(payload)
        assert payload.count(b'xmlns:wp14="') == 1
        assert payload.count(b'xmlns:w15="') == 1
        assert b'Ignorable="w14 wp14 w15"' in payload
        assert len(root.findall(".//w:sdt", NS)) == 2

    def test_noop_when_file_missing(self, tmp_path):
        assert normalize_plain_checkbox_controls(tmp_path / "missing.docx") == 0


class TestRepairDocxMarkupCompatibility:
    def test_adds_missing_ignorable_namespace_declarations(self, tmp_path):
        docx_path = tmp_path / "sample.docx"
        _build_markup_compatibility_docx(docx_path, missing_doc_namespaces=True)

        changed = repair_docx_markup_compatibility(docx_path)

        assert changed == 1
        with zipfile.ZipFile(docx_path) as zf:
            payload = zf.read("word/document.xml")
        assert b'xmlns:wp14="' in payload
        assert b'xmlns:w15="' in payload
        assert b'Ignorable="w14 wp14 w15"' in payload


class TestPrepareDocxFile:
    def test_repairs_docx_before_word_open(self, tmp_path):
        docx_path = tmp_path / "sample.docx"
        _build_markup_compatibility_docx(docx_path, missing_doc_namespaces=True)
        doc = _make_doc()
        opened_payloads: list[bytes] = []

        class _Documents:
            def Open(self, opened_path: str):
                with zipfile.ZipFile(opened_path) as zf:
                    opened_payloads.append(zf.read("word/document.xml"))
                return doc

        app = MagicMock()
        app.Documents = _Documents()

        prepare_docx_file(docx_path, app)

        assert len(opened_payloads) == 1
        assert b'xmlns:wp14="' in opened_payloads[0]
        assert b'xmlns:w15="' in opened_payloads[0]
        doc.Save.assert_called_once()
        doc.Close.assert_called_once()


class TestStopSentinel:
    def test_stop_is_not_none(self):
        assert _STOP is not None

    def test_stop_is_unique_object(self):
        assert _STOP != "stop"  # compare by value, not identity with literal


class TestCreateIsolatedWordApplication:
    def test_prefers_dispatch_ex_when_available(self):
        client = MagicMock()
        app = MagicMock()
        client.DispatchEx.return_value = app

        result = create_isolated_word_application(client)

        assert result is app
        client.DispatchEx.assert_called_once_with("Word.Application")
        client.Dispatch.assert_not_called()

    def test_falls_back_to_dispatch_when_dispatch_ex_missing(self):
        app = MagicMock()
        dispatch = MagicMock(return_value=app)
        client = type("Client", (), {"Dispatch": dispatch})()

        result = create_isolated_word_application(client)

        assert result is app
        dispatch.assert_called_once_with("Word.Application")
