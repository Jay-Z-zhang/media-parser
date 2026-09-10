from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from configs.general_constants import PROJECT_ROOT

WATCH_VERSION = 1


def default_state_dir() -> Path:
    return Path(PROJECT_ROOT) / "data" / "watch"


def default_output_dir() -> Path:
    return Path(PROJECT_ROOT) / "data" / "videos"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_platform(platform: str) -> str:
    name = (platform or "").strip().lower()
    aliases = {"dy": "douyin", "抖音": "douyin", "tk": "tiktok", "tt": "tiktok"}
    name = aliases.get(name, name)
    if name not in {"douyin", "tiktok"}:
        raise ValueError(f"不支持的订阅平台: {platform}，请使用 douyin 或 tiktok")
    return name


def creator_slug(creator: str) -> str:
    return re.sub(r"[^\w.-]+", "_", (creator or "").strip().lstrip("@"), flags=re.UNICODE)[:80] or "unknown"


def normalize_creator(platform: str, creator: str) -> tuple[str, str]:
    platform = normalize_platform(platform)
    raw = (creator or "").strip()
    if not raw:
        raise ValueError("需要提供创作者账号或主页链接")
    if platform == "tiktok":
        match = re.search(r"tiktok\.com/@([^/?#]+)", raw, re.I)
        name = match.group(1) if match else raw.lstrip("@").strip("/")
        return name, f"https://www.tiktok.com/@{name}"
    match = re.search(r"douyin\.com/user/([^/?#]+)", raw, re.I)
    if match:
        user_id = match.group(1)
        return user_id, f"https://www.douyin.com/user/{user_id}"
    user_id = raw.lstrip("@").strip("/")
    return user_id, f"https://www.douyin.com/user/{user_id}"


def load_watchlist(path: Path) -> dict[str, Any]:
    data = load_json(path, {"version": WATCH_VERSION, "targets": []})
    if not isinstance(data, dict):
        return {"version": WATCH_VERSION, "targets": []}
    data.setdefault("version", WATCH_VERSION)
    data.setdefault("targets", [])
    return data


def upsert_target(data: dict[str, Any], *, platform: str, creator: str, max_per_run: int = 3) -> dict[str, Any]:
    platform = normalize_platform(platform)
    creator_id, url = normalize_creator(platform, creator)
    payload = {
        "platform": platform,
        "creator": creator_id,
        "url": url,
        "max_per_run": max(1, int(max_per_run)),
        "enabled": True,
    }
    for item in data.setdefault("targets", []):
        if item.get("platform") == platform and item.get("creator") == creator_id:
            item.update(payload)
            return item
    payload["added_at"] = now_iso()
    data["targets"].append(payload)
    return payload


def remove_target(data: dict[str, Any], platform: str, creator: str) -> bool:
    platform = normalize_platform(platform)
    creator_id = normalize_creator(platform, creator)[0]
    before = len(data.get("targets") or [])
    data["targets"] = [
        item
        for item in (data.get("targets") or [])
        if not (item.get("platform") == platform and item.get("creator") == creator_id)
    ]
    return len(data["targets"]) < before


def enabled_targets(data: dict[str, Any], platform: str | None = None, creator: str | None = None) -> list[dict[str, Any]]:
    want_platform = normalize_platform(platform) if platform else None
    selected = []
    for item in data.get("targets") or []:
        if item.get("enabled") is False:
            continue
        if want_platform and item.get("platform") != want_platform:
            continue
        if creator:
            match_platform = want_platform or item.get("platform")
            if item.get("creator") != normalize_creator(match_platform, creator)[0]:
                continue
        selected.append(item)
    return selected


def archive_key(platform: str, video_id: str) -> str:
    return f"{platform}:{video_id}"


def load_archive(path: Path) -> set[str]:
    data = load_json(path, [])
    if isinstance(data, list):
        return {str(item) for item in data}
    return set()


def save_archive(path: Path, keys: set[str]) -> None:
    save_json(path, sorted(keys))


class HumanPace:
    def __init__(self, video_min=8, video_max=25, creator_min=90, creator_max=280, jitter=0.35):
        self.video_min = video_min
        self.video_max = video_max
        self.creator_min = creator_min
        self.creator_max = creator_max
        self.jitter = jitter

    def between_videos(self) -> float:
        return round(random.uniform(self.video_min, self.video_max), 1)

    def between_creators(self) -> float:
        return round(random.uniform(self.creator_min, self.creator_max), 1)

    def next_interval(self, seconds: float) -> float:
        jitter = min(max(self.jitter, 0), 0.8)
        return max(30.0, seconds * random.uniform(1 - jitter, 1 + jitter))
