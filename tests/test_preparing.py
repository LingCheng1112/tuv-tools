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
    prepare_single_doc,
)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": WORD_NS, "w14": WORD14_NS}


def _make_doc():
    """Create a MagicMock doc that won't infinite-loop in while find.Execute()."""
    doc = MagicMock()
    doc.Content.Find.Execute.return_value = False
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

    def test_noop_when_file_missing(self, tmp_path):
        assert normalize_plain_checkbox_controls(tmp_path / "missing.docx") == 0


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
