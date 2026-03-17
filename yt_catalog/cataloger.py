#!/usr/bin/env python3
"""YouTube Notification Cataloger — scrape, categorize, visualize."""

from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .utils import load_dotenv

# Load .env before anything else touches env vars
load_dotenv()

from .config import PHASE_ORDER
from .models import Video, save_checkpoint, load_checkpoint
from .scraper import scrape_notifications
from .enricher import enrich_videos, enrich_videos_innertube, download_thumbnails
from .categorizer import categorize_and_rank
from .vault_generator import generate_vault
from .api_scraper import scrape_via_api


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Notification Cataloger")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Only scrape notifications from the last N days")
    parser.add_argument("--max-videos", type=int, default=None,
                        help="Stop after scraping N videos")
    parser.add_argument("--from-checkpoint", type=str, default=None,
                        help="Resume from a previous data.json (skips completed phases)")
    parser.add_argument("--no-mermaid-thumbnails", action="store_true",
                        help="Use text-only mermaid nodes (no HTML img attempts)")
    parser.add_argument("--source", choices=["chrome", "api"], default="chrome",
                        help="Scraping source: 'chrome' uses bell-dropdown (default), "
                             "'api' uses YouTube Data API v3 (requires YOUTUBE_API_KEY)")
    parser.add_argument("--discover-channels", type=str, default=None, nargs="?", const="auto",
                        help="Discover channel IDs and save to channels.json. "
                             "Pass a checkpoint path to extract from existing data, "
                             "or 'auto' to use the latest run.")
    return parser.parse_args(argv)


def _save_channels_json(channels_map: dict[str, str]) -> None:
    """Save channel name→ID mapping to channels.json for future API runs."""
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


def discover_channels(checkpoint_path: str | None = None) -> None:
    """Discover channel IDs from existing data or via InnerTube API.

    1. Loads videos from a checkpoint (or finds the latest run)
    2. For videos missing channel_id, calls InnerTube player API to resolve it
    3. Saves {channel_name: channel_id} to channels.json
    """
    from .enricher import enrich_videos_innertube

    # Find checkpoint
    if checkpoint_path and checkpoint_path != "auto":
        cp_path = checkpoint_path
    else:
        # Find the latest run
        runs_dir = Path("vault/runs")
        if not runs_dir.exists():
            print("No runs found. Run a scrape first with: python cataloger.py")
            return
        run_dirs = sorted(runs_dir.iterdir(), reverse=True)
        cp_path = None
        for d in run_dirs:
            candidate = d / "data.json"
            if candidate.exists():
                cp_path = str(candidate)
                break
        if not cp_path:
            print("No checkpoint found in vault/runs/. Run a scrape first.")
            return

    print(f"Loading checkpoint: {cp_path}")
    checkpoint = load_checkpoint(cp_path)
    videos = checkpoint.videos
    print(f"  {len(videos)} videos loaded")

    # Check which videos already have channel_id
    missing_id = [v for v in videos if not v.channel_id]
    has_id = [v for v in videos if v.channel_id]
    print(f"  {len(has_id)} already have channel_id, {len(missing_id)} need resolution")

    if missing_id:
        print(f"  Resolving {len(missing_id)} channel IDs via InnerTube API...")
        enrich_videos_innertube(missing_id)

    # Build channel map
    channels_map: dict[str, str] = {}
    for v in videos:
        if v.channel and v.channel_id and v.channel not in channels_map:
            channels_map[v.channel] = v.channel_id

    if not channels_map:
        print("  No channel IDs could be resolved.")
        return

    _save_channels_json(channels_map)
    print(f"\nDiscovered {len(channels_map)} unique channels:")
    for name, cid in sorted(channels_map.items()):
        print(f"  {name}: {cid}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # --discover-channels is a standalone command
    if args.discover_channels is not None:
        path = args.discover_channels if args.discover_channels != "auto" else None
        discover_channels(path)
        return

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

    # Phase 2: Enrich (chrome source only — api source already completed above)
    if completed_phase < PHASE_ORDER["enrichment"] and args.source != "api":
        print("Phase 2: Enriching video metadata via InnerTube...")
        videos = enrich_videos_innertube(videos)
        pre_filter = len(videos)
        videos = [v for v in videos if not v.is_short and not v.is_live]
        filtered_count = pre_filter - len(videos)
        if filtered_count:
            print(f"  Removed {filtered_count} Shorts/Livestreams")

        # Auto-save channel name→ID map for future API runs
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


if __name__ == "__main__":
    main()
