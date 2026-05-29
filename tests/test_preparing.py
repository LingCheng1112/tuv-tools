"""Tests for preparing pure functions — no PySide6 dependency"""

from unittest.mock import MagicMock

from tuv_tools.core.preparing import prepare_single_doc, create_isolated_word_application, _STOP


def _make_doc():
    """Create a MagicMock doc that won't infinite-loop in while find.Execute()"""
    doc = MagicMock()
    # _replace_markers_with_content_controls has while find.Execute().
    # MagicMock().Execute() always returns truthy MagicMock → infinite loop.
    # Set return_value=False so while loops exit after one iteration.
    doc.Content.Find.Execute.return_value = False
    return doc


class TestPrepareSingleDoc:
    """Test prepare_single_doc on already-open document"""

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
