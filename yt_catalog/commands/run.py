"""Handler for `yt-catalog run` — the main scrape/categorize/vault pipeline."""

from __future__ import annotations
import argparse
import json
import os
from datetime import date
from pathlib import Path

from ..config import PHASE_ORDER
from ..models import Video, save_checkpoint, load_checkpoint, video_to_dict
from ..scraper import scrape_notifications
from ..enricher import enrich_videos_innertube, download_thumbnails
from ..categorizer import categorize_and_rank
from ..vault_generator import generate_vault
from ..api_scraper import scrape_via_api
from ..run_state import (
    is_first_run, get_last_video_date, get_last_run_video_ids,
    get_estimated_new_videos, get_daily_median, update_after_run,
)


def _save_channels_json(channels_map: dict[str, str]) -> None:
    """Save channel name->ID mapping to channels.json for future API runs."""
    channels_file = Path.cwd() / "channels.json"
    existing: dict = {}
    if channels_file.exists():
        try:
            existing = json.loads(channels_file.read_text())
            if isinstance(existing, list):
                existing = {}
        except Exception:
            existing = {}
    existing.update(channels_map)
    channels_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"  Saved {len(existing)} channels to channels.json")


def handle_run(args: argparse.Namespace) -> None:
    if args.ai_provider:
        os.environ["AI_PROVIDER"] = args.ai_provider
        if args.source == "chrome" and args.ai_provider != "claude-cli":
            print("Warning: Chrome integration requires Claude CLI. Notifications scraping will use Chrome,")
            print("but AI categorization will use the specified provider.")

    run_date = date.today().isoformat()
    run_dir = str(Path("vault") / "runs" / run_date)

    checkpoint = None
    completed_phase = 0
    if args.from_checkpoint:
        checkpoint = load_checkpoint(args.from_checkpoint)
        completed_phase = PHASE_ORDER.get(checkpoint.last_completed_phase, 0)
        videos = checkpoint.videos
    else:
        videos = []

    # Incremental run detection
    first_run = is_first_run()
    last_date = get_last_video_date()
    prev_ids = get_last_run_video_ids()
    if first_run:
        print("First run detected — fetching all available notifications")
    else:
        median = get_daily_median()
        estimate = get_estimated_new_videos(last_date)
        print(f"Incremental run — last video: {last_date}")
        print(f"  Daily median: {median:.1f} videos/day, estimated new: ~{estimate}")

    # Phase 1: Scrape
    if completed_phase >= PHASE_ORDER["scraping"]:
        print("Skipping scraping (already completed in checkpoint)")
    else:
        if args.source == "api":
            print("Phase 1: Scraping YouTube via Data API v3...")
            since = None if first_run else last_date
            videos = scrape_via_api(
                max_days=args.max_days,
                max_videos=args.max_videos,
                since_date=since,
            )
            # Dedup against previous run
            if prev_ids and videos:
                pre_dedup = len(videos)
                videos = [v for v in videos if v.video_id not in prev_ids]
                if pre_dedup != len(videos):
                    print(f"  Deduped: {pre_dedup - len(videos)} overlap with previous run")
            if not videos:
                print("No videos found. Nothing to catalog.")
                return
            save_checkpoint(videos, run_dir, phase="scraping")
            print(f"  Scraped {len(videos)} videos (already filtered)")
            # API path: skip enrichment since we already have full metadata
            # Jump directly to categorization
            print("Phase 2: Skipping enrichment (API source provides full metadata)")
            print("  Downloading thumbnails...")
            download_thumbnails(videos, run_dir)
            save_checkpoint(videos, run_dir, phase="enrichment")
        else:
            print("Phase 1: Scraping YouTube notifications (chrome)...")
            videos = scrape_notifications(
                max_days=args.max_days,
                max_videos=args.max_videos,
            )
            if not videos:
                print("No videos found. Nothing to catalog.")
                return
            save_checkpoint(videos, run_dir, phase="scraping")
            print(f"  Scraped {len(videos)} videos")

    # Phase 2: Enrich (chrome source only -- api source already completed above)
    if completed_phase < PHASE_ORDER["enrichment"] and args.source != "api":
        print("Phase 2: Enriching video metadata via InnerTube...")
        videos = enrich_videos_innertube(videos)
        pre_filter = len(videos)
        videos = [v for v in videos if not v.is_short and not v.is_live]
        filtered_count = pre_filter - len(videos)
        if filtered_count:
            print(f"  Removed {filtered_count} Shorts/Livestreams")

        # Auto-save channel name->ID map for future API runs
        channels_map = {}
        for v in videos:
            if v.channel and v.channel_id:
                channels_map[v.channel] = v.channel_id
        if channels_map:
            _save_channels_json(channels_map)

        print("  Downloading thumbnails...")
        download_thumbnails(videos, run_dir)
        save_checkpoint(videos, run_dir, phase="enrichment", shorts_filtered=filtered_count)
        print(f"  Enriched {len(videos)} videos")
    elif completed_phase < PHASE_ORDER["enrichment"] and args.source == "api":
        # Already handled in scraping block above
        pass
    else:
        print("Skipping enrichment (already completed in checkpoint)")

    # Phase 3: Categorize & Rank
    if completed_phase < PHASE_ORDER["categorization"]:
        print("Phase 3: Categorizing and ranking videos...")
        videos = categorize_and_rank(videos)
        save_checkpoint(videos, run_dir, phase="categorization")
        print(f"  Categorized {len(videos)} videos")
    else:
        print("Skipping categorization (already completed in checkpoint)")

    # Phase 4: Generate Obsidian vault
    print("Phase 4: Generating Obsidian vault...")
    generate_vault(videos, run_dir,
                   mermaid_thumbnails=not args.no_mermaid_thumbnails)

    # Update run state for incremental tracking
    stats = update_after_run(
        [video_to_dict(v) for v in videos],
        run_date,
    )
    print(f"\nDone! Vault generated at {run_dir}/")
    print(f"  Videos: {stats['total_videos']} total, {stats['new_videos']} new")
    if stats['overlap_with_previous']:
        print(f"  Overlap with previous run: {stats['overlap_with_previous']}")
    print(f"  Daily median: {stats['daily_median']:.1f} videos/day")
    print(f"  Next run estimate: ~{stats['estimated_next_run']} videos")
