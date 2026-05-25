"""Splitter 相关的纯辅助函数，供 UI 与测试共用。"""

from __future__ import annotations

from pathlib import Path
import re


STATUS_LABELS: dict[str, str] = {
    "pending": "◷ 未处理",
    "completed": "✅ 已拆分",
    "failed": "✗ 失败",
    "prepare_failed": "✗ 预处理失败",
    "processing": "⟳ 处理中",
    "cancelled": "已取消",
    "preparing": "⟳ 预处理中",
    "prepare_paused": "⏸ 预处理已暂停",
}

NON_SELECTABLE_STATUSES = frozenset({"preparing", "processing"})
NON_BATCH_SPLIT_STATUSES = frozenset({"prepare_paused", "prepare_failed"})


def is_importable_docx(file_name: str) -> bool:
    """判断文件名是否为可导入的 DOCX。"""
    return file_name.lower().endswith(".docx") and not file_name.startswith("~$")


def is_selectable_document_status(status: str) -> bool:
    """判断当前状态的文档是否允许被勾选或发起拆分。"""
    return status not in NON_SELECTABLE_STATUSES


def blocks_batch_split(status: str) -> bool:
    """判断当前状态是否应阻止批量拆分。"""
    return status in NON_BATCH_SPLIT_STATUSES


def resolve_output_root(docx_path: Path, output_root: str, output_subdir: str = "") -> Path:
    """根据配置解析导出根目录；未配置时回退到原文档所在目录。"""
    if output_subdir:
        return Path(output_subdir)
    if output_root:
        return Path(output_root)
    return docx_path.parent


def build_split_summary(success: int, failed: int, cancelled: bool, total: int) -> str:
    """构建批量拆分结束后的摘要文案。"""
    if cancelled:
        remaining = max(total - success - failed, 0)
        return f"已取消拆分：完成 {success} 个，剩余 {remaining} 个"
    if success == 0 and failed > 0:
        return f"拆分失败：{failed} 个文档未完成"
    return f"拆分完成：成功 {success} 个，失败 {failed} 个"


def extract_clause_test_content(raw_title: str) -> str:
    """提取与条款面板一致的测试内容展示文本。"""
    text = raw_title or ""

    text = re.sub(r"\(Testing equipment[^)]*\)", "", text)
    text = re.sub(r"\(please specify[^)]*\)", "", text)

    text = re.sub(r"☐\s*(Test date|Ambient temperature|Equipment ID|Sample ID|Equipment No)\s*:?[^\n|]*", "", text)
    text = text.replace("☐", "")

    text = re.sub(r"^[\d.,&\s]+\|?\s*", "", text)
    text = re.sub(r"^Annex\s+[A-Z]{1,2}\s*[,&]?\s*[\d.]*\s*[-–—]\s*", "", text)
    text = re.sub(r"^TABLE:\s*", "", text)

    for part in text.split("|"):
        part = part.strip()
        if part and re.search(r"[A-Za-z]{3,}", part):
            text = part
            break
    else:
        text = ""

    text = re.sub(r"\s+", " ", text).strip(" .:;|-\t")
    if not text or re.match(r"^[\d.,&\s]+$", text):
        return ""
    return text
