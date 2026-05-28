"""测试 Chapter 批量上传相关 UI 集成。"""

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
from tuv_tools.core.chapter.session import ChapterSessionManager
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


def _connected_session():
    from tuv_tools.core.chapter.session import ChapterConnectionStatus

    session = ChapterSessionManager()
    session._client = object()
    session._set_status(ChapterConnectionStatus.CONNECTED)
    return session


def test_main_window_registers_chapter_batch_workspace(qapp):
    from tuv_tools.ui.main_window import MainWindow
    from tuv_tools.core.chapter.session import ChapterSessionManager

    original_initialize = ChapterSessionManager.initialize_on_startup
    ChapterSessionManager.initialize_on_startup = lambda self: None
    try:
        window = MainWindow()
    finally:
        ChapterSessionManager.initialize_on_startup = original_initialize

    labels = [window._nav.item(i).text() for i in range(window._nav.count())]

    assert "批量上传" in labels
    assert "条款批量上传" not in labels


def test_workspace_has_upload_title_and_actions(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    all_button_texts = [button.text() for button in view.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QPushButton)]

    assert view._title_label.text() == "批量上传"
    assert view._upload_btn.text() == "批量上传"
    assert "查看详情" not in all_button_texts
    assert "批量确认" not in all_button_texts
    assert "开始执行" not in all_button_texts


def test_workspace_shows_filter_labels(qapp):
    from PySide6.QtWidgets import QLabel
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    label_texts = [label.text() for label in view.findChildren(QLabel)]

    assert "状态" in label_texts
    assert "拆分方式" in label_texts


def test_workspace_disables_upload_when_session_not_connected(qapp):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo(), session_manager=ChapterSessionManager())

    assert view._upload_btn.isEnabled() is False
    assert view._backend_hint.isHidden() is False
    assert "设置" in view._backend_hint.text()
    assert view._drawer._document_form._folder_selector._button.isEnabled() is False


def test_workspace_reacts_to_connected_session_state(qapp):
    from tuv_tools.core.chapter.session import ChapterConnectionStatus
    from tuv_tools.core.chapter.session import ChapterSessionManager
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    session = ChapterSessionManager()
    view = ChapterBatchView(repo=_new_repo(), session_manager=session)

    session._client = object()
    session._set_status(ChapterConnectionStatus.CONNECTED)

    assert view._backend_hint.isHidden() is True
    assert view._drawer._document_form._folder_selector._button.isEnabled() is True


def test_choose_import_mode_returns_user_selection(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getItem",
        lambda *args, **kwargs: (SplitMode.SECTION.value, True),
    )

    assert view._choose_import_mode() == SplitMode.SECTION.value


def test_import_selected_paths_imports_then_starts_background_processing(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    calls = []
    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)

    def fake_import_documents(paths, split_mode):
        calls.append((paths, split_mode))
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=paths[0],
                file_name="a.docx",
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard="60335-2-9",
            )
        )
        return [repo.get_document(doc_id)]

    started = []
    monkeypatch.setattr(view._service, "import_documents", fake_import_documents)
    monkeypatch.setattr(view, "_start_processing_documents", lambda document_ids: started.append(document_ids))

    view._import_selected_paths(["C:/docs/a.docx"])

    assert calls == [(["C:/docs/a.docx"], SplitMode.CLAUSE.value)]
    assert started == [[repo.list_documents()[0].id]]


def test_upload_selected_documents_warns_when_backend_not_connected(qapp, monkeypatch):
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo(), session_manager=ChapterSessionManager())
    warnings = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args, **kwargs: warnings.append(args[2]))

    view._upload_selected_documents()

    assert warnings == ["当前未连接后端，相关上传与目录功能不可用。"]


def test_import_selected_paths_shows_processing_document_immediately(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())

    def fake_import_documents(paths, split_mode):
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=paths[0],
                file_name="a.docx",
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard="60335-2-9",
            )
        )
        return [repo.get_document(doc_id)]

    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)
    monkeypatch.setattr(view._service, "import_documents", fake_import_documents)
    monkeypatch.setattr(view, "_start_processing_documents", lambda document_ids: None)

    view._import_selected_paths(["C:/docs/a.docx"])

    assert view._table.rowCount() == 1
    assert view._table.cellWidget(0, view.COL_STATUS) is not None
    assert view._table.item(0, view.COL_STATUS) is None


