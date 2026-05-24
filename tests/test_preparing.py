"""Tests for preparing module — win32com Word automation for checkbox replacement"""

from unittest.mock import MagicMock, patch

import pytest

from tuv_tools.core.preparing import (
    prepare_document,
    _prepare_single_doc,
    PreparingWorker,
)


def _mock_client():
    """Create mock simulating _win32com_client() return value."""
    client = MagicMock()
    mock_app = MagicMock()
    mock_doc = MagicMock()
    mock_app.Documents.Open.return_value = mock_doc
    client.Dispatch.return_value = mock_app
    return client, mock_app, mock_doc


class TestPrepareDocument:
    """Test standalone prepare_document"""

    @patch("tuv_tools.core.preparing._win32com_client")
    def test_creates_word_instance_opens_and_quits(self, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client

        prepare_document("C:\\docs\\test.docx")

        client.Dispatch.assert_called_once_with("Word.Application")
        app.Documents.Open.assert_called_once_with("C:\\docs\\test.docx")
        doc.Save.assert_called_once()
        doc.Close.assert_called_once()
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._win32com_client")
    def test_quits_word_on_error(self, mock_wc):
        client, app, doc = _mock_client()
        doc.Content.side_effect = RuntimeError("COM failure")
        mock_wc.return_value = client

        with pytest.raises(RuntimeError, match="COM failure"):
            prepare_document("C:\\docs\\test.docx")

        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._win32com_client")
    def test_unprotects_if_protected(self, mock_wc):
        client, app, doc = _mock_client()
        doc.ProtectionType = 2
        mock_wc.return_value = client

        prepare_document("C:\\docs\\test.docx")

        doc.Unprotect.assert_called_once()

    @patch("tuv_tools.core.preparing._win32com_client")
    def test_no_unprotect_when_not_protected(self, mock_wc):
        client, app, doc = _mock_client()
        doc.ProtectionType = -1
        mock_wc.return_value = client

        prepare_document("C:\\docs\\test.docx")

        doc.Unprotect.assert_not_called()


class TestPrepareSingleDoc:
    """Test _prepare_single_doc on already-open document"""

    def test_runs_replacement_and_saves(self):
        mock_doc = MagicMock()
        _prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Save.assert_called_once()

    def test_unprotects_protected_document(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = 2
        _prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Unprotect.assert_called_once()

    def test_no_unprotect_when_no_protection(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1
        _prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Unprotect.assert_not_called()


class TestPreparingWorker:
    """Test PreparingWorker — shared Word instance per batch"""

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_emits_prepared_for_each_success(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client

        worker = PreparingWorker([(1, "a.docx"), (2, "b.docx")])
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.run()
        worker.wait(3000)

        assert results == [1, 2]
        assert mock_psd.call_count == 2

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_emits_error_on_failure(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client
        mock_psd.side_effect = RuntimeError("Word crash")

        worker = PreparingWorker([(2, "bad.docx")])
        errors = []
        worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))
        worker.run()
        worker.wait(3000)

        assert len(errors) == 1
        assert errors[0] == (2, "Word crash")

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_creates_one_word_instance_for_entire_batch(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client

        worker = PreparingWorker([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])
        worker.run()
        worker.wait(3000)

        client.Dispatch.assert_called_once_with("Word.Application")
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_quits_word_even_on_error(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client
        mock_psd.side_effect = RuntimeError("fail")

        worker = PreparingWorker([(1, "a.docx")])
        worker.run()
        worker.wait(3000)

        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_continues_after_one_failure(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client

        call_count = [0]

        def fail_first(doc, app):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        mock_psd.side_effect = fail_first

        worker = PreparingWorker([(1, "a.docx"), (2, "b.docx")])
        errors = []
        successes = []
        worker.doc_error.connect(lambda did, msg: errors.append(did))
        worker.doc_prepared.connect(lambda did: successes.append(did))
        worker.run()
        worker.wait(3000)

        assert errors == [1]
        assert successes == [2]

    @patch("tuv_tools.core.preparing._win32com_client")
    @patch("tuv_tools.core.preparing._prepare_single_doc")
    def test_closes_each_document(self, mock_psd, mock_wc):
        client, app, doc = _mock_client()
        mock_wc.return_value = client

        worker = PreparingWorker([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)

        assert doc.Close.call_count == 2
