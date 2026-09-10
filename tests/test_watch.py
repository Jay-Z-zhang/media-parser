import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from src.watch.cli import build_parser, dispatch
from src.watch.engine import VideoItem, list_creator_videos
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


class WatchCliTests(unittest.TestCase):
    def test_parser_add(self):
        args = build_parser().parse_args(["add", "--platform", "tiktok", "--creator", "@foo"])
        self.assertEqual(args.action, "add")
        self.assertEqual(args.creator, "@foo")

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
