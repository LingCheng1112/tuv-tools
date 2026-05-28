"""测试条款数据模型序列化。"""

from tuv_tools.core.chapter.models import ApiConfig, Chapter, PageResult


class TestChapterSerialization:
    def test_to_api_dict_basic(self):
        ch = Chapter(
            term="10.2",
            test_content="温度测试",
            standard="IEC 60335",
            version=1,
            product_type="家电",
            folder_id=5,
            plan_sr="1.0",
        )
        d = ch.to_api_dict()
        assert d["term"] == "10.2"
        assert d["testContent"] == "温度测试"
        assert d["folder"] == {"id": 5}
        assert d["planSr"] == "1.0"
        assert "id" not in d

    def test_to_api_dict_with_id(self):
        ch = Chapter(
            id=42,
            term="10.3",
            test_content="泄漏",
            standard="IEC 60335",
            folder_id=1,
        )
        d = ch.to_api_dict()
        assert d["id"] == 42

    def test_to_api_dict_no_folder(self):
        ch = Chapter(term="10.2", test_content="test")
        d = ch.to_api_dict()
        assert "folder" not in d

    def test_to_create_api_dict_uses_minimal_payload(self):
        ch = Chapter(
            term="10.2",
            test_content="温度测试",
            standard="IEC 60335",
            standard_version="2020",
            version="1.0",
            product_type="家电",
            specific_product="Model A",
            folder_id=5,
            plan_sr="1.0",
        )

        d = ch.to_create_api_dict()

        assert d == {
            "term": "10.2",
            "testContent": "温度测试",
            "standard": "IEC 60335",
            "standardVersion": "2020",
            "version": "1.0",
            "status": 0,
            "productType": "家电",
            "specificProduct": "Model A",
            "planSr": "1.0",
            "folder": {"id": 5},
        }

    def test_from_api_dict_full(self):
        data = {
            "id": 1,
            "term": "10.2",
            "testContent": "温度测试",
            "standard": "IEC 60335",
            "standardVersion": "6th",
            "version": 2,
            "status": 1,
            "productType": "家电",
            "planSr": "1.5",
            "specificProduct": "电饭煲",
            "folder": {"id": 3, "folderName": "EMC"},
            "minioFileUrl": "http://minio/file.docx",
            "quoteCnt": 2,
            "draftBy": {"username": "tyler"},
            "reviewBy": None,
            "reviewOpinion": None,
            "createBy": "admin",
            "updateBy": "admin",
            "createTime": "2025-01-01",
            "updateTime": "2025-01-02",
        }
        ch = Chapter.from_api_dict(data)
        assert ch.id == 1
        assert ch.test_content == "温度测试"
        assert ch.folder_id == 3
        assert ch.draft_by == "tyler"
        assert ch.review_by == ""
        assert ch.plan_sr == "1.5"
        assert ch.version == 2

    def test_from_api_dict_missing_fields(self):
        ch = Chapter.from_api_dict({"id": 99})
        assert ch.id == 99
        assert ch.term == ""
        assert ch.folder_id is None

    def test_from_api_dict_draft_by_string(self):
        data = {"id": 1, "draftBy": "tyler_str", "reviewBy": "reviewer_str"}
        ch = Chapter.from_api_dict(data)
        assert ch.draft_by == "tyler_str"
        assert ch.review_by == "reviewer_str"

    def test_roundtrip(self):
        original = Chapter(
            id=10,
            term="11.1",
            test_content="能量限制",
            standard="IEC 62368",
            folder_id=7,
            plan_sr="2.0",
        )
        api_dict = original.to_api_dict()
        api_dict["draftBy"] = None
        api_dict["reviewBy"] = None
        api_dict["createBy"] = ""
        api_dict["updateBy"] = ""
        api_dict["createTime"] = ""
        api_dict["updateTime"] = ""
        api_dict["minioFileUrl"] = ""
        api_dict["quoteCnt"] = 0
        api_dict["reviewOpinion"] = None
        restored = Chapter.from_api_dict(api_dict)
        assert restored.term == original.term
        assert restored.folder_id == original.folder_id


class TestPageResult:
    def test_from_api_dict(self):
        data = {
            "content": [
                {"id": 1, "term": "10.2", "testContent": "test"},
                {"id": 2, "term": "10.3", "testContent": "test2"},
            ],
            "totalElements": 42,
        }
        page = PageResult.from_api_dict(data)
        assert page.total_elements == 42
        assert len(page.content) == 2
        assert page.content[0].term == "10.2"

    def test_from_api_dict_empty(self):
        page = PageResult.from_api_dict({"content": [], "totalElements": 0})
        assert page.total_elements == 0
        assert page.content == []


class TestApiConfig:
    def test_ca_certificate_field_defaults_to_empty(self):
        config = ApiConfig()

        assert config.ca_cert_file == ""
