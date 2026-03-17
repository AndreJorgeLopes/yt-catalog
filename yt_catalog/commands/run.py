"""Handler for `yt-catalog run` — the main scrape/categorize/vault pipeline."""

from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path

from ..config import PHASE_ORDER
from ..models import Video, save_checkpoint, load_checkpoint
from ..scraper import scrape_notifications
from ..enricher import enrich_videos_innertube, download_thumbnails
from ..categorizer import categorize_and_rank
from ..vault_generator import generate_vault
from ..api_scraper import scrape_via_api


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

    # Phase 1: Scrape
    if completed_phase >= PHASE_ORDER["scraping"]:
        print("Skipping scraping (already completed in checkpoint)")
    else:
        if args.source == "api":
            print("Phase 1: Scraping YouTube via Data API v3...")
            videos = scrape_via_api(
                max_days=args.max_days,
                max_videos=args.max_videos,
            )
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
    print(f"Done! Vault generated at {run_dir}/")
