"""PreparingWorker：后台预处理线程（全局唯一 Word 实例，队列化处理）

本模块依赖 PySide6.QtCore，仅 UI 层和对应测试应导入。
"""

from __future__ import annotations

import queue
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import _STOP, _win32com_client, create_isolated_word_application, prepare_single_doc


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
        self._stop_requested = False

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
        """发出停止信号，唤醒空闲等待并在当前文档完成后退出"""
        self._stop_requested = True
        self._queue.put(_STOP)

    def run(self) -> None:
        import pythoncom  # type: ignore[import-untyped]

        pythoncom.CoInitialize()
        client = _win32com_client()
        app = None
        try:
            app = create_isolated_word_application(client)
            app.Visible = False
            app.ScreenUpdating = False

            while True:
                if self._stop_requested:
                    break
                item = self._pop_item(timeout=self._IDLE_TIMEOUT)
                if item is None or item is _STOP:
                    break

                doc_id, file_path = item  # type: ignore[misc]
                doc = None
                try:
                    normalized_path = str(Path(file_path).resolve())
                    doc = app.Documents.Open(normalized_path)
                    prepare_single_doc(doc, app)
                    self.doc_prepared.emit(doc_id)
                except Exception as exc:
                    self.doc_error.emit(doc_id, str(exc))
                finally:
                    if doc is not None:
                        try:
                            doc.Close()
                        except Exception:
                            pass
                if self._stop_requested:
                    break
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()
