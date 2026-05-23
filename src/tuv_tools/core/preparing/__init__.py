"""DOCX 预处理：win32com Word 自动化执行复选框统一替换"""

from __future__ import annotations

import win32com.client  # type: ignore[import-untyped]

from PySide6.QtCore import QThread, Signal


def prepare_document(docx_path: str) -> None:
    """对指定 DOCX 执行复选框统一替换预处理（单文件，每次启动独立 Word 实例）

    批量导入时建议使用 PreparingWorker，它复用同一个 Word 实例。
    """
    app = None
    doc = None
    try:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = False
        app.ScreenUpdating = False

        doc = app.Documents.Open(docx_path)
        if doc.ProtectionType != -1:  # wdNoProtection
            doc.Unprotect()

        _replace_plain_checkbox_symbols(doc)
        _replace_legacy_formfield_checkboxes(doc)
        _replace_markers_with_content_controls(doc)

        doc.Save()
    finally:
        if doc is not None:
            try:
                doc.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass


def _prepare_single_doc(doc, app) -> None:
    """对已打开的文档执行复选框替换（不管理 Word 生命周期）"""
    if doc.ProtectionType != -1:
        doc.Unprotect()

    _replace_plain_checkbox_symbols(doc)
    _replace_legacy_formfield_checkboxes(doc)
    _replace_markers_with_content_controls(doc)

    doc.Save()


def _replace_plain_checkbox_symbols(doc) -> None:
    """Step 1: 将纯文本复选框符号替换为临时标记"""
    symbol_map = [
        (chr(0x2612), "@@CHECKED_BOX@@"),
        (chr(0x2610), "@@UNCHECKED_BOX@@"),
    ]
    for find_text, replace_text in symbol_map:
        rng = doc.Content
        find = rng.Find
        find.ClearFormatting()
        find.Replacement.ClearFormatting()
        find.Text = find_text
        find.Replacement.Text = replace_text
        find.Forward = True
        find.Wrap = 0  # wdFindStop
        find.Format = False
        find.Execute(Replace=2)  # wdReplaceAll


def _replace_legacy_formfield_checkboxes(doc) -> None:
    """Step 2: 将旧式表单域复选框替换为 ContentControl 复选框"""
    for i in range(doc.FormFields.Count, 0, -1):
        ff = doc.FormFields(i)
        if ff.Type != 71:  # wdFieldFormCheckBox
            continue
        target_range = ff.Range.Duplicate
        is_checked = ff.CheckBox.Value
        ff.Delete()
        cc = doc.ContentControls.Add(8, target_range)  # wdContentControlCheckBox
        cc.Checked = is_checked
        _normalize_checkbox_font(cc)


def _replace_markers_with_content_controls(doc) -> None:
    """Step 3: 将临时标记替换为 ContentControl 复选框"""
    markers = [
        ("@@CHECKED_BOX@@", True),
        ("@@UNCHECKED_BOX@@", False),
    ]
    for marker_text, is_checked in markers:
        rng = doc.Content
        find = rng.Find
        find.ClearFormatting()
        find.Text = marker_text
        find.Forward = True
        find.Wrap = 0  # wdFindStop
        find.Format = False

        while find.Execute():
            found_range = rng.Duplicate
            found_range.Delete()
            found_range.Collapse(1)  # wdCollapseStart

            try:
                cc = doc.ContentControls.Add(8, found_range)
                cc.Checked = is_checked
                _normalize_checkbox_font(cc)
                rng.SetRange(cc.Range.End, doc.Content.End)
            except Exception:
                found_range.Text = marker_text
                rng.SetRange(found_range.End, doc.Content.End)


def _normalize_checkbox_font(cc) -> None:
    """Step 4: 清除复选框字体样式"""
    cc.Range.Font.Italic = False
    cc.Range.Font.Bold = False


class PreparingWorker(QThread):
    """后台预处理工作线程：共享一个 Word 实例批量处理文档"""

    doc_prepared = Signal(int)
    doc_error = Signal(int, str)

    def __init__(self, items: list[tuple[int, str]]):
        """items: [(doc_id, file_path), ...]"""
        super().__init__()
        self._items = items

    def run(self) -> None:
        app = None
        try:
            app = win32com.client.Dispatch("Word.Application")
            app.Visible = False
            app.ScreenUpdating = False

            for doc_id, file_path in self._items:
                doc = None
                try:
                    doc = app.Documents.Open(file_path)
                    _prepare_single_doc(doc, app)
                    self.doc_prepared.emit(doc_id)
                except Exception as exc:
                    self.doc_error.emit(doc_id, str(exc))
                finally:
                    if doc is not None:
                        try:
                            doc.Close()
                        except Exception:
                            pass
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
