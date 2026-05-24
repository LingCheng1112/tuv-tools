"""Tests for preparing module — win32com Word automation for checkbox replacement"""

from unittest.mock import MagicMock, patch

import pytest

from tuv_tools.core.preparing import _prepare_single_doc, PreparingWorker


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
    """Test PreparingWorker — global singleton Word instance with queue"""

    def _make_worker_and_run(self, items, mock_client_fn=None):
        """Helper: create worker, add items, run to completion, return results."""
        worker = PreparingWorker()
        results = {"prepared": [], "errors": []}
        worker.doc_prepared.connect(lambda did: results["prepared"].append(did))
        worker.doc_error.connect(lambda did, msg: results["errors"].append((did, msg)))
        worker.add_items(items)
        worker.run()
        worker.wait(3000)
        return worker, results

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_prepared_for_each_success(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        doc = MagicMock()
        app.Documents.Open.return_value = doc
        client.Dispatch.return_value = app
        mock_wc.return_value = client

        _, r = self._make_worker_and_run([(1, "a.docx"), (2, "b.docx")])

        assert r["prepared"] == [1, 2]
        assert mock_psd.call_count == 2

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_error_on_failure(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        app.Documents.Open.return_value = MagicMock()
        client.Dispatch.return_value = app
        mock_wc.return_value = client
        mock_psd.side_effect = RuntimeError("Word crash")

        _, r = self._make_worker_and_run([(2, "bad.docx")])

        assert len(r["errors"]) == 1
        assert r["errors"][0] == (2, "Word crash")

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_one_dispatch_one_quit_for_entire_batch(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        app.Documents.Open.return_value = MagicMock()
        client.Dispatch.return_value = app
        mock_wc.return_value = client

        self._make_worker_and_run([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])

        client.Dispatch.assert_called_once_with("Word.Application")
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_quits_word_even_on_error(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        app.Documents.Open.return_value = MagicMock()
        client.Dispatch.return_value = app
        mock_wc.return_value = client
        mock_psd.side_effect = RuntimeError("fail")

        self._make_worker_and_run([(1, "a.docx")])

        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_continues_after_one_failure(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        app.Documents.Open.return_value = MagicMock()
        client.Dispatch.return_value = app
        mock_wc.return_value = client
        call_count = [0]

        def fail_first(doc, app):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        mock_psd.side_effect = fail_first

        _, r = self._make_worker_and_run([(1, "a.docx"), (2, "b.docx")])

        assert r["errors"] == [1]
        assert r["prepared"] == [2]

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_add_items_while_running(self, mock_wc, mock_psd):
        """Items added before run() + during run() via add_items() should all be processed."""
        client = MagicMock()
        app = MagicMock()
        app.Documents.Open.return_value = MagicMock()
        client.Dispatch.return_value = app
        mock_wc.return_value = client

        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))

        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        # Simulate adding more items while running: we hack _pop_item to inject
        # a side effect that adds more after first item is popped
        original_pop = worker._pop_item

        def inject_extra(*args, **kwargs):
            # Replace self to prevent infinite recursion
            if worker.queue_size == 0:
                # After first pop, add more items
                worker.add_items([(3, "c.docx")])
            return original_pop(*args, **kwargs)

        worker._pop_item = inject_extra
        worker.run()
        worker.wait(3000)

        assert results == [1, 2, 3]

    @patch("tuv_tools.core.preparing._prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_closes_each_document(self, mock_wc, mock_psd):
        client = MagicMock()
        app = MagicMock()
        doc = MagicMock()
        app.Documents.Open.return_value = doc
        client.Dispatch.return_value = app
        mock_wc.return_value = client

        self._make_worker_and_run([(1, "a.docx"), (2, "b.docx")])

        assert doc.Close.call_count == 2

    def test_queue_size_after_add(self):
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        assert worker.queue_size == 2
        worker.add_items([(3, "c.docx")])
        assert worker.queue_size == 3
