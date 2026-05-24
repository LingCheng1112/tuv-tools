"""Tests for PreparingWorker — PySide6 QThread with queue.Queue

This file imports PySide6. If this single file causes memory issues,
the PySide6 installation may be the root cause, not our code.
"""

from unittest.mock import MagicMock, patch

from tuv_tools.core.preparing.worker import PreparingWorker


def _make_client_mock(mock_wc, mock_psd):
    client = MagicMock()
    app = MagicMock()
    doc = MagicMock()
    app.Documents.Open.return_value = doc
    client.Dispatch.return_value = app
    mock_wc.return_value = client
    return client, app, doc


class TestPreparingWorker:
    """Test PreparingWorker — global singleton Word instance with queue.Queue"""

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_prepared_for_each_success(self, mock_wc, mock_psd):
        _make_client_mock(mock_wc, mock_psd)
        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)
        assert results == [1, 2]
        assert mock_psd.call_count == 2

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_emits_error_on_failure(self, mock_wc, mock_psd):
        _make_client_mock(mock_wc, mock_psd)
        mock_psd.side_effect = RuntimeError("Word crash")
        worker = PreparingWorker()
        errors = []
        worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))
        worker.add_items([(2, "bad.docx")])
        worker.run()
        worker.wait(3000)
        assert len(errors) == 1
        assert errors[0] == (2, "Word crash")

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_one_dispatch_one_quit_for_batch(self, mock_wc, mock_psd):
        client, app, doc = _make_client_mock(mock_wc, mock_psd)
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])
        worker.run()
        worker.wait(3000)
        client.Dispatch.assert_called_once_with("Word.Application")
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_quits_word_on_error(self, mock_wc, mock_psd):
        client, app, doc = _make_client_mock(mock_wc, mock_psd)
        mock_psd.side_effect = RuntimeError("fail")
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx")])
        worker.run()
        worker.wait(3000)
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_continues_after_one_failure(self, mock_wc, mock_psd):
        _make_client_mock(mock_wc, mock_psd)
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

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_add_items_while_running(self, mock_wc, mock_psd):
        _make_client_mock(mock_wc, mock_psd)
        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.add_items([(1, "a.docx")])
        inject_called = [False]

        def inject_more(doc, app):
            if not inject_called[0]:
                inject_called[0] = True
                worker.add_items([(2, "b.docx"), (3, "c.docx")])

        mock_psd.side_effect = inject_more
        worker.run()
        worker.wait(3000)
        assert results == [1, 2, 3]

    @patch("tuv_tools.core.preparing.prepare_single_doc")
    @patch("tuv_tools.core.preparing._win32com_client")
    def test_closes_each_document(self, mock_wc, mock_psd):
        client, app, doc = _make_client_mock(mock_wc, mock_psd)
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx")])
        worker.run()
        worker.wait(3000)
        assert doc.Close.call_count == 2

    def test_stop_sentinel_queued(self):
        worker = PreparingWorker()
        worker.stop()
        assert worker._queue.qsize() == 1