def test_import_selected_paths_creates_records_before_background_processing(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    started = []

    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)

    def fake_import_documents(paths, split_mode):
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=paths[0],
                file_name="b.docx",
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard="60335-2-9",
            )
        )
        return [repo.get_document(doc_id)]

    monkeypatch.setattr(view._service, "import_documents", fake_import_documents)
    monkeypatch.setattr(view, "_start_processing_documents", lambda document_ids: started.append(document_ids))

    view._import_selected_paths(["C:/docs/b.docx"])

    assert view._table.rowCount() == 1
    assert started == [[repo.list_documents()[0].id]]


def test_import_selected_paths_loads_rows_before_starting_processing(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    started = []

    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)

    def fake_import_documents(paths, split_mode):
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=paths[0],
                file_name="visible-first.docx",
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard="60335-2-9",
            )
        )
        return [repo.get_document(doc_id)]

    monkeypatch.setattr(view._service, "import_documents", fake_import_documents)

    def fake_start_processing(document_ids):
        assert view._table.rowCount() == 1
        started.append(document_ids)

    monkeypatch.setattr(view, "_start_processing_documents", fake_start_processing)

    view._import_selected_paths(["C:/docs/visible-first.docx"])

    assert started == [[repo.list_documents()[0].id]]


def test_import_selected_paths_prompts_for_missing_standard_before_processing(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    monkeypatch.setattr(view, "_choose_import_mode", lambda: SplitMode.CLAUSE.value)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getText",
        lambda *args, **kwargs: ("60335-2-35", True),
    )

    def fake_import_documents(paths, split_mode):
        doc_id = repo.create_document(
            BatchImportDocument(
                file_path=paths[0],
                file_name="unknown.docx",
                document_status=DocumentStatus.PREPARING.value,
                split_mode=split_mode,
                standard="",
            )
        )
        return [repo.get_document(doc_id)]

    started = []
    monkeypatch.setattr(view._service, "import_documents", fake_import_documents)
    monkeypatch.setattr(view, "_start_processing_documents", lambda document_ids: started.append(document_ids))

    view._import_selected_paths(["C:/docs/unknown.docx"])

    saved = repo.list_documents()[0]
    assert saved.standard == "60335-2-35"
    assert started == [[saved.id]]


def test_checkboxes_update_selected_document_ids_in_list_order(qapp):
    from PySide6.QtWidgets import QCheckBox
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    for idx in range(3):
        repo.create_document(
            BatchImportDocument(
                file_path=f"C:/docs/{idx}.docx",
                file_name=f"{idx}.docx",
                document_status=DocumentStatus.PENDING_CONFIRM.value,
            )
        )

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
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    view.show()
    qapp.processEvents()
    doc_id = view._repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/sample.docx",
            file_name="sample.docx",
            split_mode=SplitMode.CLAUSE.value,
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    doc = view._repo.get_document(doc_id)
    assert doc is not None
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
    view._load_documents()

    view._on_table_double_clicked(0, 0)

    assert view._drawer.isVisible() is True
    assert view._drawer._title.text() == "sample.docx"
    assert view._drawer._clause_table.rowCount() == 1
    assert view._drawer._clause_table.item(0, 1).text() == "10.1"


def test_double_click_drawer_uses_opaque_wider_layout(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus, SplitMode
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    view.resize(1200, 760)
    view.show()
    qapp.processEvents()

    doc_id = view._repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/layout.docx",
            file_name="layout.docx",
            split_mode=SplitMode.CLAUSE.value,
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )
    view._load_documents()
    view._on_table_double_clicked(0, 0)
    qapp.processEvents()

    assert view._drawer.isVisible() is True
    assert view._drawer.width() == view.width()
    assert view._drawer.height() == view.height()
    assert view._drawer._panel.width() >= 560
    assert view._drawer._panel.pos().x() == view.width() - view._drawer._panel.width()
    assert view._drawer.testAttribute(__import__("PySide6.QtCore").QtCore.Qt.WidgetAttribute.WA_StyledBackground)
    assert "#chapterBatchDrawer" in view._drawer.styleSheet()


