#!/usr/bin/env python3
"""End-to-end benchmark: run both chrome and API flows with clean isolation.

Measures wall-clock time for each phase and total pipeline.
Uses the raw_notifications_backup.json as the scrape input for the chrome flow.
Runs the API flow live against YouTube Data API.
"""
import json
import os
import shutil
import sys
import time
from datetime import date
from pathlib import Path

# Load .env
from yt_catalog.utils import load_dotenv
load_dotenv()

from yt_catalog.models import Video, save_checkpoint, load_checkpoint, video_to_dict
from yt_catalog.enricher import enrich_videos_innertube, download_thumbnails
from yt_catalog.rule_categorizer import categorize_video
from yt_catalog.vault_generator import generate_vault
from yt_catalog.config import get_duration_group


def _clean_run_dir(run_dir: str) -> None:
    """Remove run directory completely for clean isolation."""
    p = Path(run_dir)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def _run_chrome_flow() -> dict:
    """Run the chrome-like flow using raw notification backup as scrape input."""
    timings = {}
    run_dir = "vault/runs/benchmark-chrome"
    _clean_run_dir(run_dir)

    # Phase 1: Load raw notifications (simulates scraping)
    t0 = time.time()
    raw_path = Path("vault/runs/2026-03-16/raw_notifications_backup.json")
    if not raw_path.exists():
        print("ERROR: raw_notifications_backup.json not found")
        return {"error": "no raw data"}

    raw = json.loads(raw_path.read_text())
    notifs = raw["notifications"]

    # Deduplicate and filter shorts
    seen: set[str] = set()
    videos: list[Video] = []
    for n in notifs:
        if n["v"] not in seen and n["s"] == 0:
            seen.add(n["v"])
            videos.append(Video(
                video_id=n["v"], title=n["t"], channel=n["c"],
                url=f"https://www.youtube.com/watch?v={n['v']}",
                relative_time="",
            ))
    timings["scrape"] = time.time() - t0
    print(f"  Phase 1 (scrape sim): {timings['scrape']:.2f}s — {len(videos)} videos from {len(notifs)} raw")

    # Phase 2: Enrich via InnerTube
    t0 = time.time()
    enrich_videos_innertube(videos)
    pre = len(videos)
    videos = [v for v in videos if not v.is_short and not v.is_live]
    filtered = pre - len(videos)
    timings["enrich"] = time.time() - t0
    print(f"  Phase 2 (enrich):     {timings['enrich']:.1f}s — {len(videos)} remain, {filtered} filtered")

    # Phase 3: Categorize
    t0 = time.time()
    for v in videos:
        result = categorize_video(video_to_dict(v))
        v.category = result["category"]
        v.interest_score = result["interest_score"]
        v.tags = result["tags"]
        v.summary = result["summary"]
        v.duration_group = result["duration_group"]
    timings["categorize"] = time.time() - t0
    print(f"  Phase 3 (categorize): {timings['categorize']*1000:.1f}ms")

    # Phase 4: Save checkpoint + generate vault (skip thumbnails for speed)
    t0 = time.time()
    save_checkpoint(videos, run_dir, phase="categorization", shorts_filtered=filtered)
    generate_vault(videos, run_dir, mermaid_thumbnails=False)
    timings["vault_gen"] = time.time() - t0
    print(f"  Phase 4 (vault gen):  {timings['vault_gen']:.2f}s")

    timings["total"] = sum(timings.values())
    timings["video_count"] = len(videos)
    return timings


def _run_api_flow() -> dict:
    """Run the API flow live against YouTube Data API."""
    timings = {}
    run_dir = "vault/runs/benchmark-api"
    _clean_run_dir(run_dir)

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("  SKIP: No YOUTUBE_API_KEY set")
        return {"error": "no api key"}

    channels_path = Path("channels.json")
    if not channels_path.exists():
        print("  SKIP: No channels.json")
        return {"error": "no channels.json"}

    # Phase 1: Scrape via API
    t0 = time.time()
    from yt_catalog.api_scraper import scrape_via_api
    videos = scrape_via_api(max_days=30)  # Last 30 days to match first run window
    timings["scrape"] = time.time() - t0
    print(f"  Phase 1 (API scrape): {timings['scrape']:.1f}s — {len(videos)} videos")

    if not videos:
        print("  ERROR: API returned 0 videos")
        return {"error": "0 videos", **timings}

    # Phase 2: Categorize (API already enriches)
    t0 = time.time()
    for v in videos:
        result = categorize_video(video_to_dict(v))
        v.category = result["category"]
        v.interest_score = result["interest_score"]
        v.tags = result["tags"]
        v.summary = result["summary"]
        v.duration_group = result["duration_group"]
    timings["categorize"] = time.time() - t0
    print(f"  Phase 2 (categorize): {timings['categorize']*1000:.1f}ms")

    # Phase 3: Save + vault gen (skip thumbnails)
    t0 = time.time()
    save_checkpoint(videos, run_dir, phase="categorization")
    generate_vault(videos, run_dir, mermaid_thumbnails=False)
    timings["vault_gen"] = time.time() - t0
    print(f"  Phase 3 (vault gen):  {timings['vault_gen']:.2f}s")

    timings["total"] = sum(timings.values())
    timings["video_count"] = len(videos)
    return timings


def main():
    print("=" * 60)
    print("YT-CATALOG END-TO-END BENCHMARK")
    print("=" * 60)

    # Chrome flow
    print("\n--- Chrome Flow (InnerTube enrichment) ---")
    chrome_timings = _run_chrome_flow()

    # API flow
    print("\n--- API Flow (YouTube Data API v3) ---")
    api_timings = _run_api_flow()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    if "error" not in chrome_timings:
        print(f"\nChrome flow ({chrome_timings['video_count']} videos):")
        print(f"  Scrape (sim):  {chrome_timings['scrape']:.2f}s")
        print(f"  Enrich:        {chrome_timings['enrich']:.1f}s")
        print(f"  Categorize:    {chrome_timings['categorize']*1000:.1f}ms")
        print(f"  Vault gen:     {chrome_timings['vault_gen']:.2f}s")
        print(f"  TOTAL:         {chrome_timings['total']:.1f}s")

    if "error" not in api_timings:
        print(f"\nAPI flow ({api_timings['video_count']} videos):")
        print(f"  Scrape (API):  {api_timings['scrape']:.1f}s")
        print(f"  Categorize:    {api_timings['categorize']*1000:.1f}ms")
        print(f"  Vault gen:     {api_timings['vault_gen']:.2f}s")
        print(f"  TOTAL:         {api_timings['total']:.1f}s")

    if "error" not in chrome_timings and "error" not in api_timings:
        speedup = chrome_timings["total"] / api_timings["total"]
        print(f"\nAPI is {speedup:.1f}x {'faster' if speedup > 1 else 'slower'} than Chrome flow")

    # Save results for comparison
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "chrome": chrome_timings,
        "api": api_timings,
    }
    Path("vault/runs/benchmark_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to vault/runs/benchmark_results.json")

    # Run evals against the chrome benchmark output
    print("\n--- Running evals against chrome benchmark ---")
    # Point evals at the benchmark run
    os.system(f"cd {os.getcwd()} && python -m pytest tests/test_eval.py -v --tb=short 2>&1 | tail -15")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
