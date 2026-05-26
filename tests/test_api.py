"""测试条款 API 函数"""

from pathlib import Path
import sys
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tuv_tools.core.chapter.api import (
    create_chapter,
    delete_chapters,
    get_chapters,
    update_chapter,
)
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import Chapter
from tuv_tools.core.chapter_batch.api import (
    create_chapter_and_return_id,
    find_created_draft_chapter_id,
    import_chapter_doc,
    query_draft_chapters,
)


def _mock_client():
    return MagicMock(spec=TuvClient)


class TestGetChapters:
    def test_basic_query(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "content": [{"id": 1, "term": "10.2", "testContent": "test"}],
            "totalElements": 1,
        }
        result = get_chapters(client, page=0, size=20)
        assert result.total_elements == 1
        assert result.content[0].term == "10.2"
        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert call_kwargs[0][0] == "/api/chapter"
        params = call_kwargs[1]["params"]
        assert params["page"] == 0
        assert params["size"] == 20

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"content": [], "totalElements": 0}
        get_chapters(client, page=1, size=10, term="10.2", status=0)
        params = client.get.call_args[1]["params"]
        assert params["term"] == "10.2"
        assert params["status"] == 0
        assert "specificProduct" not in params


class TestCreateChapter:
    def test_success(self):
        client = _mock_client()
        client.post.return_value.status_code = 201
        ch = Chapter(term="10.2", test_content="温度", standard="IEC 60335", folder_id=1)
        result = create_chapter(client, ch)
        assert result is True
        body = client.post.call_args[1]["json"]
        assert body["term"] == "10.2"
        assert body["folder"] == {"id": 1}


class TestCreateChapterAndReturnId:
    def test_reads_direct_id(self):
        client = _mock_client()
        client.post.return_value.content = b'{"id":456}'
        client.post.return_value.json.return_value = {"id": 456}

        chapter_id = create_chapter_and_return_id(client, Chapter(term="10.1"))

        assert chapter_id == 456
        client.post.assert_called_once()
        assert client.post.call_args[0][0] == "/api/chapter"

    def test_reads_data_wrapper_id(self):
        client = _mock_client()
        client.post.return_value.content = b'{"data":{"id":789}}'
        client.post.return_value.json.return_value = {"data": {"id": 789}}

        chapter_id = create_chapter_and_return_id(client, Chapter(term="10.2"))

        assert chapter_id == 789

    def test_missing_id_falls_back_to_query_once(self):
        client = _mock_client()
        client.post.return_value.content = b"{}"
        client.post.return_value.json.return_value = {}
        client.post.return_value.status_code = 201
        client.get.return_value.json.return_value = {
            "content": [
                {
                    "id": 321,
                    "term": "10.3",
                    "testContent": "Leakage",
                    "status": 0,
                    "productType": "家电",
                    "planSr": "1",
                    "standard": "IEC 60335",
                    "standardVersion": "2020",
                    "specificProduct": "Model A",
                    "version": "1.0",
                    "folder": {"id": 7},
                }
            ],
            "totalElements": 1,
        }

        chapter = Chapter(
            term="10.3",
            test_content="Leakage",
            product_type="家电",
            plan_sr="1",
            standard="IEC 60335",
            standard_version="2020",
            specific_product="Model A",
            version="1.0",
            folder_id=7,
        )

        chapter_id = create_chapter_and_return_id(client, chapter)

        assert chapter_id == 321
        client.post.assert_called_once()
        client.get.assert_called_once()
        body = client.post.call_args[1]["json"]
        assert body == {
            "term": "10.3",
            "testContent": "Leakage",
            "productType": "家电",
            "planSr": "1",
            "standard": "IEC 60335",
            "version": "1.0",
            "status": 0,
            "standardVersion": "2020",
            "specificProduct": "Model A",
            "folder": {"id": 7},
        }

    def test_missing_id_raises_when_query_finds_nothing(self):
        client = _mock_client()
        client.post.return_value.content = b"{}"
        client.post.return_value.json.return_value = {}
        client.post.return_value.status_code = 201
        client.get.return_value.json.return_value = {"content": [], "totalElements": 0}

        try:
            create_chapter_and_return_id(client, Chapter(term="10.3"))
        except RuntimeError as exc:
            assert "did not include id" in str(exc)
        else:
            raise AssertionError("missing id should raise")

        client.post.assert_called_once()
        client.get.assert_called_once()