def test_drawer_exposes_save_and_upload_buttons(qapp):
    from PySide6.QtWidgets import QPushButton
    from tuv_tools.ui.widgets.chapter_batch_drawer import ChapterBatchDrawer

    drawer = ChapterBatchDrawer()
    button_texts = [button.text() for button in drawer.findChildren(QPushButton)]

    assert "保存" in button_texts
    assert "上传" in button_texts
    assert "保存确认" not in button_texts


def test_save_documents_keeps_saved_data_without_queue(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/cancel.docx",
            file_name="cancel.docx",
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

    view._save_documents([doc_id])

    saved = repo.get_document(doc_id)
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value
    assert saved.standard == "60335-2-9"
    assert saved.is_queued is False


def test_upload_requested_uses_current_saved_document_without_forced_save(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/upload.docx",
            file_name="upload.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            standard="60335-2-9",
            folder_id=1061,
            folder_name="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    started_upload_ids = []
    save_calls = []
    monkeypatch.setattr(view, "_resolve_upload_duplicates", lambda document_id, clause_ids=None: True)
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started_upload_ids.append((document_id, clause_ids)))
    monkeypatch.setattr(view, "_save_documents", lambda document_ids: save_calls.append(document_ids) or document_ids)

    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    view._on_upload_requested(doc_id, [clause_id])

    assert save_calls == []
    assert started_upload_ids == [(doc_id, [clause_id])]


def test_upload_requested_blocks_when_drawer_has_unsaved_edits(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/upload-dirty.docx",
            file_name="upload-dirty.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            standard="60335-2-9",
            folder_id=1061,
            folder_name="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    view._drawer._document_form._standard_edit.setText("changed")
    warnings = []
    started_upload_ids = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args, **kwargs: warnings.append(args[2]))
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started_upload_ids.append((document_id, clause_ids)))

    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    view._on_upload_requested(doc_id, [clause_id])

    assert started_upload_ids == []
    assert warnings == ["请先保存修改后再上传"]


def test_save_confirm_allows_user_to_skip_duplicate_clause(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup.docx",
            file_name="dup.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=7,
            folder_name="60335-2-9",
            standard="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    monkeypatch.setattr(
        view,
        "_existing_rows_for_duplicate_check",
        lambda _document_id, _clause=None: [{"id": 99, "folder_id": 7, "term": "10.1", "test_content": "Heating", "specific_product": ""}],
    )
    monkeypatch.setattr(view, "_ask_duplicate_decision", lambda document, clause, matched_row: "skip")

    ok = view._resolve_upload_duplicates(doc_id, [repo.get_clauses(doc_id)[0].id])

    clause = repo.get_clauses(doc_id)[0]
    saved = repo.get_document(doc_id)
    assert ok is True
    assert clause.duplicate_flag is True
    assert clause.clause_status == ClauseStatus.PENDING_UPLOAD.value
    assert clause.user_decision == "skip_duplicate"
    assert saved is not None
    assert saved.document_status == DocumentStatus.PENDING_UPLOAD.value


def test_duplicate_skip_restores_original_success_clause_state(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup-success.docx",
            file_name="dup-success.docx",
            document_status=DocumentStatus.COMPLETED.value,
            folder_id=7,
            folder_name="60335-2-9",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=123,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    monkeypatch.setattr(
        view,
        "_existing_rows_for_duplicate_check",
        lambda _document_id, _clause=None: [{"id": 99, "folder_id": 7, "term": "10.1", "test_content": "Heating", "specific_product": ""}],
    )
    monkeypatch.setattr(view, "_ask_duplicate_decision", lambda document, clause, matched_row: "skip")

    ok = view._resolve_upload_duplicates(doc_id, [repo.get_clauses(doc_id)[0].id])

    clause = repo.get_clauses(doc_id)[0]
    saved = repo.get_document(doc_id)
    assert ok is True
    assert clause.clause_status == ClauseStatus.UPLOAD_SUCCESS.value
    assert clause.chapter_id == 123
    assert saved is not None
    assert saved.document_status == DocumentStatus.COMPLETED.value


def test_pending_clause_with_existing_chapter_id_skips_duplicate_lookup(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/existing-chapter.docx",
            file_name="existing-chapter.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=1061,
            folder_name="60335-2-9",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=808,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    monkeypatch.setattr(
        view,
        "_existing_rows_for_duplicate_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not query duplicate rows")),
    )

    ok = view._resolve_upload_duplicates(doc_id, [repo.get_clauses(doc_id)[0].id])

    assert ok is True


