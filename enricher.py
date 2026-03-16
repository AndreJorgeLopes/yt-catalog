from __future__ import annotations
import subprocess
import sys
import urllib.request
from pathlib import Path

from models import Video, extract_json_array
from config import ENRICHER_PROMPT

def batch_videos(videos: list[Video], batch_size: int = 10) -> list[list[Video]]:
    return [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]

def build_enricher_prompt(batch: list[Video]) -> str:
    video_list = "\n".join(
        f"{i+1}. {v.url}" for i, v in enumerate(batch)
    )
    return ENRICHER_PROMPT.format(video_list=video_list)

def parse_enricher_output(raw: str, batch: list[Video]) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return batch

    lookup = {e["video_id"]: e for e in entries if "video_id" in e}

    for v in batch:
        if v.video_id in lookup:
            e = lookup[v.video_id]
            v.duration_seconds = e.get("duration_seconds")
            v.description = e.get("description")
            v.view_count = e.get("view_count")
            v.like_count = e.get("like_count")
            v.upload_date = e.get("upload_date")
            v.thumbnail_url = e.get("thumbnail_url")
            v.is_short = e.get("is_short", False)
    return batch

def download_thumbnails(videos: list[Video], run_dir: str) -> None:
    thumb_dir = Path(run_dir) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    for v in videos:
        if not v.thumbnail_url:
            continue
        dest = thumb_dir / f"{v.video_id}.jpg"
        try:
            urllib.request.urlretrieve(v.thumbnail_url, str(dest))
            v.thumbnail_path = str(dest)
        except Exception as e:
            print(f"Warning: Failed to download thumbnail for {v.video_id}: {e}", file=sys.stderr)

def enrich_videos(videos: list[Video]) -> list[Video]:
    batches = batch_videos(videos)
    for i, batch in enumerate(batches):
        print(f"Enriching batch {i+1}/{len(batches)} ({len(batch)} videos)...")
        prompt = build_enricher_prompt(batch)
        result = subprocess.run(
            ["claude", "--print", "--allowedTools", "mcp__claude-in-chrome__*", "-p", prompt],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            print(f"Warning: Enrichment batch {i+1} failed: {result.stderr}", file=sys.stderr)
            continue
        parse_enricher_output(result.stdout, batch)
    return videos
