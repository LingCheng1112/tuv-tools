"""数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


@dataclass
class Block:
    """文档中的一个顶层块（段落或表格）"""
    block_type: str  # "paragraph" | "table"
    index: int
    element: ET.Element
    text: str
    table_index: int | None = None


@dataclass
class TableSlice:
    """表格的一个行范围切片"""
    table_block_index: int
    table_index: int
    row_start: int
    row_end: int
    title: str
    rows: list[list[str]]
    xml: str


@dataclass
class ClauseMatch:
    """条款号检测结果"""
    clause_id: str
    major_version: str
    title_hint: str
    secondary_refs: list[str] = field(default_factory=list)


@dataclass
class Section:
    """一个条款对应的文档片段"""
    clause_id: str
    major_version: str
    source_file: str
    title: str
    secondary_refs: list[str] = field(default_factory=list)
    block_indexes: list[int] = field(default_factory=list)
    table_slices: list[TableSlice] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    paragraph_elements: list[ET.Element] = field(default_factory=list)

    def add_paragraph(self, block_index: int, text: str, element: ET.Element | None = None) -> None:
        self.block_indexes.append(block_index)
        if text:
            self.paragraphs.append(text)
        if element is not None:
            self.paragraph_elements.append(element)

    def add_table_slice(self, block_index: int, table_slice: TableSlice) -> None:
        self.block_indexes.append(block_index)
        self.table_slices.append(table_slice)