def test_reupload_single_clause_skips_duplicate_resolution(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/reupload-skip-dup.docx",
            file_name="reupload-skip-dup.docx",
            document_status=DocumentStatus.COMPLETED.value,
            standard="60335-2-9",
            folder_id=1061,
            folder_name="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=808,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    started = []
    monkeypatch.setattr(view, "_resolve_upload_duplicates", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not check duplicate")))
    monkeypatch.setattr(view, "_ask_reupload_overwrite", lambda document, clause: True)
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._on_clause_action_requested("重新上传", clause_id)

    assert started == [(doc_id, [clause_id])]


def test_reupload_single_clause_uses_success_clause_without_status_fallback(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/reupload-direct.docx",
            file_name="reupload-direct.docx",
            document_status=DocumentStatus.COMPLETED.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=808,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    view._drawer.mark_saved(doc_id)
    monkeypatch.setattr(view, "_ask_reupload_overwrite", lambda document, clause: True)
    started = []
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._reupload_single_clause(repo.get_clauses(doc_id)[0].id)

    assert started == [(doc_id, [repo.get_clauses(doc_id)[0].id])]


def test_reupload_single_clause_cancelled_by_user_does_not_start(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/reupload-cancel.docx",
            file_name="reupload-cancel.docx",
            document_status=DocumentStatus.COMPLETED.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                test_content="Heating",
                clause_status=ClauseStatus.UPLOAD_SUCCESS.value,
                chapter_id=808,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    started = []
    monkeypatch.setattr(view, "_ask_reupload_overwrite", lambda document, clause: False)
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._on_clause_action_requested("重新上传", clause_id)

    assert started == []


def test_ask_duplicate_decision_uses_business_buttons(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    document = BatchImportDocument(folder_name="60335-2-9", specific_product="")
    clause = BatchImportClause(term="10.1", test_content="Heating")
    clicked = {}

    original_exec = QMessageBox.exec
    original_clicked = QMessageBox.clickedButton

    def fake_exec(self):
        buttons = self.buttons()
        clicked["texts"] = [button.text() for button in buttons]
        clicked["button"] = buttons[1]
        return 0

    def fake_clicked_button(self):
        return clicked["button"]

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)

    decision = view._ask_duplicate_decision(document, clause, {"id": 1})

    monkeypatch.setattr(QMessageBox, "exec", original_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", original_clicked)

    assert clicked["texts"] == ["覆盖", "跳过当前条款", "后续重复全部跳过"]
    assert decision == "skip"


def test_duplicate_lookup_queries_backend_by_clause_term_and_test_content(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.core.chapter.models import Chapter, PageResult
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup-query.docx",
            file_name="dup-query.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=1059,
            folder_name="60335-2-9",
            standard="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="7.14", test_content="RUBBING TEST FOR RATING LABEL", source_docx_path="C:/out/7_14.docx")],
    )

    calls = []

    def fake_get_chapters(client, **kwargs):
        calls.append(kwargs)
        return PageResult(
            content=[
                Chapter(
                    id=165,
                    term="7.14",
                    test_content="RUBBING TEST FOR RATING LABEL",
                    folder_id=1059,
                    specific_product="",
                )
            ],
            total_elements=1,
        )

    monkeypatch.setattr("tuv_tools.ui.views.chapter_batch_view.get_chapters", fake_get_chapters)

    clause = repo.get_clauses(doc_id)[0]
    rows = view._existing_rows_for_duplicate_check(doc_id, clause)

    assert len(rows) == 1
    assert rows[0]["id"] == 165
    assert calls == [
        {
            "folder_id": 1059,
            "page": 0,
            "size": 100,
            "term": "7.14",
            "test_content": "RUBBING TEST FOR RATING LABEL",
        }
    ]


def test_duplicate_lookup_queries_backend_with_specific_product_when_present(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.core.chapter.models import PageResult
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup-query-product.docx",
            file_name="dup-query-product.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=1059,
            folder_name="60335-2-9",
            standard="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
            specific_product="Model A",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="7.14", test_content="RUBBING TEST FOR RATING LABEL", source_docx_path="C:/out/7_14.docx")],
    )

    calls = []

    def fake_get_chapters(client, **kwargs):
        calls.append(kwargs)
        return PageResult(content=[], total_elements=0)

    monkeypatch.setattr("tuv_tools.ui.views.chapter_batch_view.get_chapters", fake_get_chapters)

    clause = repo.get_clauses(doc_id)[0]
    rows = view._existing_rows_for_duplicate_check(doc_id, clause)

    assert rows == []
    assert calls == [
        {
            "folder_id": 1059,
            "page": 0,
            "size": 100,
            "term": "7.14",
            "test_content": "RUBBING TEST FOR RATING LABEL",
            "specific_product": "Model A",
        }
    ]


def test_duplicate_lookup_scans_multiple_pages_until_exact_duplicate_found(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.core.chapter.models import Chapter, PageResult
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=_connected_session())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/dup-query-pages.docx",
            file_name="dup-query-pages.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=1059,
            folder_name="60335-2-9",
            standard="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
            specific_product="",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="7.14", test_content="RUBBING TEST FOR RATING LABEL", source_docx_path="C:/out/7_14.docx")],
    )

    calls = []

    def fake_get_chapters(client, **kwargs):
        calls.append(kwargs)
        if kwargs["page"] == 0:
            return PageResult(
                content=[
                    Chapter(
                        id=164,
                        term="7.14",
                        test_content="RUBBING TEST FOR RATING LABEL",
                        folder_id=1059,
                        specific_product="Model A",
                    )
                ],
                total_elements=101,
            )
        return PageResult(
            content=[
                Chapter(
                    id=165,
                    term="7.14",
                    test_content="RUBBING TEST FOR RATING LABEL",
                    folder_id=1059,
                    specific_product="",
                )
            ],
            total_elements=101,
        )

    monkeypatch.setattr("tuv_tools.ui.views.chapter_batch_view.get_chapters", fake_get_chapters)

    clause = repo.get_clauses(doc_id)[0]
    rows = view._existing_rows_for_duplicate_check(doc_id, clause)

    assert [row["id"] for row in rows] == [164, 165]
    assert calls == [
        {
            "folder_id": 1059,
            "page": 0,
            "size": 100,
            "term": "7.14",
            "test_content": "RUBBING TEST FOR RATING LABEL",
        },
        {
            "folder_id": 1059,
            "page": 1,
            "size": 100,
            "term": "7.14",
            "test_content": "RUBBING TEST FOR RATING LABEL",
        },
    ]


