"""DOCX 预处理：复选框统一替换的纯函数

本模块不含 PySide6 依赖，可在测试中安全导入。
PreparingWorker 见 .worker 子模块。
"""

from __future__ import annotations

_STOP = object()  # 哨兵：停止信号


def _win32com_client():
    """懒加载 win32com.client —— 仅在真正需要 Word 自动化时才导入"""
    import win32com.client  # type: ignore[import-untyped]
    return win32com.client


def create_isolated_word_application(client):
    """创建隔离的 Word 实例，避免绑定并关闭用户已打开的窗口。"""
    dispatch_ex = getattr(client, "DispatchEx", None)
    if callable(dispatch_ex):
        return dispatch_ex("Word.Application")
    return client.Dispatch("Word.Application")


def prepare_single_doc(doc, app) -> None:
    """对已打开的文档执行复选框替换（不管理 Word 生命周期）"""
    if doc.ProtectionType != -1:
        doc.Unprotect()

    _replace_plain_checkbox_symbols(doc)
    _replace_legacy_formfield_checkboxes(doc)
    _replace_markers_with_content_controls(doc)

    doc.Save()


def _replace_plain_checkbox_symbols(doc) -> None:
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
        find.Wrap = 0
        find.Format = False
        find.Execute(Replace=2)


def _replace_legacy_formfield_checkboxes(doc) -> None:
    for i in range(doc.FormFields.Count, 0, -1):
        ff = doc.FormFields(i)
        if ff.Type != 71:
            continue
        target_range = ff.Range.Duplicate
        is_checked = ff.CheckBox.Value
        ff.Delete()
        cc = doc.ContentControls.Add(8, target_range)
        cc.Checked = is_checked
        _normalize_checkbox_font(cc)


def _replace_markers_with_content_controls(doc) -> None:
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
        find.Wrap = 0
        find.Format = False

        while find.Execute():
            found_range = rng.Duplicate
            found_range.Delete()
            found_range.Collapse(1)

            try:
                cc = doc.ContentControls.Add(8, found_range)
                cc.Checked = is_checked
                _normalize_checkbox_font(cc)
                rng.SetRange(cc.Range.End, doc.Content.End)
            except Exception:
                found_range.Text = marker_text
                rng.SetRange(found_range.End, doc.Content.End)


def _normalize_checkbox_font(cc) -> None:
    cc.Range.Font.Italic = False
    cc.Range.Font.Bold = False
