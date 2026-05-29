"""DOCX 预处理：复选框统一替换的纯函数。

本模块不依赖 PySide6，可在测试中安全导入。PreparingWorker 见 .worker 子模块。
"""

from __future__ import annotations

import copy
import itertools
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_STOP = object()  # 哨兵：停止信号

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_W = f"{{{_WORD_NS}}}"
_W14 = f"{{{_WORD14_NS}}}"
_NS = {"w": _WORD_NS, "w14": _WORD14_NS}
_CHECKBOX_CHARS = {"☐": False, "☒": True}


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _win32com_client():
    """懒加载 win32com.client - 仅在真正需要 Word 自动化时才导入。"""
    import win32com.client  # type: ignore[import-untyped]

    return win32com.client


def create_isolated_word_application(client):
    """创建隔离的 Word 实例，避免绑定并关闭用户已打开的窗口。"""
    dispatch_ex = getattr(client, "DispatchEx", None)
    if callable(dispatch_ex):
        return dispatch_ex("Word.Application")
    return client.Dispatch("Word.Application")


def prepare_single_doc(doc, app) -> None:
    """对已打开的文档执行复选框替换（不管理 Word 生命周期）。"""
    if doc.ProtectionType != -1:
        doc.Unprotect()

    _replace_plain_checkbox_symbols(doc)
    _replace_legacy_formfield_checkboxes(doc)
    _replace_markers_with_content_controls(doc)

    doc.Save()


def prepare_docx_file(docx_path: str | Path, app) -> None:
    """对单个 DOCX 执行 Word 预处理，并在保存后做 XML 兜底修复。"""
    path = Path(docx_path).expanduser().resolve()
    doc = None
    try:
        doc = app.Documents.Open(str(path))
        prepare_single_doc(doc, app)
    finally:
        if doc is not None:
            try:
                doc.Close()
            except Exception:
                pass
    normalize_plain_checkbox_controls(path)


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


def normalize_plain_checkbox_controls(docx_path: str | Path) -> int:
    """把 DOCX 中仍然是普通字符的 ☐/☒ 转回真正的复选框内容控件。"""
    path = Path(docx_path).expanduser().resolve()
    if not path.exists():
        return 0

    ET.register_namespace("w", _WORD_NS)
    ET.register_namespace("w14", _WORD14_NS)

    with zipfile.ZipFile(path, "r") as src:
        entries = {item.filename: src.read(item.filename) for item in src.infolist()}

    max_checkbox_id = 0
    for payload in entries.values():
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            continue
        for element in root.iter():
            if _local_name(element.tag) != "id":
                continue
            raw_value = element.attrib.get(f"{_W}val") or element.attrib.get("val") or ""
            try:
                max_checkbox_id = max(max_checkbox_id, int(raw_value))
            except (TypeError, ValueError):
                continue

    checkbox_ids = itertools.count(max_checkbox_id + 1)
    changed = False

    for filename, payload in list(entries.items()):
        if not filename.startswith("word/") or not filename.endswith(".xml"):
            continue
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            continue
        if _normalize_plain_checkbox_xml(root, checkbox_ids):
            entries[filename] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            changed = True

    if not changed:
        return 0

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for filename, payload in entries.items():
            dst.writestr(filename, payload)

    return 1


def _normalize_plain_checkbox_xml(root: ET.Element, checkbox_ids) -> bool:
    changed = False

    def clone_run(run: ET.Element, text: str) -> ET.Element:
        new_run = ET.Element(_W + "r")
        rpr = run.find("w:rPr", _NS)
        if rpr is not None:
            new_run.append(copy.deepcopy(rpr))
        text_node = ET.SubElement(new_run, _W + "t")
        if text.startswith(" ") or text.endswith(" "):
            text_node.set(_XML_SPACE, "preserve")
        text_node.text = text
        return new_run

    def build_checkbox(run: ET.Element, is_checked: bool) -> ET.Element:
        sdt = ET.Element(_W + "sdt")
        sdt_pr = ET.SubElement(sdt, _W + "sdtPr")
        rpr = run.find("w:rPr", _NS)
        if rpr is not None:
            sdt_pr.append(copy.deepcopy(rpr))
        ET.SubElement(sdt_pr, _W + "id", {_W + "val": str(next(checkbox_ids))})
        checkbox = ET.SubElement(sdt_pr, _W14 + "checkbox")
        ET.SubElement(checkbox, _W14 + "checked", {_W14 + "val": "1" if is_checked else "0"})
        ET.SubElement(
            checkbox,
            _W14 + "checkedState",
            {_W14 + "val": "2612", _W14 + "font": "MS Gothic"},
        )
        ET.SubElement(
            checkbox,
            _W14 + "uncheckedState",
            {_W14 + "val": "2610", _W14 + "font": "MS Gothic"},
        )
        content = ET.SubElement(sdt, _W + "sdtContent")
        checkbox_run = ET.SubElement(content, _W + "r")
        if rpr is not None:
            checkbox_run.append(copy.deepcopy(rpr))
        text_node = ET.SubElement(checkbox_run, _W + "t")
        text_node.text = "☒" if is_checked else "☐"
        return sdt

    def split_run(run: ET.Element) -> list[ET.Element]:
        text_nodes = [node for node in list(run) if node.tag == _W + "t" and (node.text or "")]
        if not text_nodes:
            return [run]

        plain_text = "".join(node.text or "" for node in text_nodes)
        if not any(ch in _CHECKBOX_CHARS for ch in plain_text):
            return [run]

        parts: list[ET.Element] = []
        buffer: list[str] = []
        for ch in plain_text:
            if ch in _CHECKBOX_CHARS:
                if buffer:
                    parts.append(clone_run(run, "".join(buffer)))
                    buffer = []
                parts.append(build_checkbox(run, _CHECKBOX_CHARS[ch]))
            else:
                buffer.append(ch)
        if buffer:
            parts.append(clone_run(run, "".join(buffer)))
        return parts

    def walk(parent: ET.Element, in_sdt: bool = False) -> bool:
        nonlocal changed
        children = list(parent)
        if not children:
            return False

        rebuilt: list[ET.Element] = []
        local_changed = False
        for child in children:
            local = _local_name(child.tag)
            if local == "sdt":
                if walk(child, True):
                    local_changed = True
                rebuilt.append(child)
                continue
            if not in_sdt and local == "r":
                replacements = split_run(child)
                if len(replacements) != 1 or replacements[0] is not child:
                    local_changed = True
                    rebuilt.extend(replacements)
                    continue
            if walk(child, in_sdt or local == "sdtContent"):
                local_changed = True
            rebuilt.append(child)

        if local_changed:
            parent[:] = rebuilt
            changed = True
        return local_changed

    walk(root)
    return changed