def test_duplicate_lookup_returns_empty_when_session_has_no_client(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo, session_manager=ChapterSessionManager())
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/offline-dup.docx",
            file_name="offline-dup.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            folder_id=1059,
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="7.14", test_content="TEST", source_docx_path="C:/out/7_14.docx")],
    )

    clause = repo.get_clauses(doc_id)[0]

    assert view._existing_rows_for_duplicate_check(doc_id, clause) == []


def test_start_documents_passes_connected_client_to_worker(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    session = _connected_session()
    view = ChapterBatchView(repo=repo, session_manager=session)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/upload-worker.docx",
            file_name="upload-worker.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    captured = {}

    class DummyWorker:
        def __init__(self, repo_arg, client_arg, document_ids_arg):
            captured["repo"] = repo_arg
            captured["client"] = client_arg
            captured["document_ids"] = document_ids_arg
            self.progress_changed = type("Sig", (), {"connect": lambda self, fn: None})()
            self.finished_ok = type("Sig", (), {"connect": lambda self, fn: None})()
            self.failed = type("Sig", (), {"connect": lambda self, fn: None})()
            self.finished = type("Sig", (), {"connect": lambda self, fn: None})()

        def start(self):
            captured["started"] = True

    monkeypatch.setattr("tuv_tools.ui.views.chapter_batch_view.ChapterBatchExecutionWorker", DummyWorker)

    view._start_documents([doc_id])

    assert captured["repo"] is repo
    assert captured["client"] is session._client
    assert captured["document_ids"] == [doc_id]
    assert captured["started"] is True


def test_clause_table_includes_view_error_action(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert "查看错误信息" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=True)
    assert "查看错误信息" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=False)


