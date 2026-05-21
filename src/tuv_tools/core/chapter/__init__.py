"""条款管理模块"""

from .api import create_chapter, delete_chapters, get_chapters, update_chapter
from .auth import auto_login
from .client import TuvClient
from .models import ApiConfig, Chapter, ChapterStatus, PageResult, STATUS_LABELS

__all__ = [
    "ApiConfig", "Chapter", "ChapterStatus", "PageResult", "STATUS_LABELS",
    "TuvClient", "auto_login",
    "create_chapter", "delete_chapters", "get_chapters", "update_chapter",
]
