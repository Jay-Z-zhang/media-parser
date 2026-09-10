import json
import unittest
from unittest.mock import patch

from src.parsers.tiktok_parser import TikTokParser, collect_item_structs, play_url_from_video


HYDRATION = {
    "__DEFAULT_SCOPE__": {
        "webapp.video-detail": {
            "itemInfo": {
                "itemStruct": {
                    "id": "123",
                    "desc": "hello tiktok",
                    "author": {"uniqueId": "foo", "nickname": "Foo", "id": "u1"},
                    "video": {
                        "playAddr": "https://cdn.tiktok.com/play.mp4",
                        "cover": "https://cdn.tiktok.com/cover.jpg",
                    },
                }
            }
        }
    }
}


class TikTokParserTest(unittest.TestCase):
    def test_play_url_from_video_dict(self):
        url = play_url_from_video({"downloadAddr": {"url_list": ["https://cdn.tiktok.com/a.mp4"]}})
        self.assertEqual(url, "https://cdn.tiktok.com/a.mp4")

    def test_collect_item_structs(self):
        items = collect_item_structs(HYDRATION)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "123")

    def test_parses_hydration_script(self):
        html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            + json.dumps(HYDRATION)
            + "</script></html>"
        )
        with patch.object(TikTokParser, "fetch_html_content", return_value=html):
            parser = TikTokParser("https://www.tiktok.com/@foo/video/123")
        self.assertEqual(parser.get_real_video_url(), "https://cdn.tiktok.com/play.mp4")
        self.assertEqual(parser.get_title_content(), "hello tiktok")
        self.assertEqual(parser.get_author_info()["nickname"], "Foo")
        self.assertEqual(len(parser.list_user_items(count=5)), 1)