def test_failed_clause_with_chapter_id_prefers_reupload_action(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/reupload-failed.docx",
            file_name="reupload-failed.docx",
            document_status=DocumentStatus.FAILED.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.UPLOAD_FAILED.value,
                chapter_id=808,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    assert view._can_apply_clause_action("重新上传", repo.get_clauses(doc_id)[0].id) is True
    assert view._can_apply_clause_action("上传", repo.get_clauses(doc_id)[0].id) is False


def test_pending_clause_with_chapter_id_can_still_use_upload_action(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/pending-existing.docx",
            file_name="pending-existing.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="10.1",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=809,
                source_docx_path="C:/out/10_1.docx",
            )
        ],
    )

    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    assert view._can_apply_clause_action("上传", clause_id) is True
    assert view._can_apply_clause_action("重新上传", clause_id) is True


def test_clause_table_filters_mutating_actions_when_readonly(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value, editable=False) == [
        "打开本地 docx",
        "打开后端 chapter 记录",
        "查看错误信息",
    ]
    assert table.available_actions_for_status(ClauseStatus.UPLOAD_SUCCESS.value, editable=False) == [
        "打开本地 docx",
        "打开后端 chapter 记录",
    ]


def test_clause_table_actions_follow_status(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    assert "重试上传" in table.available_actions_for_status(ClauseStatus.UPLOAD_FAILED.value)
    assert "重新上传" in table.available_actions_for_status(ClauseStatus.UPLOAD_SUCCESS.value)
    assert "打开后端 chapter 记录" in table.available_actions_for_status(ClauseStatus.PENDING_UPLOAD.value)
    assert "上传" in table.available_actions_for_status(ClauseStatus.PENDING_UPLOAD.value)


def test_clause_table_pending_with_chapter_id_keeps_upload_action(qapp):
    from tuv_tools.core.chapter_batch.models import ClauseStatus
    from tuv_tools.ui.widgets.chapter_batch_clause_table import ChapterBatchClauseTable

    table = ChapterBatchClauseTable()

    actions = table.available_actions_for_status(ClauseStatus.PENDING_UPLOAD.value, chapter_id=123)

    assert "上传" in actions
    assert "重新上传" not in actions


def test_clause_local_actions_update_status(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(file_path="C:/docs/a.docx", file_name="a.docx", document_status=DocumentStatus.PENDING_UPLOAD.value)
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", clause_status=ClauseStatus.UPLOAD_FAILED.value, source_docx_path="C:/out/10_1.docx")],
    )
    clause = repo.get_clauses(doc_id)[0]

    view._set_clause_status_for_retry(clause.id, ClauseStatus.UPLOAD_FAILED.value)

    updated = repo.get_clause(clause.id)
    assert updated is not None
    assert updated.clause_status == ClauseStatus.PENDING_UPLOAD.value


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
    view._restore_clause(clause.id)

    unchanged = repo.get_clause(clause.id)
    assert unchanged is not None
    assert unchanged.clause_status == ClauseStatus.UPLOAD_FAILED.value


def test_stable_status_row_uses_plain_status_item(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/plain.docx",
            file_name="plain.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )

    view._load_documents()

    assert view._table.cellWidget(0, view.COL_STATUS) is None
    assert view._table.item(0, view.COL_STATUS) is not None


def test_running_status_row_uses_centered_status_text_without_percent_label(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, ChapterBatchProgressEvent, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/preparing.docx",
            file_name="preparing.docx",
            document_status=DocumentStatus.PREPARING.value,
        )
    )
    view._progress_by_document_id[doc_id] = ChapterBatchProgressEvent(
        document_id=doc_id,
        phase="processing",
        percent=42,
        message="processing",
    )

    view._load_documents()

    widget = view._table.cellWidget(0, view.COL_STATUS)
    assert widget is not None
    labels = [label for label in widget.findChildren(QLabel) if label.text()]
    assert any(label.text() == view._display_status_text(DocumentStatus.PREPARING.value) for label in labels)
    assert all("%" not in label.text() for label in labels)
    assert any(label.alignment() & Qt.AlignmentFlag.AlignHCenter for label in labels)


def test_build_summary_text_omits_skipped_count(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    document = BatchImportDocument(success_clause_count=2, failed_clause_count=1, skipped_clause_count=3)

    assert ChapterBatchView._build_summary_text(document) == "成功 2 / 失败 1"


def test_pending_confirm_document_displays_as_pending_upload(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/pending-confirm.docx",
            file_name="pending-confirm.docx",
            document_status=DocumentStatus.PENDING_CONFIRM.value,
        )
    )

    view._load_documents()

    assert view._table.item(0, view.COL_STATUS).text() == DocumentStatus.PENDING_UPLOAD.value


def test_drawer_summary_displays_pending_confirm_as_pending_upload(qapp):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    view = ChapterBatchView(repo=_new_repo())
    document = BatchImportDocument(
        file_path="C:/docs/pending-confirm.docx",
        file_name="pending-confirm.docx",
        document_status=DocumentStatus.PENDING_CONFIRM.value,
        split_mode="条款",
    )

    view._drawer.set_documents([document])

    assert "待上传" in view._drawer._summary.text()
    assert "待确认" not in view._drawer._summary.text()


def test_delete_documents_uses_service_cleanup_instead_of_repo_direct_delete(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/delete-me.docx",
            file_name="delete-me.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
        )
    )
    deleted = []
    monkeypatch.setattr(view._service, "delete_documents", lambda ids: deleted.extend(ids) or ids)

    view._delete_documents([doc_id])

    assert deleted == [doc_id]


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


