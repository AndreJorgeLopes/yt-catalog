from __future__ import annotations
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .models import Video, extract_json_array
from .config import ENRICHER_PROMPT
from .utils import retry

INNERTUBE_URL = (
    "https://www.youtube.com/youtubei/v1/player"
    "?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
)


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


def _enrich_single_video(v: Video) -> None:
    """Enrich a single video via InnerTube. Modifies the Video in-place."""
    try:
        def _fetch():
            body = json.dumps({
                "context": {"client": {"clientName": "WEB", "clientVersion": "2.20260316.01.00"}},
                "videoId": v.video_id,
            }).encode()
            req = urllib.request.Request(
                INNERTUBE_URL,
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read())

        result = retry(_fetch, max_retries=3, delay=1, backoff=2)
        details = result.get("videoDetails", {})
        micro = result.get("microformat", {}).get("playerMicroformatRenderer", {})

        v.duration_seconds = int(details.get("lengthSeconds", 0)) or None
        v.view_count = int(details.get("viewCount", 0)) or None
        v.description = (details.get("shortDescription", "") or "")[:500]
        v.upload_date = micro.get("uploadDate", micro.get("publishDate", ""))
        v.thumbnail_url = (
            details.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url", "")
        )
        v.is_live = details.get("isLiveContent", False)
        v.is_short = (v.duration_seconds or 0) > 0 and (v.duration_seconds or 0) < 60
        v.channel_id = details.get("channelId")
    except Exception as e:
        print(f"  Warning: Failed to enrich {v.video_id}: {e}", file=sys.stderr)


def enrich_videos_innertube(videos: list[Video], max_workers: int = 10) -> list[Video]:
    """Enrich videos using YouTube's InnerTube player API (no auth needed).

    Uses concurrent threads for speed. InnerTube is stateless (no shared
    browser), so parallel requests are safe.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    done = 0
    total = len(videos)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_enrich_single_video, v): v for v in videos}
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == total:
                print(f"    {done}/{total} enriched...")
            future.result()  # Propagate any unexpected exceptions

    return videos


def enrich_videos_chrome(videos: list[Video]) -> list[Video]:
    """Enrich videos using Chrome via claude --print subprocess (legacy)."""
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


# Default enrichment uses InnerTube
def enrich_videos(videos: list[Video]) -> list[Video]:
    """Enrich videos using the InnerTube player API (default)."""
    return enrich_videos_innertube(videos)
