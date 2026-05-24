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
    assert view._drawer._clause_table.item(0, 0).text() == "10.1"


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
    assert view._drawer._tabs.count() == 2
    assert view._drawer._tabs.item(0).text() == view._documents[0].file_name
    assert view._drawer._tabs.item(1).text() == view._documents[1].file_name


def test_drawer_only_exposes_save_confirm_button(qapp):
    from PySide6.QtWidgets import QPushButton
    from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer

    drawer = ChapterBatchDrawer()
    button_texts = [button.text() for button in drawer.findChildren(QPushButton)]

    assert "保存确认" in button_texts
    assert "直接上传" not in button_texts
    assert "稍后处理" not in button_texts


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

    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.No,
    )

    view._on_save_confirm_requested([doc_id])

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

    view._on_save_confirm_requested([doc_id])

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
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.No,
    )

    view._on_save_confirm_requested([doc_id])

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
    view._drawer._clause_table.item(0, 0).setText("10.2")
    view._drawer._clause_table.item(0, 1).setText("Updated")
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

    view._on_save_confirm_requested([doc_id])

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

    view._on_save_confirm_requested([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_CREATE.value
    assert saved.is_queued is False


def test_bulk_confirm_preserves_fields_per_document_across_tabs(qapp, monkeypatch):
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

    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-9",
            "folder_id": 101,
            "folder_name": "60335-2-9",
            "product_type": "家电",
            "plan_sr": "1",
            "standard_version": "",
            "chapter_version": "1.0",
            "specific_product": "",
        }
    )

    view._drawer._tabs.setCurrentRow(1)
    view._drawer._document_form.load_document(
        {
            "standard": "60335-2-3",
            "folder_id": 202,
            "folder_name": "60335-2-3",
            "product_type": "厨房",
            "plan_sr": "2",
            "standard_version": "",
            "chapter_version": "1.1",
            "specific_product": "",
        }
    )

    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.No,
    )

    view._on_save_confirm_requested([first_id, second_id])

    first_saved = repo.get_document(first_id)
    second_saved = repo.get_document(second_id)
    assert first_saved is not None and second_saved is not None
    assert first_saved.standard == "60335-2-9"
    assert first_saved.folder_id == 101
    assert second_saved.standard == "60335-2-3"
    assert second_saved.folder_id == 202


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
    assert table.item(0, 0).text() == "10.1"
    assert table.item(0, 1).text() == "Heating"
    assert table.item(0, 4).text() == "是"
    assert table.item(0, 5).text() == "same"


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
    table.item(0, 0).setText("10.2")
    table.item(0, 1).setText("Updated")

    assert table.to_clause_updates() == {10: {"term": "10.2", "test_content": "Updated"}}


def test_clause_table_actions_follow_status(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert "重试创建" in table.available_actions_for_status(ClauseStatus.CREATE_FAILED.value)
    assert "重试上传" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value)
    assert "恢复跳过" in table.available_actions_for_status(ClauseStatus.SKIPPED.value)
    assert "打开后端 chapter 记录" in table.available_actions_for_status(ClauseStatus.PENDING_UPLOAD.value)


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
