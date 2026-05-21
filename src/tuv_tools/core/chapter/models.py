"""条款数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ChapterStatus(IntEnum):
    """条款状态枚举"""

    DRAFT = 0
    VALID = 1
    INVALID = 2
    IN_REVIEW = 3
    REJECT = 4
    OBSOLETED = 5


STATUS_LABELS: dict[int, str] = {
    ChapterStatus.DRAFT: "草稿",
    ChapterStatus.VALID: "有效",
    ChapterStatus.INVALID: "无效",
    ChapterStatus.IN_REVIEW: "审核中",
    ChapterStatus.REJECT: "驳回",
    ChapterStatus.OBSOLETED: "已废弃",
}


@dataclass
class Chapter:
    """条款数据模型"""

    id: int | None = None
    term: str = ""
    test_content: str = ""
    standard: str = ""
    standard_version: str = ""
    version: int = 0
    status: int = ChapterStatus.DRAFT
    product_type: str = ""
    plan_sr: str = ""
    specific_product: str = ""
    folder_id: int | None = None
    minio_file_url: str = ""
    quote_cnt: int = 0
    draft_by: str = ""
    review_by: str = ""
    review_opinion: str = ""
    create_by: str = ""
    update_by: str = ""
    create_time: str = ""
    update_time: str = ""

    def to_api_dict(self) -> dict[str, Any]:
        """转换为 API 请求所需的 camelCase 字典"""
        d: dict[str, Any] = {
            "term": self.term,
            "testContent": self.test_content,
            "standard": self.standard,
            "standardVersion": self.standard_version,
            "version": self.version,
            "status": self.status,
            "productType": self.product_type,
            "planSr": self.plan_sr,
            "specificProduct": self.specific_product,
            "minioFileUrl": self.minio_file_url,
            "quoteCnt": self.quote_cnt,
            "draftBy": self.draft_by,
            "reviewBy": self.review_by,
            "reviewOpinion": self.review_opinion,
            "createBy": self.create_by,
            "updateBy": self.update_by,
            "createTime": self.create_time,
            "updateTime": self.update_time,
        }
        if self.id is not None:
            d["id"] = self.id
        if self.folder_id is not None:
            d["folder"] = {"id": self.folder_id}
        return d

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> Chapter:
        """从 API 响应字典反序列化"""
        folder = data.get("folder")
        folder_id = folder.get("id") if isinstance(folder, dict) else None

        draft_by_obj = data.get("draftBy")
        draft_by = (
            draft_by_obj.get("username", "")
            if isinstance(draft_by_obj, dict)
            else (draft_by_obj or "")
        )

        review_by_obj = data.get("reviewBy")
        review_by = (
            review_by_obj.get("username", "")
            if isinstance(review_by_obj, dict)
            else (review_by_obj or "")
        )

        return cls(
            id=data.get("id"),
            term=data.get("term", ""),
            test_content=data.get("testContent", ""),
            standard=data.get("standard", ""),
            standard_version=data.get("standardVersion", ""),
            version=data.get("version", 0),
            status=data.get("status", ChapterStatus.DRAFT),
            product_type=data.get("productType", ""),
            plan_sr=data.get("planSr", ""),
            specific_product=data.get("specificProduct", ""),
            folder_id=folder_id,
            minio_file_url=data.get("minioFileUrl", ""),
            quote_cnt=data.get("quoteCnt", 0),
            draft_by=draft_by,
            review_by=review_by,
            review_opinion=data.get("reviewOpinion", ""),
            create_by=data.get("createBy", ""),
            update_by=data.get("updateBy", ""),
            create_time=data.get("createTime", ""),
            update_time=data.get("updateTime", ""),
        )


@dataclass
class PageResult:
    """分页查询结果"""

    content: list[Chapter] = field(default_factory=list)
    total_elements: int = 0

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> PageResult:
        """从 API 分页响应反序列化"""
        content = [
            Chapter.from_api_dict(item) for item in data.get("content", [])
        ]
        total_elements = data.get("totalElements", 0)
        return cls(content=content, total_elements=total_elements)


@dataclass
class FolderNode:
    """目录树节点"""

    id: int = 0
    pid: int | None = None
    folder_name: str = ""
    sub_count: int = 0

    @property
    def has_children(self) -> bool:
        return self.sub_count > 0

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> FolderNode:
        """从 API 响应反序列化"""
        return cls(
            id=data.get("id", 0),
            pid=data.get("pid"),
            folder_name=data.get("folderName", ""),
            sub_count=data.get("subCount", 0),
        )


@dataclass
class ApiConfig:
    """API 连接配置"""

    base_url: str = ""
    username: str = ""
    password: str = ""
    rsa_private_key: str = ""
    token_cache_file: str = ".token_cache"
    token_idle_timeout: int = 1800
    request_timeout: int = 30
