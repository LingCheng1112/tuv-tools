"""Tests for preparing pure functions — no PySide6 dependency"""

from unittest.mock import MagicMock

from tuv_tools.core.preparing import prepare_single_doc, _STOP


class TestPrepareSingleDoc:
    """Test prepare_single_doc on already-open document"""

    def test_runs_replacement_and_saves(self):
        mock_doc = MagicMock()
        prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Save.assert_called_once()

    def test_unprotects_protected_document(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = 2
        prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Unprotect.assert_called_once()

    def test_no_unprotect_when_no_protection(self):
        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1
        prepare_single_doc(mock_doc, MagicMock())
        mock_doc.Unprotect.assert_not_called()

    def test_calls_replace_steps(self):
        mock_doc = MagicMock()
        prepare_single_doc(mock_doc, MagicMock())
        # Find.Execute is called during the replacement steps
        assert mock_doc.Content.Find.Execute.called


class TestStopSentinel:
    def test_stop_is_not_none(self):
        assert _STOP is not None

    def test_stop_is_unique_object(self):
        assert _STOP is not "stop"
