"""Tests for preparing module — win32com Word automation for checkbox replacement"""

from unittest.mock import MagicMock, patch
import queue

import pytest

from tuv_tools.core.preparing import _prepare_single_doc, PreparingWorker, _STOP


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
    """Test PreparingWorker — global singleton Word instance with queue.Queue"""

    def _make_client_mock(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        doc = MagicMock()
        app.Documents.Open.return_value = doc
        client.Dispatch.return_value = app
        mock_wc.return_value = client
        return client, app, doc

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_prepared_for_each_success(self, mock_wc, mock_psd):
        self._make_client_mock(mock_wc, mock_psd)

        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)

        assert results == [1, 2]
        assert mock_psd.call_count == 2

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_error_on_failure(self, mock_wc, mock_psd):
        self._make_client_mock(mock_wc, mock_psd)
        mock_psd.side_effect = RuntimeError("Word crash")

        worker = PreparingWorker()
        errors = []
        worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))
        worker.add_items([(2, "bad.docx")])
        worker.run()
        worker.wait(3000)

        assert len(errors) == 1
        assert errors[0] == (2, "Word crash")

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_one_dispatch_one_quit_for_batch(self, mock_wc, mock_psd):
        client, app, doc = self._make_client_mock(mock_wc, mock_psd)

        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])
        worker.run()
        worker.wait(3000)

        client.Dispatch.assert_called_once_with("Word.Application")
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_quits_word_on_error(self, mock_wc, mock_psd):
        client, app, doc = self._make_client_mock(mock_wc, mock_psd)
        mock_psd.side_effect = RuntimeError("fail")

        worker = PreparingWorker()
        worker.add_items([(1, "a.docx")])
        worker.run()
        worker.wait(3000)

        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_continues_after_one_failure(self, mock_wc, mock_psd):
        self._make_client_mock(mock_wc, mock_psd)
        call_count = [0]

        def fail_first(doc, app):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        mock_psd.side_effect = fail_first

        worker = PreparingWorker()
        errors = []
        successes = []
        worker.doc_error.connect(lambda did, msg: errors.append(did))
        worker.doc_prepared.connect(lambda did: successes.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)

        assert errors == [1]
        assert successes == [2]

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_add_items_while_running(self, mock_wc, mock_psd):
        """Queue.put() from other thread should be processed within same run()."""
        self._make_client_mock(mock_wc, mock_psd)

        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))

        worker.add_items([(1, "a.docx")])
        # Use a side effect on _prepare_single_doc to inject more items
        # while run() is active, before the queue drains.
        inject_called = [False]

        def inject_more(doc, app):
            if not inject_called[0]:
                inject_called[0] = True
                worker.add_items([(2, "b.docx"), (3, "c.docx")])

        mock_psd.side_effect = inject_more

        worker.run()
        worker.wait(3000)

        assert results == [1, 2, 3]

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_closes_each_document(self, mock_wc, mock_psd):
        client, app, doc = self._make_client_mock(mock_wc, mock_psd)

        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)

        assert doc.Close.call_count == 2

    def test_stop_sentinel_exits_loop(self):
        worker = PreparingWorker()
        worker.queue_size  # touch internal queue to ensure it exists
        worker.stop()
        # _STOP sentinel was put into queue
        # run() would exit on next iteration
        assert worker._queue.qsize() == 1  # _STOP is in queue
