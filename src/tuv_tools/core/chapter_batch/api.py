"""Chapter 批量导入工作台使用的本地 API 封装。"""

from __future__ import annotations

from pathlib import Path

from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import Chapter, ChapterStatus, PageResult


_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def import_chapter_doc(client: TuvClient, chapter_id: int, file_path: str | Path) -> dict:
    """上传本地 docx 到 chapter-doc/import 接口。"""
    path = Path(file_path)
    with path.open("rb") as file_obj:
        response = client.post(
            "/api/chapter-doc/import",
            files={"file": (path.name, file_obj, _DOCX_MIME_TYPE)},
            params={"chapterId": chapter_id},
        )
    return response.json()


def create_chapter_and_return_id(client: TuvClient, chapter: Chapter) -> int:
    """创建条款并返回后端 ID。

    旧的 create_chapter 只返回 bool；批量导入后续上传 docx 需要 chapterId。
    """
    response = client.post("/api/chapter", json=chapter.to_api_dict())
    data = response.json() if response.content else {}
    if isinstance(data, dict):
        if isinstance(data.get("id"), int):
            return data["id"]
        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("id"), int):
            return data["data"]["id"]
    raise RuntimeError("Create chapter succeeded but response did not include id")


def query_draft_chapters(
    client: TuvClient,
    folder_id: int | None = None,
    standard: str = "",
    standard_version: str = "",
    page: int = 0,
    size: int = 20,
) -> PageResult:
    """查询草稿条款，供后续手动同步流程复用。"""
    params: dict[str, int | str] = {
        "page": page,
        "size": size,
        "status": int(ChapterStatus.DRAFT),
    }
    if folder_id is not None:
        params["folderId"] = folder_id
    if standard:
        params["standard"] = standard
    if standard_version:
        params["standardVersion"] = standard_version
    response = client.get("/api/chapter", params=params)
    return PageResult.from_api_dict(response.json())
