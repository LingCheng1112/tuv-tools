"""Tests for preparing module — win32com Word automation for checkbox replacement"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Prevent win32com.client from being imported by the preparing module.
# We mock it at sys.modules level before any test imports.
_mock_win32com = MagicMock()
_mock_client = MagicMock()
_mock_win32com.client = _mock_client
sys.modules["win32com"] = _mock_win32com
sys.modules["win32com.client"] = _mock_client


def _make_mock_app():
    mock_doc = MagicMock()
    mock_app = MagicMock()
    mock_app.Documents.Open.return_value = mock_doc
    return mock_app, mock_doc


# Now safe to import — win32com.client is already mocked
from tuv_tools.core.preparing import (  # noqa: E402
    prepare_document,
    _prepare_single_doc,
    PreparingWorker,
)


class TestPrepareDocument:
    """Test standalone prepare_document function"""

    def test_creates_word_instance_opens_and_quits(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        _mock_client.Dispatch.assert_called_once_with("Word.Application")
        mock_app.Documents.Open.assert_called_once_with("C:\\docs\\test.docx")
        mock_doc.Save.assert_called_once()
        mock_doc.Close.assert_called_once()
        mock_app.Quit.assert_called_once()

    def test_unprotects_if_document_is_protected(self):
        mock_app, mock_doc = _make_mock_app()
        mock_doc.ProtectionType = 2
        _mock_client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_called_once()

    def test_no_unprotect_when_not_protected(self):
        mock_app, mock_doc = _make_mock_app()
        mock_doc.ProtectionType = -1
        _mock_client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_not_called()

    def test_runs_find_replace_for_checkbox_symbols(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        execute_calls = mock_doc.Content.Find.Execute.call_args_list
        assert len(execute_calls) >= 2

    def test_converts_legacy_formfield_checkboxes(self):
        mock_app, mock_doc = _make_mock_app()
        mock_ff = MagicMock()
        mock_ff.Type = 71  # wdFieldFormCheckBox
        mock_ff.CheckBox.Value = True
        mock_doc.FormFields.Count = 1
        mock_doc.FormFields.side_effect = lambda i: mock_ff if i == 1 else None
        _mock_client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        assert mock_doc.ContentControls.Add.called

    def test_quits_word_on_error(self):
        mock_app, mock_doc = _make_mock_app()
        mock_doc.Content.side_effect = RuntimeError("COM failure")
        _mock_client.Dispatch.return_value = mock_app

        with pytest.raises(RuntimeError, match="COM failure"):
            prepare_document("C:\\docs\\test.docx")

        mock_app.Quit.assert_called_once()


class TestPrepareSingleDoc:
    """Test _prepare_single_doc which operates on an already-open document"""

    def test_runs_all_replacement_steps(self):
        mock_doc = MagicMock()
        mock_app = MagicMock()

        _prepare_single_doc(mock_doc, mock_app)

        mock_doc.Save.assert_called_once()
        assert mock_doc.Content.Find.Execute.called

    def test_unprotects_protected_document(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = 2
        mock_app = MagicMock()

        _prepare_single_doc(mock_doc, mock_app)

        mock_doc.Unprotect.assert_called_once()

    def test_does_not_unprotect_when_no_protection(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1
        mock_app = MagicMock()

        _prepare_single_doc(mock_doc, mock_app)

        mock_doc.Unprotect.assert_not_called()


class TestPreparingWorker:
    """Test PreparingWorker — shared Word instance across batch"""

    def test_emits_prepared_for_each_success_item(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app

        worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))

        worker.run()
        worker.wait(3000)

        assert results == [1, 2]

    def test_emits_error_on_failure(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app
        # Force _prepare_single_doc to fail
        mock_doc.Content.side_effect = RuntimeError("Word crash")

        worker = PreparingWorker([(2, "C:\\bad.docx")])
        errors = []
        worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))

        worker.run()
        worker.wait(3000)

        assert len(errors) == 1
        assert errors[0][0] == 2
        assert "Word crash" in errors[0][1]

    def test_creates_one_word_instance_for_entire_batch(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app

        worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx"), (3, "C:\\c.docx")])

        worker.run()
        worker.wait(3000)

        _mock_client.Dispatch.assert_called_once_with("Word.Application")
        mock_app.Quit.assert_called_once()
        # 3 documents opened and closed
        assert mock_app.Documents.Open.call_count == 3
        assert mock_doc.Close.call_count == 3

    def test_quits_word_even_on_document_error(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app
        mock_doc.Content.side_effect = RuntimeError("fail")

        worker = PreparingWorker([(1, "C:\\a.docx")])

        worker.run()
        worker.wait(3000)

        mock_app.Quit.assert_called_once()

    def test_continues_after_one_failure(self):
        mock_app, mock_doc = _make_mock_app()
        _mock_client.Dispatch.return_value = mock_app

        # First doc raises, second succeeds
        open_count = [0]

        def failing_open(path):
            open_count[0] += 1
            if open_count[0] == 1:
                bad_doc = MagicMock()
                bad_doc.Content.side_effect = RuntimeError("first fails")
                return bad_doc
            return MagicMock()

        mock_app.Documents.Open.side_effect = failing_open

        worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])
        errors = []
        successes = []
        worker.doc_error.connect(lambda did, msg: errors.append(did))
        worker.doc_prepared.connect(lambda did: successes.append(did))

        worker.run()
        worker.wait(3000)

        assert errors == [1]
        assert successes == [2]