def test_clause_upload_action_starts_single_clause_upload(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/single-upload.docx",
            file_name="single-upload.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            standard="60335-2-9",
            folder_id=1061,
            folder_name="60335-2-9",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [BatchImportClause(sort_index=0, term="10.1", test_content="Heating", source_docx_path="C:/out/10_1.docx")],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    started = []
    monkeypatch.setattr(view, "_resolve_upload_duplicates", lambda document_id, clause_ids=None: True)
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._on_clause_action_requested("上传", clause_id)

    assert started == [(doc_id, [clause_id])]


def test_clause_upload_action_with_existing_chapter_id_starts_single_clause_upload(qapp, monkeypatch):
    from tuv_tools.core.chapter_batch.models import BatchImportClause, BatchImportDocument, ClauseStatus, DocumentStatus
    from tuv_tools.ui.views.chapter_batch_view import ChapterBatchView

    repo = _new_repo()
    view = ChapterBatchView(repo=repo)
    doc_id = repo.create_document(
        BatchImportDocument(
            file_path="C:/docs/single-upload-existing.docx",
            file_name="single-upload-existing.docx",
            document_status=DocumentStatus.PENDING_UPLOAD.value,
            standard="60335-2-35",
            folder_id=1061,
            folder_name="60335-2-35",
            product_type="家电",
            plan_sr="1",
            chapter_version="1.0",
        )
    )
    repo.replace_clauses(
        doc_id,
        [
            BatchImportClause(
                sort_index=0,
                term="11",
                test_content="Heating",
                clause_status=ClauseStatus.PENDING_UPLOAD.value,
                chapter_id=1234,
                source_docx_path="C:/out/11.docx",
            )
        ],
    )
    doc = repo.get_document(doc_id)
    assert doc is not None
    view._drawer.set_documents([doc])
    view._load_drawer_clauses(doc_id)
    view._drawer.mark_saved(doc_id)
    clause_id = repo.get_clauses(doc_id)[0].id
    assert clause_id is not None
    started = []
    monkeypatch.setattr(view, "_resolve_upload_duplicates", lambda document_id, clause_ids=None: True)
    monkeypatch.setattr(view, "_start_clause_upload", lambda document_id, clause_ids: started.append((document_id, clause_ids)))

    view._on_clause_action_requested("上传", clause_id)

    assert started == [(doc_id, [clause_id])]
