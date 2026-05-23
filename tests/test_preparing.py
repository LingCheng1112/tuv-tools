"""Tests for preparing module — win32com Word automation for checkbox replacement"""

from unittest.mock import MagicMock, patch
import pytest

from tuv_tools.core.preparing import prepare_document, PreparingWorker


class TestPrepareDocument:
    """Test VBA-to-win32com port correctness"""

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_opens_document_saves_and_quits_word(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_docs = MagicMock()
        mock_app.Documents = mock_docs
        mock_docs.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_win32com.client.Dispatch.assert_called_once_with("Word.Application")
        mock_docs.Open.assert_called_once_with("C:\\docs\\test.docx")
        mock_doc.Save.assert_called_once()
        mock_doc.Close.assert_called_once()
        mock_app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_unprotects_if_document_is_protected(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ProtectionType = 2
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_called_once()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_no_unprotect_when_not_protected(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # wdNoProtection
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        mock_doc.Unprotect.assert_not_called()

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_replaces_plain_text_checkbox_symbols(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        execute_calls = mock_doc.Content.Find.Execute.call_args_list
        assert len(execute_calls) >= 2

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_converts_legacy_formfield_checkboxes(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_ff = MagicMock()
        mock_ff.Type = 71  # wdFieldFormCheckBox
        mock_ff.CheckBox.Value = True
        mock_doc.FormFields.Count = 1
        mock_doc.FormFields.side_effect = lambda i: mock_ff if i == 1 else None
        mock_app.Documents.Open.return_value = mock_doc
        mock_win32com.client.Dispatch.return_value = mock_app

        prepare_document("C:\\docs\\test.docx")

        assert mock_doc.ContentControls.Add.called

    @patch("tuv_tools.core.preparing.win32com", autospec=True)
    def test_quits_word_on_error_to_prevent_zombie_process(self, mock_win32com):
        mock_app = MagicMock()
        mock_doc = MagicMock()
        mock_app.Documents.Open.return_value = mock_doc
        mock_doc.Content.side_effect = RuntimeError("COM failure")
        mock_win32com.client.Dispatch.return_value = mock_app

        with pytest.raises(RuntimeError, match="COM failure"):
            prepare_document("C:\\docs\\test.docx")

        mock_app.Quit.assert_called_once()


class TestPreparingWorker:
    """Test PreparingWorker QThread signal emission"""

    def test_emits_doc_prepared_on_success(self, qtbot):
        with patch("tuv_tools.core.preparing.prepare_document") as mock_prepare:
            worker = PreparingWorker([(1, "C:\\a.docx")])
            results = []

            worker.doc_prepared.connect(lambda did: results.append(did))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert results == [1]
            mock_prepare.assert_called_once_with("C:\\a.docx")

    def test_emits_doc_error_on_failure(self, qtbot):
        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=RuntimeError("Word crash")):
            worker = PreparingWorker([(2, "C:\\bad.docx")])
            errors = []

            worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert len(errors) == 1
            assert errors[0] == (2, "Word crash")

    def test_processes_multiple_items_sequentially(self, qtbot):
        results = []
        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=lambda p: results.append(p)):
            worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert results == ["C:\\a.docx", "C:\\b.docx"]

    def test_continues_after_one_failure(self, qtbot):
        call_count = [0]

        def failing_prepare(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        with patch("tuv_tools.core.preparing.prepare_document",
                   side_effect=failing_prepare):
            worker = PreparingWorker([(1, "C:\\a.docx"), (2, "C:\\b.docx")])
            errors = []
            successes = []
            worker.doc_error.connect(lambda did, msg: errors.append(did))
            worker.doc_prepared.connect(lambda did: successes.append(did))

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

            assert errors == [1]
            assert successes == [2]
