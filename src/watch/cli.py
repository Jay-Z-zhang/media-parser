from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from src.watch.engine import COOKIE_HINT, download_video, list_creator_videos, parse_tiktok_video_url
from src.watch.store import (
    HumanPace,
    archive_key,
    default_output_dir,
    default_state_dir,
    enabled_targets,
    load_archive,
    load_watchlist,
    normalize_creator,
    normalize_platform,
    remove_target,
    save_archive,
    save_json,
    upsert_target,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.watch",
        description="订阅抖音 / TikTok 创作者主页，定期下载新短视频。登录不是必须的。",
    )
    actions = parser.add_subparsers(dest="action", required=True)

    add = actions.add_parser("add", help="订阅一个创作者")
    add.add_argument("--platform", required=True, choices=("douyin", "tiktok"))
    add.add_argument("--creator", required=True, help="主页 URL、抖音 sec_uid，或 TikTok @name")
    add.add_argument("--max-per-run", type=int, default=3)

    actions.add_parser("list", help="查看订阅列表")

    remove = actions.add_parser("remove", help="取消订阅")
    remove.add_argument("--platform", required=True, choices=("douyin", "tiktok"))
    remove.add_argument("--creator", required=True)

    def add_run_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--platform", choices=("douyin", "tiktok"))
        sub.add_argument("--creator")
        sub.add_argument("--max-per-run", type=int, default=3)
        sub.add_argument("--out", type=Path, help="下载目录，默认 data/videos")
        sub.add_argument("--dry-run", action="store_true", help="只列出新视频，不落盘")
        sub.add_argument("--no-human", action="store_true", help="关闭间隔抖动")

    once = actions.add_parser("once", help="立即检查一次")
    add_run_flags(once)

    watch = actions.add_parser("watch", help="按人类节奏循环检查")
    add_run_flags(watch)
    watch.add_argument("--interval", type=int, default=3600, help="检查间隔秒数，默认 3600，实际会加减抖动")

    download = actions.add_parser("download", help="打开作品页后走官方下载按钮（downloadAddr）")
    download.add_argument("urls", nargs="+", help="TikTok 作品页 URL")
    download.add_argument("--out", type=Path, help="下载目录，默认 data/videos")
    return parser


def _targets(args, watchlist) -> list[dict]:
    selected = enabled_targets(watchlist, getattr(args, "platform", None), getattr(args, "creator", None))
    if selected:
        return selected
    if getattr(args, "platform", None) and getattr(args, "creator", None):
        creator_id, url = normalize_creator(args.platform, args.creator)
        return [{
            "platform": normalize_platform(args.platform),
            "creator": creator_id,
            "url": url,
            "max_per_run": max(1, int(args.max_per_run)),
            "enabled": True,
        }]
    return []


def _run_pass(args, state_dir: Path) -> int:
    watchlist = load_watchlist(state_dir / "watchlist.json")
    targets = _targets(args, watchlist)
    if not targets:
        print("没有订阅。先执行: python -m src.watch add --platform tiktok --creator @name")
        return 1
    archive_path = state_dir / "archive.json"
    seen = load_archive(archive_path)
    output_root = Path(args.out) if getattr(args, "out", None) else default_output_dir()
    pace = None if getattr(args, "no_human", False) else HumanPace()
    failures = 0
    for index, target in enumerate(targets):
        if index and pace:
            delay = pace.between_creators()
            print(f"换号等待 {delay:.0f}s")
            time.sleep(delay)
        limit = int(getattr(args, "max_per_run", None) or target.get("max_per_run") or 3)
        print(f"检查 {target['platform']} @{target['creator']}（最多 {limit} 条新视频，匿名）")
        try:
            items = list_creator_videos(target["platform"], target["url"], count=limit * 2)
        except Exception as exc:
            print(f"[fail] 拉取主页失败: {exc}. {COOKIE_HINT}")
            failures += 1
            continue
        fresh = [item for item in items if archive_key(item.platform, item.video_id) not in seen][:limit]
        if not fresh:
            print("没有新视频")
            continue
        referer = "https://www.douyin.com/" if target["platform"] == "douyin" else "https://www.tiktok.com/"
        for item in fresh:
            if args.dry_run:
                print(f"[dry-run] {item.platform} {item.video_id} {item.title}")
                continue
            if pace:
                time.sleep(pace.between_videos())
            try:
                dest = download_video(item, output_root, referer)
            except Exception as exc:
                print(f"[fail] {item.video_id}: {exc}. {COOKIE_HINT}")
                failures += 1
                continue
            seen.add(archive_key(item.platform, item.video_id))
            save_archive(archive_path, seen)
            print(f"[ok] {dest}")
    return 1 if failures else 0


def dispatch(args, state_dir: Path | None = None) -> int:
    state_dir = state_dir or default_state_dir()
    watchlist_path = state_dir / "watchlist.json"
    if args.action == "add":
        data = load_watchlist(watchlist_path)
        target = upsert_target(data, platform=args.platform, creator=args.creator, max_per_run=args.max_per_run)
        save_json(watchlist_path, data)
        print(f"已订阅 {target['platform']} @{target['creator']}")
        print(f"  {target['url']}")
        print("  登录: 不需要（公开主页匿名拉取）")
        return 0
    if args.action == "list":
        data = load_watchlist(watchlist_path)
        if not data.get("targets"):
            print("订阅列表为空")
            return 0
        for item in data["targets"]:
            print(f"[{'on' if item.get('enabled', True) else 'off'}] {item.get('platform')} @{item.get('creator')} max={item.get('max_per_run', 3)}")
            print(f"      {item.get('url')}")
        return 0
    if args.action == "remove":
        data = load_watchlist(watchlist_path)
        if not remove_target(data, args.platform, args.creator):
            print("未找到该订阅")
            return 1
        save_json(watchlist_path, data)
        print("已取消订阅")
        return 0
    if args.action == "once":
        return _run_pass(args, state_dir)
    if args.action == "watch":
        interval = max(60, int(args.interval))
        pace = None if args.no_human else HumanPace()
        print(f"每约 {interval}s 检查一次，Ctrl+C 停止。登录不是必须的。")
        try:
            while True:
                _run_pass(args, state_dir)
                sleep_for = pace.next_interval(interval) if pace else float(interval)
                print(f"下次检查 {sleep_for / 60:.1f} 分钟后")
                time.sleep(sleep_for)
        except KeyboardInterrupt:
            print("已停止")
            return 0
    if args.action == "download":
        output_root = Path(args.out) if getattr(args, "out", None) else default_output_dir()
        failures = 0
        for url in args.urls:
            try:
                item = parse_tiktok_video_url(url)
                dest = download_video(item, output_root, "https://www.tiktok.com/")
            except Exception as exc:
                print(f"[fail] {url}: {exc}")
                failures += 1
                continue
            print(f"[ok] {dest} ({dest.stat().st_size} bytes)")
        return 1 if failures else 0
    raise RuntimeError(f"未知命令: {args.action}")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
