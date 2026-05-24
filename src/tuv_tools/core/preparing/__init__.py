"""DOCX 预处理：win32com Word 自动化执行复选框统一替换"""

from __future__ import annotations

import queue

from PySide6.QtCore import QThread, Signal

_STOP = object()  # 哨兵：停止信号


def _win32com_client():
    """懒加载 win32com.client —— 仅在真正需要 Word 自动化时才导入"""
    import win32com.client  # type: ignore[import-untyped]
    return win32com.client


def _prepare_single_doc(doc, app) -> None:
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
        find.Wrap = 0  # wdFindStop
        find.Format = False
        find.Execute(Replace=2)  # wdReplaceAll


def _replace_legacy_formfield_checkboxes(doc) -> None:
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


class PreparingWorker(QThread):
    """后台预处理工作线程：全局唯一 Word 实例，所有文档排队处理

    支持运行时通过 add_items() 追加队列项。
    stop() 发出停止信号（处理完当前文档后退出）。
    """

    doc_prepared = Signal(int)
    doc_error = Signal(int, str)

    _IDLE_TIMEOUT = 30

    def __init__(self):
        super().__init__()
        self._queue: queue.Queue[tuple[int, str] | object] = queue.Queue()

    def add_items(self, items: list[tuple[int, str]]) -> None:
        """追加队列项（线程安全，可在主线程调用）"""
        for item in items:
            self._queue.put(item)

    def _pop_item(self, timeout: float | None = None) -> tuple[int, str] | object | None:
        """从队列取一项。超时返回 None，收到 _STOP 哨兵返回 _STOP"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def stop(self) -> None:
        """发出停止信号，处理完当前文档后退出"""
        self._queue.put(_STOP)

    def run(self) -> None:
        client = _win32com_client()
        app = None
        try:
            app = client.Dispatch("Word.Application")
            app.Visible = False
            app.ScreenUpdating = False

            while True:
                item = self._pop_item(timeout=self._IDLE_TIMEOUT)
                if item is None or item is _STOP:
                    break  # 空闲超时 或 收到停止信号

                doc_id, file_path = item  # type: ignore[misc]
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
