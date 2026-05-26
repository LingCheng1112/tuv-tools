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
    response = client.post("/api/chapter", json=chapter.to_create_api_dict())
    data = response.json() if response.content else {}
    if isinstance(data, dict):
        if isinstance(data.get("id"), int):
            return data["id"]
        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("id"), int):
            return data["data"]["id"]
    chapter_id = find_created_draft_chapter_id(client, chapter)
    if chapter_id is not None:
        return chapter_id
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


def find_created_draft_chapter_id(client: TuvClient, chapter: Chapter) -> int | None:
    """当创建接口不返回 ID 时，按精确字段回查刚创建的 draft 条款。"""
    params: dict[str, object] = {
        "page": 0,
        "size": 50,
        "status": int(ChapterStatus.DRAFT),
        "term": chapter.term,
        "testContent": chapter.test_content,
        "version": chapter.version,
    }
    if chapter.folder_id is not None:
        params["folderId"] = chapter.folder_id
    if chapter.standard:
        params["standard"] = chapter.standard
    if chapter.standard_version:
        params["standardVersion"] = chapter.standard_version
    result = PageResult.from_api_dict(client.get("/api/chapter", params=params).json())
    target_version = _normalize_text(chapter.version)
    target_product = _normalize_text(chapter.specific_product)
    matches = [
        item for item in result.content
        if item.term == chapter.term
        and item.test_content == chapter.test_content
        and _normalize_text(item.product_type) == _normalize_text(chapter.product_type)
        and _same_numeric_text(item.plan_sr, chapter.plan_sr)
        and _normalize_text(item.version) == target_version
        and _normalize_text(item.specific_product) == target_product
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.id or 0, reverse=True)
    return matches[0].id


def _normalize_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _same_numeric_text(left: object, right: object) -> bool:
    left_text = _normalize_text(left)
    right_text = _normalize_text(right)
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except (TypeError, ValueError):
        return False
