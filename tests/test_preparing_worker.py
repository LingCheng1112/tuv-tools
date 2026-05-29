"""Tests for PreparingWorker."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from tuv_tools.core.preparing.worker import PreparingWorker


@pytest.fixture(autouse=True)
def _disable_idle_wait():
    """测试里不等待 30 秒空闲超时。"""
    original = PreparingWorker._IDLE_TIMEOUT
    PreparingWorker._IDLE_TIMEOUT = 0
    try:
        yield
    finally:
        PreparingWorker._IDLE_TIMEOUT = original


def _make_client_mock(mock_client_factory):
    client = MagicMock()
    app = MagicMock()
    client.DispatchEx.return_value = app
    client.Dispatch.return_value = app
    mock_client_factory.return_value = client
    return client, app


class TestPreparingWorker:
    """PreparingWorker 行为回归。"""

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_emits_prepared_for_each_success(self, mock_client_factory, mock_prepare):
        _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx")])

        worker.run()

        assert results == [1, 2]
        assert mock_prepare.call_count == 2

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_emits_error_on_failure(self, mock_client_factory, mock_prepare):
        _make_client_mock(mock_client_factory)
        mock_prepare.side_effect = RuntimeError("Word crash")
        worker = PreparingWorker()
        errors = []
        worker.doc_error.connect(lambda did, msg: errors.append((did, msg)))
        worker.add_items([(2, "bad.docx")])

        worker.run()

        assert errors == [(2, "Word crash")]

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_one_dispatch_one_quit_for_batch(self, mock_client_factory, mock_prepare):
        client, app = _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])

        worker.run()

        client.DispatchEx.assert_called_once_with("Word.Application")
        client.Dispatch.assert_not_called()
        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_quits_word_on_error(self, mock_client_factory, mock_prepare):
        _client, app = _make_client_mock(mock_client_factory)
        mock_prepare.side_effect = RuntimeError("fail")
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx")])

        worker.run()

        app.Quit.assert_called_once()

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_continues_after_one_failure(self, mock_client_factory, mock_prepare):
        _make_client_mock(mock_client_factory)
        call_count = [0]

        def fail_first(doc_path, app):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")

        mock_prepare.side_effect = fail_first
        worker = PreparingWorker()
        errors = []
        successes = []
        worker.doc_error.connect(lambda did, msg: errors.append(did))
        worker.doc_prepared.connect(lambda did: successes.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx")])

        worker.run()

        assert errors == [1]
        assert successes == [2]

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_add_items_while_running(self, mock_client_factory, mock_prepare):
        _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        results = []
        worker.doc_prepared.connect(lambda did: results.append(did))
        worker.add_items([(1, "a.docx")])
        inject_called = [False]

        def inject_more(doc_path, app):
            if not inject_called[0]:
                inject_called[0] = True
                worker.add_items([(2, "b.docx"), (3, "c.docx")])

        mock_prepare.side_effect = inject_more

        worker.run()

        assert results == [1, 2, 3]

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_passes_shared_app_to_prepare_helper(self, mock_client_factory, mock_prepare):
        _client, app = _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx"), (2, "b.docx")])

        worker.run()

        assert mock_prepare.call_count == 2
        assert all(call.args[1] is app for call in mock_prepare.call_args_list)

    def test_stop_sentinel_queued(self):
        worker = PreparingWorker()
        worker.stop()
        assert worker._queue.qsize() == 1

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    def test_stop_does_not_process_later_queued_items(self, mock_client_factory, mock_prepare):
        _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        prepared = []
        worker.doc_prepared.connect(lambda did: prepared.append(did))
        worker.add_items([(1, "a.docx"), (2, "b.docx"), (3, "c.docx")])

        call_count = [0]

        def stop_after_first(doc_path, app):
            call_count[0] += 1
            if call_count[0] == 1:
                worker.stop()

        mock_prepare.side_effect = stop_after_first

        worker.run()

        assert prepared == [1]
        assert mock_prepare.call_count == 1

    def test_stop_wakes_idle_worker_without_waiting_full_timeout(self):
        worker = PreparingWorker()
        popped = []

        def target():
            popped.append(worker._pop_item(timeout=60))

        thread = threading.Thread(target=target)
        thread.start()
        worker.stop()
        thread.join(timeout=1)

        assert thread.is_alive() is False
        assert len(popped) == 1
        assert popped[0] is not None

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    @patch("pythoncom.CoUninitialize")
    @patch("pythoncom.CoInitialize")
    def test_initializes_and_uninitializes_com_in_worker_thread(
        self,
        mock_coinit,
        mock_couninit,
        mock_client_factory,
        mock_prepare,
    ):
        _make_client_mock(mock_client_factory)
        worker = PreparingWorker()
        worker.add_items([(1, "a.docx")])

        worker.run()

        mock_coinit.assert_called_once()
        mock_couninit.assert_called_once()

    @patch("tuv_tools.core.preparing.worker.prepare_docx_file")
    @patch("tuv_tools.core.preparing.worker._win32com_client")
    @patch("tuv_tools.core.preparing.worker.Path.resolve")
    def test_normalizes_path_before_prepare_helper(self, mock_resolve, mock_client_factory, mock_prepare):
        _client, app = _make_client_mock(mock_client_factory)
        mock_resolve.return_value = "D:\\Data\\normalized.docx"
        worker = PreparingWorker()
        worker.add_items([(1, "D:\\Data\\raw path.docx")])

        worker.run()

        mock_prepare.assert_called_once_with("D:\\Data\\normalized.docx", app)
