"""Splitter 相关的纯辅助函数，供 UI 与测试共用。"""

from __future__ import annotations

from pathlib import Path


STATUS_LABELS: dict[str, str] = {
    "pending": "◷ 未处理",
    "completed": "✅ 已拆分",
    "failed": "✗ 失败",
    "processing": "⟳ 处理中",
    "cancelled": "已取消",
    "preparing": "⟳ 预处理中",
}

NON_SELECTABLE_STATUSES = frozenset({"preparing", "processing"})


def is_importable_docx(file_name: str) -> bool:
    """判断文件名是否为可导入的 DOCX。"""
    return file_name.lower().endswith(".docx") and not file_name.startswith("~$")


def is_selectable_document_status(status: str) -> bool:
    """判断当前状态的文档是否允许被勾选或发起拆分。"""
    return status not in NON_SELECTABLE_STATUSES


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
