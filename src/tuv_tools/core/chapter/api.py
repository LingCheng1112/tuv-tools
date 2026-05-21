"""条款 CRUD API 函数"""

from __future__ import annotations

from .client import TuvClient
from .models import Chapter, FolderNode, PageResult


def get_folders(client: TuvClient, pid: int | None = None, folder_name: str = "") -> list[FolderNode]:
    """查询目录树节点"""
    params: dict = {}
    if pid is not None:
        params["pid"] = pid
    else:
        params["pidIsNull"] = True
    if folder_name:
        params["folderName"] = folder_name
    resp = client.get("/api/folder", params=params)
    data = resp.json()
    items = data.get("content", data) if isinstance(data, dict) else data
    return [FolderNode.from_api_dict(item) for item in items]


def get_chapters(client: TuvClient, page: int = 0, size: int = 20, **filters) -> PageResult:
    """分页查询条款"""
    params: dict = {"page": page, "size": size}
    for key in ("folderId", "term", "testContent", "status", "standard",
                "standardVersion", "specificProduct", "version"):
        snake = _to_snake(key)
        value = filters.get(snake) or filters.get(key)
        if value is not None and value != "":
            params[key] = value
    resp = client.get("/api/chapter", params=params)
    return PageResult.from_api_dict(resp.json())


def create_chapter(client: TuvClient, chapter: Chapter) -> bool:
    """创建条款"""
    resp = client.post("/api/chapter", json=chapter.to_api_dict())
    return 200 <= resp.status_code < 300


def update_chapter(client: TuvClient, chapter: Chapter) -> bool:
    """更新条款"""
    resp = client.put("/api/chapter", json=chapter.to_api_dict())
    return 200 <= resp.status_code < 300


def delete_chapters(client: TuvClient, ids: list[int]) -> bool:
    """批量删除条款"""
    resp = client.delete("/api/chapter", json=ids)
    return 200 <= resp.status_code < 300


def _to_snake(camel: str) -> str:
    """camelCase -> snake_case"""
    result = []
    for ch in camel:
        if ch.isupper():
            result.append("_")
            result.append(ch.lower())
        else:
            result.append(ch)
    return "".join(result)
