#!/usr/bin/env python3
"""YouTube Notification Cataloger — scrape, categorize, visualize."""

from __future__ import annotations
import argparse
import sys
from datetime import date
from pathlib import Path

from config import PHASE_ORDER
from models import save_checkpoint, load_checkpoint
from scraper import scrape_notifications
from enricher import enrich_videos, download_thumbnails
from categorizer import categorize_and_rank
from vault_generator import generate_vault


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
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
        print("Phase 1: Scraping YouTube notifications...")
        videos = scrape_notifications(
            max_days=args.max_days,
            max_videos=args.max_videos,
        )
        if not videos:
            print("No videos found. Nothing to catalog.")
            return
        save_checkpoint(videos, run_dir, phase="scraping")
        print(f"  Scraped {len(videos)} videos")

    # Phase 2: Enrich
    if completed_phase < PHASE_ORDER["enrichment"]:
        print("Phase 2: Enriching video metadata...")
        videos = enrich_videos(videos)
        pre_filter = len(videos)
        videos = [v for v in videos if not v.is_short and not v.is_live]
        filtered_count = pre_filter - len(videos)
        if filtered_count:
            print(f"  Removed {filtered_count} Shorts/Livestreams")
        print("  Downloading thumbnails...")
        download_thumbnails(videos, run_dir)
        save_checkpoint(videos, run_dir, phase="enrichment", shorts_filtered=filtered_count)
        print(f"  Enriched {len(videos)} videos")
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
