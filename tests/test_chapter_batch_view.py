"""测试 Chapter 批量导入相关 UI 集成。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from tuv_tools.config.database import DatabaseManager
from tuv_tools.core.chapter_batch.repository import ChapterBatchRepository


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _new_repo():
    tmp = tempfile.mkdtemp()
    db = DatabaseManager(Path(tmp) / "batch-view.db")
    return ChapterBatchRepository(db)


def test_chapter_dialog_uses_folder_selector(qapp):
    from tuv_tools.ui.views.chapter_view import ChapterDialog

    dialog = ChapterDialog(folder_id=123)
    folder_id, folder_name = dialog._folder_selector.selected_folder()

    assert folder_id == 123
    assert folder_name == ""


def test_main_window_registers_chapter_batch_workspace(qapp):
    from tuv_tools.ui.main_window import MainWindow

    window = MainWindow()
    labels = [window._nav.item(i).text() for i in range(window._nav.count())]

    assert "条款批量导入" in labels


def test_workspace_has_import_and_filter_controls(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())

    assert view._import_file_btn.text() == "导入文件"
    assert view._import_dir_btn.text() == "导入文件夹"
    assert view._bulk_confirm_btn.text() == "批量确认"
    assert view._start_btn.text() == "开始执行"
    assert view._status_filter.count() >= 1
    assert view._mode_filter.count() >= 2


def test_choose_import_mode_returns_user_selection(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getItem",
        lambda *args, **kwargs: (SplitMode.SECTION.value, True),
    )

    assert view._choose_import_mode() == SplitMode.SECTION.value


def test_import_selected_paths_splits_documents(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    calls = []
    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)
    monkeypatch.setattr(
        view._service,
        "import_and_split_documents",
        lambda paths, split_mode: calls.append((paths, split_mode)) or [],
    )

    view._import_selected_paths(["C:/docs/a.docx"])

    assert calls == [(["C:/docs/a.docx"], SplitMode.CLAUSE.value)]


def test_checkboxes_update_selected_document_ids_in_list_order(qapp):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    docs = []
    for idx in range(3):
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=f"C:/docs/{idx}.docx",
                file_name=f"{idx}.docx",
                document_status="待确认",
            )
        )
        doc = repo.get_document(doc_id)
        assert doc is not None
        docs.append(doc)

    view._load_documents()

    first = view._table.cellWidget(0, 0)
    third = view._table.cellWidget(2, 0)
    assert isinstance(first, QCheckBox)
    assert isinstance(third, QCheckBox)

    first.setChecked(True)
    third.setChecked(True)

    ordered_ids = [view._documents[0].id, view._documents[2].id]
    assert view._selected_document_ids == ordered_ids


def test_reload_preserves_checked_documents_and_footer_state(qapp):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    first_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/first.docx", file_name="first.docx", document_status="待确认")
    )
    repo.create_document(
        BatchImportDocument(file_path="C:/docs/second.docx", file_name="second.docx", document_status="待确认")
    )

    view._load_documents()
    for row, document in enumerate(view._documents):
        if document.id != first_id:
            continue
        checkbox = view._table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        break

    assert view._selected_document_ids == [first_id]
    assert view._selected_label.text() == "已选 1/2 项"
    assert view._bulk_confirm_btn.isEnabled() is True

    repo.update_document(first_id, product_type="家电")
    view._load_documents()

    assert view._selected_document_ids == [first_id]
    assert view._selected_label.text() == "已选 1/2 项"
    checked_ids = []
    for row, document in enumerate(view._documents):
        checkbox = view._table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        if checkbox.isChecked():
            checked_ids.append(document.id)
    assert checked_ids == [first_id]


def test_double_click_document_opens_drawer(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument

    view = ChapterBatchView(repo=_new_repo())
    view.show()
    qapp.processEvents()
    doc_id = view._repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/sample.docx",
            file_name="sample.docx",
            split_mode="条款",
            document_status="待确认",
        )
    )
    doc = view._repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._table.setRowCount(1)
    view._repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                document_id=doc_id,
                sort_index=0,
                term="10.1",
                test_content="Heating",
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    view._on_table_double_clicked(0, 0)

    assert view._drawer.isVisible() is True
    assert view._drawer._title.text() == "sample.docx"
    assert view._drawer._clause_table.rowCount() == 1
    assert view._drawer._clause_table.item(0, 1).text() == "10.1"


def test_double_click_drawer_uses_opaque_wider_layout(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    view = ChapterBatchView(repo=_new_repo())
    view.resize(1200, 760)
    view.show()
    qapp.processEvents()

    doc_id = view._repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/layout.docx",
            file_name="layout.docx",
            split_mode="条款",
            document_status="待确认",
        )
    )
    doc = view._repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._table.setRowCount(1)

    view._on_table_double_clicked(0, 0)
    qapp.processEvents()

    assert view._drawer.isVisible() is True
    assert view._drawer.width() == view.width()
    assert view._drawer.height() == view.height()
    assert view._drawer._panel.width() >= 560
    assert view._drawer._panel.pos().x() == view.width() - view._drawer._panel.width()
    assert view._drawer.testAttribute(__import__("PySide6.QtCore").QtCore.Qt.WidgetAttribute.WA_StyledBackground)
    assert "#chapterBatchDrawer" in view._drawer.styleSheet()


def test_clicking_left_of_drawer_closes_it(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    view = ChapterBatchView(repo=_new_repo())
    view.resize(1200, 760)
    view.show()
    qapp.processEvents()

    doc_id = view._repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/click-close.docx",
            file_name="click-close.docx",
            split_mode="条款",
            document_status="待确认",
        )
    )
    doc = view._repo.get_document(doc_id)
    assert doc is not None

    view._open_drawer_for_documents([doc])
    qapp.processEvents()
    assert view._drawer.isVisible() is True

    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert view._drawer.eventFilter(view._drawer._dismiss_zone, event) is True
    assert view._drawer.isVisible() is False


def test_drawer_close_button_uses_cross_symbol(qapp):
    from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer

    drawer = ChapterBatchDrawer()

    assert drawer._close_btn.text() == "×"


def test_bulk_confirm_opens_drawer_with_selected_documents_in_table_order(qapp):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()

    first_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/1.docx", file_name="1.docx", document_status="待确认")
    )
    second_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/2.docx", file_name="2.docx", document_status="待确认")
    )
    first = repo.get_document(first_id)
    second = repo.get_document(second_id)
    assert first is not None and second is not None

    view._load_documents()
    first_box = view._table.cellWidget(1, 0)
    second_box = view._table.cellWidget(0, 0)
    assert isinstance(first_box, QCheckBox)
    assert isinstance(second_box, QCheckBox)
    first_box.setChecked(True)
    second_box.setChecked(True)

    view._open_bulk_confirm()

    assert view._drawer.isVisible() is True
    assert view._drawer.current_document() is not None
    assert view._drawer.current_document().id == view._documents[0].id


def test_drawer_exposes_save_and_upload_buttons(qapp):
    from PySide6.QtWidgets import QPushButton
    from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer

    drawer = ChapterBatchDrawer()
    button_texts = [button.text() for button in drawer.findChildren(QPushButton)]

    assert "保存" in button_texts
    assert "上传" in button_texts
    assert "保存确认" not in button_texts


def test_save_confirm_updates_local_document_and_marks_pending_create(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()

    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/confirm.docx",
            file_name="confirm.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._table.setRowCount(1)
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )

    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved.standard == "60335-2-9"
    assert saved.folder_id == 1061


def test_save_confirm_requires_required_fields(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/missing.docx",
            file_name="missing.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    warnings = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CONFIRM.value
    assert warnings


def test_save_confirm_allows_user_to_skip_duplicate_clause(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup.docx",
            file_name="dup.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
            folder_id=7,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 7,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    monkeypatch.setattr(
        view,
        "_existing_rows_for_duplicate_check",
        lambda document_id: [{"folder_id": 7, "term": "10.1", "test_content": "Heating"}],
    )
    monkeypatch.setattr(
        view,
        "_ask_duplicate_decision",
        lambda clause: "skip",
    )
    view._save_documents([doc_id])

    clause = repo.get_clauses(doc_id)[0]
    assert clause.duplicate_flag is True
    assert clause.clause_status == ClauseStatus.SKIPPED.value


def test_save_confirm_updates_clause_edits(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/confirm.docx",
            file_name="confirm.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer._clause_table.item(0, 1).setText("10.2")
    view._drawer._clause_table.item(0, 2).setText("Updated")
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    view._save_documents([doc_id])

    clause = repo.get_clauses(doc_id)[0]
    assert clause.term == "10.2"
    assert clause.test_content == "Updated"


def test_start_selected_documents_uses_current_list_order_and_executable_only(qapp, monkeypatch):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    first_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/1.docx", file_name="1.docx", document_status=DocumentStatus.PENDING_CREATE.value)
    )
    second_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/2.docx", file_name="2.docx", document_status=DocumentStatus.PENDING_CONFIRM.value)
    )
    view._load_documents()
    for row in range(view._table.rowCount()):
        checkbox = view._table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
    started = []
    monkeypatch.setattr(view, "_start_documents", lambda document_ids: started.append(document_ids))

    view._start_selected_documents()

    assert started == [[first_id]]


def test_delete_selected_documents_skips_running_documents(qapp, monkeypatch):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    keep_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/running.docx", file_name="running.docx", document_status=DocumentStatus.CREATING.value)
    )
    delete_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/delete.docx", file_name="delete.docx", document_status=DocumentStatus.PENDING_CONFIRM.value)
    )
    view._load_documents()
    for row in range(view._table.rowCount()):
        checkbox = view._table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes,
    )

    view._delete_selected_documents()

    assert repo.get_document(keep_id) is not None
    assert repo.get_document(delete_id) is None


def test_cancel_execution_requests_worker_cancel(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())

    class Worker:
        def __init__(self):
            self.cancelled = False

        def request_cancel(self):
            self.cancelled = True

    worker = Worker()
    view._execution_worker = worker

    view._cancel_execution()

    assert worker.cancelled is True


def test_resplit_document_changes_single_document_mode(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a.docx",
            file_name="a.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
            split_mode=SplitMode.CLAUSE.value,
        )
    )
    calls = []
    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.SECTION.value)
    monkeypatch.setattr(view._service, "reset_document_for_resplit", lambda did, mode: calls.append(("reset", did, mode)))
    monkeypatch.setattr(view._service, "split_document", lambda did: calls.append(("split", did)))

    view._resplit_document(doc_id)

    assert calls == [("reset", doc_id, SplitMode.SECTION.value), ("split", doc_id)]


def test_save_confirm_slightly_later_keeps_document_not_queued(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()

    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/later.docx",
            file_name="later.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._table.setRowCount(1)
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )

    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.No,
    )

    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved.is_queued is False


def test_upload_requested_starts_checked_clauses(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()

    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/upload.docx",
            file_name="upload.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    view._load_drawer_clauses(doc_id)
    started = []
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    view._on_upload_requested(doc_id, [clause_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert started == [(doc_id, [clause_id])]
    assert saved.is_queued is False


def test_save_documents_keeps_saved_data_without_queue(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/cancel.docx",
            file_name="cancel.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved.standard == "60335-2-9"
    assert saved.is_queued is False


def test_bulk_confirm_opens_first_selected_document(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    view.show()
    qapp.processEvents()

    first_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/a.docx",
            file_name="a.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    second_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/b.docx",
            file_name="b.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    first = repo.get_document(first_id)
    second = repo.get_document(second_id)
    assert first is not None and second is not None

    view._documents = [first, second]
    view._set_selected_document_ids([first_id, second_id])
    view._open_bulk_confirm()

    current = view._drawer.current_document()

    assert current is not None
    assert current.id == first_id


def test_document_form_loads_public_fields(qapp):
    from tuv_tools.ui.widgets.chapter_batch_document_form import ChapterBatchDocumentForm

    form = ChapterBatchDocumentForm()
    form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )

    assert form._standard_edit.text() == "60335-2-9"
    assert form._product_type_edit.text() == "家电"
    assert form._folder_selector.selected_folder() == (1061, "60335-2-9")


def test_bulk_workspace_drawer_shows_auto_filled_folder_and_product_type(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView
    from tuv_tools.core.chapter_batch.models import BatchImportDocument

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/auto.docx",
            file_name="auto.docx",
            standard="60335-2-9",
            folder_id=1061,
            folder_name="60335-2-9",
            product_type="家电",
            document_status="待确认",
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None

    view._open_drawer_for_documents([doc])

    assert view._drawer._document_form._folder_selector.selected_folder() == (1061, "60335-2-9")
    assert view._drawer._document_form._product_type_edit.text() == "家电"


def test_clause_table_loads_term_and_test_content(qapp):
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    table.load_clauses(
        [
            {
                "term": "10.1",
                "test_content": "Heating",
                "clause_status": "待创建",
                "chapter_id": None,
                "duplicate_flag": True,
                "duplicate_reason": "same",
            }
        ]
    )

    assert table.rowCount() == 1
    assert table.item(0, 1).text() == "10.1"
    assert table.item(0, 2).text() == "Heating"
    assert table.columnCount() == 5
    assert table.item(0, 1).data(__import__("PySide6.QtCore").QtCore.Qt.ItemDataRole.UserRole + 2) is True
    assert table.item(0, 1).data(__import__("PySide6.QtCore").QtCore.Qt.ItemDataRole.UserRole + 3) == "same"


def test_splitter_overlay_and_batch_service_share_clause_content_rule():
    from tuv_tools.core.splitter.ui_helpers import extract_clause_test_content

    raw = "10.1 | ☐ Ambient temperature : 23°C | Heating test"

    assert extract_clause_test_content(raw) == "Heating test"


def test_clause_table_shows_non_draft_backend_clause_as_readonly(qapp):
    from PySide6.QtCore import Qt
    from tuv_tools.core.chapter.models import ChapterStatus
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    table.load_clauses(
        [
            {
                "id": 10,
                "term": "10.1",
                "test_content": "Heating",
                "clause_status": ClauseStatus.PENDING_UPLOAD.value,
                "chapter_id": 123,
                "editable": False,
                "readonly_reason": "后端非草稿，禁止编辑",
                "backend_chapter_status": int(ChapterStatus.VALID),
            }
        ]
    )

    assert bool(table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable) is False
    assert bool(table.item(0, 2).flags() & Qt.ItemFlag.ItemIsEditable) is False
    assert table.item(0, 1).data(Qt.ItemDataRole.UserRole + 6) == "后端非草稿，禁止编辑"


def test_running_document_disables_form_and_save_button(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.UPLOADING.value,
            standard="60335-2-9",
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None

    view._open_drawer_for_documents([doc])

    assert view._drawer._save_btn.isEnabled() is False
    assert view._drawer._document_form._standard_edit.isReadOnly() is True


def test_clause_with_unknown_backend_status_is_readonly_in_table(qapp):
    from PySide6.QtCore import Qt
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    table.load_clauses(
        [
            {
                "id": 11,
                "term": "10.2",
                "test_content": "Abnormal",
                "clause_status": ClauseStatus.PENDING_UPLOAD.value,
                "chapter_id": 456,
                "editable": False,
                "readonly_reason": "后端状态未知，禁止编辑",
                "backend_chapter_status": None,
            }
        ]
    )

    assert bool(table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable) is False
    assert bool(table.item(0, 2).flags() & Qt.ItemFlag.ItemIsEditable) is False
    assert table.item(0, 1).data(Qt.ItemDataRole.UserRole + 6) == "后端状态未知，禁止编辑"


def test_clause_table_includes_view_error_action(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert "查看错误信息" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=True)
    assert "查看错误信息" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=False)


def test_clause_table_filters_mutating_actions_when_readonly(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=False) == [
        "打开本地 docx",
        "打开后端 chapter 记录",
        "查看错误信息",
    ]
    assert table.available_actions_for_status(ClauseStatus.SKIPPED.value, editable=False) == [
        "打开本地 docx",
        "查看错误信息",
    ]


def test_on_clause_action_requested_ignores_mutating_action_for_readonly_clause(qapp):
    from tuv_tools.core.chapter.models import ChapterStatus
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/readonly.docx",
            file_name="readonly.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=123,
                backend_chapter_status=int(ChapterStatus.VALID),
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    clause = repo.get_clauses(doc_id)[0]

    view._on_clause_action_requested("重试上传", clause.id)

    updated = repo.get_clause(clause.id)
    assert updated is not None
    assert updated.clause_status == ClauseStatus.UPLOAD_FAILED.value


def test_save_confirm_skips_running_documents_in_bulk(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)

    ready_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/ready.docx",
            file_name="ready.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    running_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.UPLOADING.value,
            standard="locked-standard",
        )
    )
    ready_doc = repo.get_document(ready_id)
    running_doc = repo.get_document(running_id)
    assert ready_doc is not None and running_doc is not None

    view._documents = [ready_doc, running_doc]
    view._drawer.set_documents([ready_doc, running_doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    view._drawer._document_field_cache = {
        ready_id: {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        },
        running_id: {
            "standard": "should-not-save",
            "folder_id": 9999,
            "folder_name": "locked",
            "product_type": "locked",
            "plan_sr": "9",
            "standard_version": "",
            "chapter_version": "9.9",
            "specific_product": "",
        },
    }
    monkeypatch.setattr(view, "_resolve_duplicate_candidates", lambda document_ids: document_ids == [ready_id])

    view._save_documents([ready_id, running_id])

    saved_ready = repo.get_document(ready_id)
    saved_running = repo.get_document(running_id)
    assert saved_ready is not None and saved_running is not None
    assert saved_ready.standard == "60335-2-9"
    assert saved_ready.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved_running.standard == "locked-standard"
    assert saved_running.document_status == DocumentStatus.UPLOADING.value


def test_save_confirm_rechecks_repo_state_for_running_documents(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)

    ready_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/ready.docx",
            file_name="ready.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    running_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
            standard="locked-standard",
        )
    )
    ready_doc = repo.get_document(ready_id)
    running_doc = repo.get_document(running_id)
    assert ready_doc is not None and running_doc is not None

    view._documents = [ready_doc, running_doc]
    view._drawer.set_documents([ready_doc, running_doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    view._drawer._document_field_cache = {
        ready_id: {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        },
        running_id: {
            "standard": "should-not-save",
            "folder_id": 9999,
            "folder_name": "locked",
            "product_type": "locked",
            "plan_sr": "9",
            "standard_version": "",
            "chapter_version": "9.9",
            "specific_product": "",
        },
    }
    repo.update_document(running_id, document_status=DocumentStatus.UPLOADING.value)
    monkeypatch.setattr(view, "_resolve_duplicate_candidates", lambda document_ids: True)

    view._save_documents([ready_id, running_id])

    saved_ready = repo.get_document(ready_id)
    saved_running = repo.get_document(running_id)
    assert saved_ready is not None and saved_running is not None
    assert saved_ready.standard == "60335-2-9"
    assert saved_ready.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved_running.standard == "locked-standard"
    assert saved_running.document_status == DocumentStatus.UPLOADING.value


def test_save_documents_skips_running_document(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None

    view._documents = [doc]
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    repo.update_document(doc_id, document_status=DocumentStatus.UPLOADING.value)
    monkeypatch.setattr(view, "_resolve_duplicate_candidates", lambda document_ids: True)

    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.UPLOADING.value


def test_save_confirm_does_not_apply_stale_clause_cache_after_document_locks(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    target_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/target.docx",
            file_name="target.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    other_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/other.docx",
            file_name="other.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    repo.replace_clauses(
        target_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Original", source_docx_path="C:/out/10_1.docx")],
    )
    target_doc = repo.get_document(target_id)
    other_doc = repo.get_document(other_id)
    assert target_doc is not None and other_doc is not None

    view._documents = [target_doc, other_doc]
    view._drawer.set_documents([target_doc])
    view._load_drawer_clauses(target_id)
    view._drawer._clause_table.item(0, 2).setText("Edited while unlocked")
    view._repo.update_document(target_id, document_status=DocumentStatus.UPLOADING.value)
    view._drawer.set_documents([other_doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    monkeypatch.setattr(view, "_resolve_duplicate_candidates", lambda document_ids: True)

    view._save_documents([other_id])

    clause = repo.get_clauses(target_id)[0]
    assert clause.test_content == "Original"


def test_delete_documents_ignores_running_documents(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    running_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.UPLOADING.value,
        )
    )

    view._delete_documents([running_id])

    assert repo.get_document(running_id) is not None


def test_resplit_document_ignores_running_documents(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    running_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/running.docx",
            file_name="running.docx",
            document_status=DocumentStatus.UPLOADING.value,
            split_mode=SplitMode.CLAUSE.value,
        )
    )
    calls = []
    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.SECTION.value)
    monkeypatch.setattr(view._service, "reset_document_for_resplit", lambda did, mode: calls.append(("reset", did, mode)))
    monkeypatch.setattr(view._service, "split_document", lambda did: calls.append(("split", did)))

    view._resplit_document(running_id)

    assert calls == []
    saved = repo.get_document(running_id)
    assert saved is not None
    assert saved.split_mode == SplitMode.CLAUSE.value
    assert saved.document_status == DocumentStatus.UPLOADING.value


def test_clause_table_exports_edited_rows(qapp):
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    table.load_clauses(
        [
            {
                "id": 10,
                "term": "10.1",
                "test_content": "Heating",
                "clause_status": "待创建",
                "chapter_id": None,
            }
        ]
    )
    table.item(0, 1).setText("10.2")
    table.item(0, 2).setText("Updated")

    assert table.to_clause_updates() == {10: {"term": "10.2", "test_content": "Updated"}}


def test_clause_table_actions_follow_status(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert "重试创建" in table.available_actions_for_status(ClauseStatus.CREATE_FAILED.value)
    assert "重试上传" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value)
    assert "恢复跳过" in table.available_actions_for_status(ClauseStatus.SKIPPED.value)
    assert "打开后端 chapter 记录" in table.available_actions_for_status(ClauseStatus.PENDING_UPLOAD.value)
    assert "上传" in table.available_actions_for_status(ClauseStatus.PENDING_CREATE.value)


def test_clause_local_actions_update_status(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/a.docx", file_name="a.docx", document_status=DocumentStatus.PENDING_CREATE.value)
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.CREATE_FAILED.value, source_docx_path="C:/out/10_1.docx")],
    )
    clause = repo.get_clauses(doc_id)[0]

    view._set_clause_status_for_retry(clause.id, ClauseStatus.CREATE_FAILED.value)

    updated = repo.get_clause(clause.id)
    assert updated is not None
    assert updated.clause_status == ClauseStatus.PENDING_CREATE.value

    view._skip_clause(clause.id)
    skipped = repo.get_clause(clause.id)
    assert skipped is not None
    assert skipped.clause_status == ClauseStatus.SKIPPED.value

    view._restore_clause(clause.id)
    restored = repo.get_clause(clause.id)
    assert restored is not None
    assert restored.clause_status == ClauseStatus.PENDING_CREATE.value


def test_direct_clause_mutation_helpers_ignore_readonly_clause(qapp):
    from tuv_tools.core.chapter.models import ChapterStatus
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/readonly.docx", file_name="readonly.docx", document_status=DocumentStatus.PENDING_UPLOAD.value)
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=123,
                backend_chapter_status=int(ChapterStatus.VALID),
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    clause = repo.get_clauses(doc_id)[0]

    view._set_clause_status_for_retry(clause.id, ClauseStatus.UPLOAD_FAILED.value)
    view._skip_clause(clause.id)
    view._restore_clause(clause.id)

    unchanged = repo.get_clause(clause.id)
    assert unchanged is not None
    assert unchanged.clause_status == ClauseStatus.UPLOAD_FAILED.value


def test_open_backend_chapter_record_reports_id(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(BatchImportDocument(file_path="C:/docs/a.docx", file_name="a.docx"))
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=123,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    clause = repo.get_clauses(doc_id)[0]
    messages = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: messages.append(args),
    )

    view._open_backend_chapter_record(clause.id)

    assert messages
    assert "123" in messages[0][2]


def test_on_save_requested_respects_user_confirmation(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/confirm-cancel.docx",
            file_name="confirm-cancel.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.No,
    )

    view._on_save_requested(doc_id)

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CONFIRM.value


def test_clause_table_supports_check_and_select_all(qapp):
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()
    table.load_clauses(
        [
            {"id": 1, "term": "10.1", "test_content": "Heating", "clause_status": "待创建", "chapter_id": None},
            {"id": 2, "term": "10.2", "test_content": "Abnormal", "clause_status": "待上传", "chapter_id": 22},
        ]
    )

    table.set_checked_clause_ids([2])
    assert table.checked_clause_ids() == [2]

    table.set_all_checked(True)
    assert table.checked_clause_ids() == [1, 2]


def test_clause_upload_action_starts_single_clause_upload(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/single-upload.docx",
            file_name="single-upload.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 1061,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )
    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    started = []
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._on_clause_action_requested("上传", clause_id)

    assert started == [(doc_id, [clause_id])]
