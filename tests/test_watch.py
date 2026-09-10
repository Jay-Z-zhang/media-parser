import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from src.watch.cli import build_parser, dispatch
from src.watch.engine import VideoItem, download_video, list_creator_videos, parse_tiktok_video_url
from src.watch.store import (
    HumanPace,
    enabled_targets,
    normalize_creator,
    remove_target,
    upsert_target,
)


class WatchStoreTests(unittest.TestCase):
    def test_tiktok_and_douyin_urls(self):
        creator, url = normalize_creator("tiktok", "@foo")
        self.assertEqual(creator, "foo")
        self.assertEqual(url, "https://www.tiktok.com/@foo")
        creator, url = normalize_creator("douyin", "MS4wLjABAAAA")
        self.assertEqual(url, "https://www.douyin.com/user/MS4wLjABAAAA")

    def test_upsert_and_filter(self):
        data = {"version": 1, "targets": []}
        upsert_target(data, platform="tiktok", creator="@foo", max_per_run=2)
        upsert_target(data, platform="douyin", creator="MS4wLjABAAAA")
        self.assertEqual(len(enabled_targets(data, platform="tiktok")), 1)
        self.assertTrue(remove_target(data, "tiktok", "foo"))
        self.assertEqual(len(data["targets"]), 1)

    def test_interval_jitter(self):
        pace = HumanPace(jitter=0.35)
        samples = [pace.next_interval(3600) for _ in range(20)]
        self.assertTrue(all(3600 * 0.65 <= value <= 3600 * 1.35 for value in samples))


class WatchEngineTests(unittest.TestCase):
    def test_list_douyin_uses_aweme_list_without_login(self):
        aweme = {
            "aweme_id": "111",
            "desc": "demo",
            "video": {"play_addr": {"url_list": ["https://cdn.douyin.com/a.mp4", "https://cdn.douyin.com/b.mp4", "https://origin.douyin.com/c.mp4"]}},
        }
        with patch("src.watch.engine.DouyinParser") as mock_cls:
            parser = mock_cls.return_value
            parser.list_user_awemes.return_value = [aweme]
            parser.get_real_video_url.return_value = "https://origin.douyin.com/c.mp4"
            items = list_creator_videos("douyin", "MS4wLjABAAAA", count=3)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].video_id, "111")
        mock_cls.assert_called_once()
        self.assertEqual(mock_cls.call_args.kwargs.get("fetch"), False)

    def test_parse_tiktok_video_url(self):
        item = parse_tiktok_video_url(
            "https://www.tiktok.com/@zihan_music/video/7682625310977707272?is_from_webapp=1"
        )
        self.assertEqual(item.video_id, "7682625310977707272")
        self.assertEqual(item.page_url, "https://www.tiktok.com/@zihan_music/video/7682625310977707272")
        with self.assertRaises(ValueError):
            parse_tiktok_video_url("https://www.tiktok.com/@zihan_music")

    def test_tiktok_download_uses_page_session(self):
        item = VideoItem(
            "tiktok",
            "123",
            "123",
            "https://stale.example/old.mp4",
            "https://www.tiktok.com/@foo/video/123",
        )
        payload = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2048

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_content(self, size):
                yield payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as tmp, patch("src.watch.engine.TikTokParser") as mock_cls:
            parser = mock_cls.return_value
            parser.get_real_video_url.return_value = "https://cdn.tiktok.com/dl.mp4"
            parser.get_title_content.return_value = "hello"
            parser.headers = {"User-Agent": "UA"}
            parser.session.get.return_value = FakeResponse()
            dest = download_video(item, Path(tmp), "https://www.tiktok.com/")
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 1024)
            parser.session.get.assert_called_once()
            self.assertEqual(parser.session.get.call_args.args[0], "https://cdn.tiktok.com/dl.mp4")


class WatchCliTests(unittest.TestCase):
    def test_parser_add(self):
        args = build_parser().parse_args(["add", "--platform", "tiktok", "--creator", "@foo"])
        self.assertEqual(args.action, "add")
        self.assertEqual(args.creator, "@foo")
        args = build_parser().parse_args(["download", "https://www.tiktok.com/@foo/video/123"])
        self.assertEqual(args.action, "download")
        self.assertEqual(args.urls, ["https://www.tiktok.com/@foo/video/123"])

    def test_dispatch_add_and_once_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            add_args = Namespace(action="add", platform="tiktok", creator="@foo", max_per_run=2)
            self.assertEqual(dispatch(add_args, state_dir=home), 0)
            saved = json.loads((home / "watchlist.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["targets"][0]["creator"], "foo")
            once_args = Namespace(
                action="once",
                platform="tiktok",
                creator="@foo",
                max_per_run=1,
                out=home / "videos",
                dry_run=True,
                no_human=True,
            )
            fake_item = VideoItem("tiktok", "99", "title", "https://cdn.tiktok.com/a.mp4", "https://www.tiktok.com/@foo/video/99")
            with patch("src.watch.cli.list_creator_videos", return_value=[fake_item]):
                self.assertEqual(dispatch(once_args, state_dir=home), 0)