class TestFindCreatedDraftChapterId:
    def test_matches_latest_exact_draft_row(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "content": [
                {
                    "id": 101,
                    "term": "10.1",
                    "testContent": "Heating",
                    "status": 0,
                    "productType": "家电",
                    "planSr": "1",
                    "standard": "IEC 60335",
                    "standardVersion": "2020",
                    "specificProduct": "",
                    "version": "1.0",
                    "folder": {"id": 5},
                },
                {
                    "id": 102,
                    "term": "10.1",
                    "testContent": "Heating",
                    "status": 0,
                    "productType": "家电",
                    "planSr": "1",
                    "standard": "IEC 60335",
                    "standardVersion": "2020",
                    "specificProduct": "",
                    "version": "1.0",
                    "folder": {"id": 5},
                },
            ],
            "totalElements": 2,
        }

        chapter_id = find_created_draft_chapter_id(
            client,
            Chapter(
                term="10.1",
                test_content="Heating",
                product_type="家电",
                plan_sr="1",
                standard="IEC 60335",
                standard_version="2020",
                specific_product="",
                version="1.0",
                folder_id=5,
            ),
        )

        assert chapter_id == 102

    def test_matches_when_plan_sr_string_and_decimal_format_differ(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "content": [
                {
                    "id": 165,
                    "term": "7.14",
                    "testContent": "RUBBING TEST FOR RATING LABEL",
                    "status": 0,
                    "productType": "家电",
                    "planSr": "1.0",
                    "standard": "60335-2-9",
                    "standardVersion": "",
                    "specificProduct": "",
                    "version": "1.0",
                    "folder": {"id": 1059},
                }
            ],
            "totalElements": 1,
        }

        chapter_id = find_created_draft_chapter_id(
            client,
            Chapter(
                term="7.14",
                test_content="RUBBING TEST FOR RATING LABEL",
                product_type="家电",
                plan_sr="1",
                standard="60335-2-9",
                standard_version="",
                specific_product="",
                version="1.0",
                folder_id=1059,
            ),
        )

        assert chapter_id == 165
        params = client.get.call_args[1]["params"]
        assert params["term"] == "7.14"
        assert params["testContent"] == "RUBBING TEST FOR RATING LABEL"
        assert params["version"] == "1.0"


class TestUpdateChapter:
    def test_success(self):
        client = _mock_client()
        client.put.return_value.status_code = 204
        ch = Chapter(id=42, term="10.2", test_content="更新", standard="IEC 60335", folder_id=1)
        result = update_chapter(client, ch)
        assert result is True
        body = client.put.call_args[1]["json"]
        assert body["id"] == 42


class TestDeleteChapters:
    def test_success(self):
        client = _mock_client()
        client.delete.return_value.status_code = 200
        result = delete_chapters(client, [1, 2, 3])
        assert result is True
        body = client.delete.call_args[1]["json"]
        assert body == [1, 2, 3]


class TestImportChapterDoc:
    def test_success(self, tmp_path: Path):
        client = _mock_client()
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {"code": 200, "msg": "ok"}
        docx_path = tmp_path / "sample.docx"
        docx_path.write_bytes(b"fake-docx")

        result = import_chapter_doc(client, chapter_id=11, file_path=docx_path)

        assert result == {"code": 200, "msg": "ok"}
        client.post.assert_called_once()
        call_args = client.post.call_args
        assert call_args[0][0] == "/api/chapter-doc/import"
        assert call_args[1]["params"] == {"chapterId": 11}
        assert "json" not in call_args[1]
        uploaded = call_args[1]["files"]["file"]
        assert uploaded[0] == "sample.docx"
        assert uploaded[2] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert uploaded[1].closed is True


class TestQueryDraftChapters:
    def test_query_draft_chapters_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "content": [
                {
                    "id": 9,
                    "term": "10.2",
                    "testContent": "content",
                    "status": 0,
                }
            ],
            "totalElements": 1,
        }

        result = query_draft_chapters(
            client,
            folder_id=5,
            standard="IEC 60335",
            standard_version="2020",
            page=2,
            size=50,
        )

        assert result.total_elements == 1
        assert result.content[0].id == 9
        assert result.content[0].status == 0
        client.get.assert_called_once()
        call_args = client.get.call_args
        assert call_args[0][0] == "/api/chapter"
        params = call_args[1]["params"]
        assert params == {
            "page": 2,
            "size": 50,
            "folderId": 5,
            "status": 0,
            "standard": "IEC 60335",
            "standardVersion": "2020",
        }
