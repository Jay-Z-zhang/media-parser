from __future__ import annotations

import re
from pathlib import Path

import requests

from src.parsers.douyin_parser import DouyinParser
from src.parsers.tiktok_parser import TikTokParser, play_url_from_video
from src.watch.store import normalize_creator, normalize_platform


COOKIE_HINT = "匿名请求被拦截时，可在 .env 配置 DOUYIN_COOKIE，或换一个公开账号再试。"


class VideoItem:
    def __init__(self, platform: str, video_id: str, title: str, url: str, page_url: str):
        self.platform = platform
        self.video_id = str(video_id)
        self.title = title or video_id
        self.url = url
        self.page_url = page_url


def list_creator_videos(platform: str, creator: str, count: int = 3) -> list[VideoItem]:
    platform = normalize_platform(platform)
    creator_id, profile_url = normalize_creator(platform, creator)
    if platform == "douyin":
        return _list_douyin(profile_url, creator_id, count)
    return _list_tiktok(profile_url, creator_id, count)


def _list_douyin(profile_url: str, creator_id: str, count: int) -> list[VideoItem]:
    parser = DouyinParser(profile_url, fetch=False)
    awemes = parser.list_user_awemes(count=count)
    items = []
    for aweme in awemes:
        parser.data = {"aweme_detail": aweme}
        video_url = parser.get_real_video_url()
        video_id = str(aweme.get("aweme_id") or aweme.get("id") or "")
        if not video_url or not video_id:
            continue
        items.append(
            VideoItem(
                "douyin",
                video_id,
                aweme.get("desc") or video_id,
                video_url,
                f"https://www.douyin.com/video/{video_id}",
            )
        )
        if len(items) >= count:
            break
    return items


def _list_tiktok(profile_url: str, creator_id: str, count: int) -> list[VideoItem]:
    parser = TikTokParser(profile_url)
    items = []
    for raw in parser.list_user_items(count=count):
        video_id = str(raw.get("id") or raw.get("idStr") or "")
        video_url = play_url_from_video(raw.get("video") or {})
        if not video_id or not video_url:
            continue
        items.append(
            VideoItem(
                "tiktok",
                video_id,
                raw.get("desc") or video_id,
                video_url,
                f"https://www.tiktok.com/@{creator_id}/video/{video_id}",
            )
        )
        if len(items) >= count:
            break
    return items


def download_video(item: VideoItem, output_root: Path, referer: str) -> Path:
    dest_dir = output_root / item.platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    title = re.sub(r"[^\w.-]+", "_", item.title, flags=re.UNICODE)[:40] or item.video_id
    dest = dest_dir / f"{item.video_id}_{title}.mp4"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }
    with requests.get(item.url, headers=headers, stream=True, timeout=60) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(64 * 1024):
                if chunk:
                    handle.write(chunk)
    return dest
