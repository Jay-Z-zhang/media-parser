from __future__ import annotations

import re
from pathlib import Path

import requests

from src.parsers.douyin_parser import DouyinParser
from src.parsers.tiktok_parser import TikTokParser, play_url_from_video
from src.watch.store import normalize_creator, normalize_platform


COOKIE_HINT = "匿名请求被拦截时，可在 .env 配置 DOUYIN_COOKIE，或换一个公开账号再试。"
TIKTOK_VIDEO_RE = re.compile(r"tiktok\.com/@([^/?#]+)/video/(\d+)", re.I)


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
    return _list_tiktok(profile_url, creator_id, count, seed=creator)


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


def _list_tiktok(profile_url: str, creator_id: str, count: int, seed: str | None = None) -> list[VideoItem]:
    parser = TikTokParser(profile_url)
    items = []
    for raw in parser.list_user_items(count=count):
        video_id = str(raw.get("id") or raw.get("idStr") or "")
        if not video_id:
            continue
        items.append(
            VideoItem(
                "tiktok",
                video_id,
                raw.get("desc") or video_id,
                play_url_from_video(raw.get("video") or {}) or "",
                f"https://www.tiktok.com/@{creator_id}/video/{video_id}",
            )
        )
        if len(items) >= count:
            break
    if items:
        return items
    match = TIKTOK_VIDEO_RE.search(seed or "")
    if not match:
        return []
    return [_item_from_tiktok_page(f"https://www.tiktok.com/@{match.group(1)}/video/{match.group(2)}")]


def parse_tiktok_video_url(url: str) -> VideoItem:
    match = TIKTOK_VIDEO_RE.search(url or "")
    if not match:
        raise ValueError(f"不是 TikTok 作品页链接: {url}")
    video_id = match.group(2)
    return VideoItem(
        "tiktok",
        video_id,
        video_id,
        "",
        f"https://www.tiktok.com/@{match.group(1)}/video/{video_id}",
    )


def _item_from_tiktok_page(page_url: str) -> VideoItem:
    parser = TikTokParser(page_url)
    if not parser.item:
        raise RuntimeError(f"打开作品页失败（可能被 WAF 拦截）: {page_url}")
    video_id = str(parser.item.get("id") or parser.item.get("idStr") or "")
    if not video_id:
        raise RuntimeError(f"作品页没有视频 ID: {page_url}")
    return VideoItem(
        "tiktok",
        video_id,
        parser.get_title_content() or video_id,
        parser.get_real_video_url() or "",
        page_url,
    )


def download_video(item: VideoItem, output_root: Path, referer: str) -> Path:
    dest_dir = output_root / item.platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    if item.platform == "tiktok":
        return _download_tiktok_like_button(item, dest_dir)
    title = re.sub(r"[^\w.-]+", "_", item.title, flags=re.UNICODE)[:40] or item.video_id
    dest = dest_dir / f"{item.video_id}_{title}.mp4"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }
    _stream_to_file(requests, item.url, headers, dest)
    return dest


def _download_tiktok_like_button(item: VideoItem, dest_dir: Path) -> Path:
    # Web 右侧绿色下载按钮：先进作品页拿 Cookie，再请求 video.downloadAddr。
    parser = TikTokParser(item.page_url)
    media_url = parser.get_real_video_url()
    if not media_url:
        raise RuntimeError(f"作品页没有 downloadAddr/playAddr: {item.page_url}")
    title = parser.get_title_content() or item.title or item.video_id
    safe = re.sub(r"[^\w.-]+", "_", title, flags=re.UNICODE)[:40] or item.video_id
    dest = dest_dir / f"{item.video_id}_{safe}.mp4"
    headers = {
        **(parser.headers or {}),
        "Referer": "https://www.tiktok.com/",
        "Accept": "*/*",
    }
    _stream_to_file(parser.session, media_url, headers, dest, timeout=90)
    return dest


def _stream_to_file(client, url: str, headers: dict, dest: Path, timeout: int = 60) -> None:
    with client.get(url, headers=headers, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        first = None
        try:
            with dest.open("wb") as handle:
                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    if first is None:
                        first = chunk[:64]
                        stripped = first.lstrip()
                        if stripped[:1] == b"<" or b"<html" in stripped.lower():
                            raise RuntimeError(
                                "CDN 返回了 HTML（缺进页 Cookie）。需要先打开作品页再拉 downloadAddr。"
                            )
                    handle.write(chunk)
        except Exception:
            if dest.exists():
                dest.unlink()
            raise
    if not dest.exists() or dest.stat().st_size < 1024:
        if dest.exists():
            dest.unlink()
        raise RuntimeError("下载文件过小，不像完整视频")
