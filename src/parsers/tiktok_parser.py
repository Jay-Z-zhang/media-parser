import json
import re
import time

from src.parser_factory import register_parser
from src.parsers.base_parser import BaseParser
from utils.web_fetcher import UrlParser


def play_url_from_video(video):
    if not isinstance(video, dict):
        return None
    for key in ("downloadAddr", "playAddr", "play_addr", "download_addr"):
        value = video.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
        if isinstance(value, dict):
            urls = value.get("UrlList") or value.get("url_list") or []
            for item in urls:
                if isinstance(item, str) and item.startswith("http"):
                    return item
    return None


def collect_item_structs(payload, found=None):
    if found is None:
        found = []
    if isinstance(payload, dict):
        video = payload.get("video")
        item_id = payload.get("id") or payload.get("idStr") or payload.get("aweme_id")
        if item_id and isinstance(video, dict) and play_url_from_video(video):
            found.append(payload)
        for value in payload.values():
            collect_item_structs(value, found)
    elif isinstance(payload, list):
        for value in payload:
            collect_item_structs(value, found)
    return found


def parse_hydration_payloads(html):
    payloads = []
    if not html:
        return payloads
    for pattern in (
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        r'<script id="SIGI_STATE"[^>]*>(.*?)</script>',
    ):
        match = re.search(pattern, html, re.S)
        if not match:
            continue
        raw = match.group(1).strip()
        try:
            payloads.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return payloads


@register_parser("TikTok")
class TikTokParser(BaseParser):
    def __init__(self, real_url, fetch=True):
        super().__init__(real_url)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            "Referer": "https://www.tiktok.com/",
        }
        self.item = None
        self.items = []
        if fetch:
            self._load()

    def fetch_html_content(self):
        last = None
        for attempt in range(2):
            try:
                resp = self.session.get(self.real_url, headers=self.headers, timeout=20)
                resp.raise_for_status()
                last = resp.text or ""
                if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in last or "SIGI_STATE" in last:
                    self.html_content = last
                    return last
            except Exception:
                pass
            if attempt == 0:
                time.sleep(1.5)
        self.html_content = last
        return last

    def _load(self):
        html = self.fetch_html_content()
        self.items = []
        seen = set()
        for payload in parse_hydration_payloads(html):
            for item in collect_item_structs(payload):
                item_id = str(item.get("id") or item.get("idStr") or "")
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)
                self.items.append(item)
        video_id = UrlParser.get_video_id(self.real_url)
        self.item = next((item for item in self.items if str(item.get("id") or item.get("idStr")) == str(video_id)), None)
        if self.item is None and self.items:
            self.item = self.items[0]

    def list_user_items(self, count=10):
        return self.items[: max(1, int(count))]

    def get_real_video_url(self):
        if not self.item:
            return None
        return play_url_from_video(self.item.get("video") or {})

    def get_title_content(self):
        if not self.item:
            return None
        return self.item.get("desc") or self.item.get("description") or ""

    def get_description(self):
        return self.get_title_content()

    def get_cover_photo_url(self):
        video = (self.item or {}).get("video") or {}
        for key in ("cover", "originCover", "dynamicCover"):
            value = video.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
            if isinstance(value, dict):
                urls = value.get("UrlList") or value.get("url_list") or []
                if urls:
                    return urls[0]
        return None

    def get_author_info(self):
        author = (self.item or {}).get("author") or {}
        if not isinstance(author, dict):
            return {"nickname": "", "author_id": "", "avatar": ""}
        return {
            "nickname": author.get("nickname") or author.get("uniqueId") or "",
            "author_id": str(author.get("id") or author.get("secUid") or author.get("uniqueId") or ""),
            "avatar": author.get("avatarLarger") or author.get("avatarMedium") or author.get("avatarThumb") or "",
        }

    def get_video_list(self):
        url = self.get_real_video_url()
        return [url] if url else []
