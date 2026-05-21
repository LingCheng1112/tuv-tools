"""DOCX 测试模板拆分模块"""

from .parsing import build_sections
from .exporting import export_docx_outputs
from .utils import CleanPatterns

__all__ = ["build_sections", "export_docx_outputs", "CleanPatterns"]
