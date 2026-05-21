"""测试条款 API 函数"""

from unittest.mock import MagicMock

from tuv_tools.core.chapter.api import (
    create_chapter,
    delete_chapters,
    get_chapters,
    update_chapter,
)
from tuv_tools.core.chapter.client import TuvClient
from tuv_tools.core.chapter.models import Chapter


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
