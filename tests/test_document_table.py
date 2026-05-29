"""DocumentTable 的轻量 Qt 行为测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox

from tuv_tools.ui.widgets.document_list import DocumentTable


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _doc(doc_id: int, file_path: Path, status: str) -> dict:
    return {
        "id": doc_id,
        "file_path": str(file_path),
        "file_name": file_path.name,
        "standard_number": None,
        "status": status,
        "last_section_count": None,
        "last_split_at": None,
    }


class FakeUrl:
    def __init__(self, path: Path):
        self._path = path

    def toLocalFile(self) -> str:
        return str(self._path)


class FakeMimeData:
    def __init__(self, paths: list[Path]):
        self._urls = [FakeUrl(path) for path in paths]

    def hasUrls(self) -> bool:
        return True

    def urls(self) -> list[FakeUrl]:
        return self._urls


class FakeDropEvent:
    def __init__(self, paths: list[Path]):
        self._mime = FakeMimeData(paths)

    def mimeData(self) -> FakeMimeData:
        return self._mime


class TestDocumentTable:
    def test_checkbox_column_uses_wrapped_centered_checkbox(self, qapp, tmp_path):
        path = tmp_path / "sample.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(1, path, "pending")])

        assert table.columnWidth(table.COL_CHECK) == 44
        assert not isinstance(table.cellWidget(0, table.COL_CHECK), QCheckBox)
        assert isinstance(table._row_checkbox(0), QCheckBox)

    def test_double_click_standard_column_starts_inline_edit(self, qapp, tmp_path, monkeypatch):
        path = tmp_path / "sample.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(1, path, "pending")])
        edited = []
        monkeypatch.setattr(table, "editItem", lambda item: edited.append((item.row(), item.column(), item.text())))

        table._on_double_click(0, table.COL_STANDARD)

        assert edited == [(0, table.COL_STANDARD, "-")]

    def test_edit_standard_item_emits_standard_number_edited(self, qapp, tmp_path):
        path = tmp_path / "sample.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(1, path, "pending")])
        emitted = []
        table.standard_number_edited.connect(lambda doc_id, value: emitted.append((doc_id, value)))

        item = table.item(0, table.COL_STANDARD)
        assert item is not None

        item.setText("60335-2-30")

        assert emitted == [(1, "60335-2-30")]
        assert table._data[0]["standard_number"] == "60335-2-30"
        assert item.toolTip() == "60335-2-30"

    def test_set_all_checked_skips_preparing_and_processing(self, qapp, tmp_path):
        files = []
        for name in ("pending.docx", "preparing.docx", "processing.docx", "completed.docx"):
            path = tmp_path / name
            path.write_text("x", encoding="utf-8")
            files.append(path)

        table = DocumentTable()
        table.load_documents([
            _doc(1, files[0], "pending"),
            _doc(2, files[1], "preparing"),
            _doc(3, files[2], "processing"),
            _doc(4, files[3], "completed"),
        ])

        table.set_all_checked(True)

        assert set(table.checked_ids()) == {1, 4}

    def test_update_row_status_reenables_checkbox_and_clears_selection(self, qapp, tmp_path):
        path = tmp_path / "sample.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(1, path, "pending")])
        table.set_single_checked(1)

        checkbox = table._row_checkbox(0)
        assert isinstance(checkbox, QCheckBox)
        assert checkbox.isEnabled() is True
        assert table.checked_ids() == [1]

        table.update_row_status(1, "processing")

        assert checkbox.isEnabled() is False
        assert checkbox.isChecked() is False
        assert table.checked_ids() == []

        table.update_row_status(1, "pending")

        assert checkbox.isEnabled() is True
        assert checkbox.isChecked() is False

    def test_drop_event_emits_importable_paths(self, qapp, tmp_path):
        direct = tmp_path / "direct.docx"
        direct.write_text("x", encoding="utf-8")

        folder = tmp_path / "folder"
        folder.mkdir()
        nested = folder / "nested.docx"
        nested.write_text("x", encoding="utf-8")
        (folder / "~$lock.docx").write_text("x", encoding="utf-8")
        (folder / "skip.doc").write_text("x", encoding="utf-8")

        table = DocumentTable()
        received: list[list[str]] = []
        table.files_dropped.connect(lambda paths: received.append(paths))

        table.dropEvent(FakeDropEvent([direct, folder]))

        assert received == [[str(direct), str(nested)]]

    def test_prepare_paused_is_selectable_for_batch_delete(self, qapp, tmp_path):
        path = tmp_path / "paused.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(1, path, "prepare_paused")])
        table.set_all_checked(True)

        checkbox = table._row_checkbox(0)
        assert isinstance(checkbox, QCheckBox)
        assert checkbox.isEnabled() is True
        assert table.checked_ids() == [1]

    def test_prepare_paused_context_actions_emit_signals(self, qapp, tmp_path):
        path = tmp_path / "paused.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(7, path, "prepare_paused")])

        resumed = []
        skipped = []
        table.resume_preparing_requested.connect(lambda did: resumed.append(did))
        table.skip_preparing_split_requested.connect(lambda did: skipped.append(did))

        table.resume_preparing_requested.emit(7)
        table.skip_preparing_split_requested.emit(7)

        assert resumed == [7]
        assert skipped == [7]

    def test_prepare_failed_is_selectable_for_batch_delete(self, qapp, tmp_path):
        path = tmp_path / "prepare_failed.docx"
        path.write_text("x", encoding="utf-8")

        table = DocumentTable()
        table.load_documents([_doc(9, path, "prepare_failed")])
        table.set_all_checked(True)

        checkbox = table._row_checkbox(0)
        assert isinstance(checkbox, QCheckBox)
        assert checkbox.isEnabled() is True
        assert table.checked_ids() == [9]
