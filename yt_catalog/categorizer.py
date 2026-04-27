from __future__ import annotations
import json
import sys

from .models import Video, video_to_dict, extract_json_array
from .config import CATEGORIZER_PROMPT, get_duration_group
from .ai_provider import categorize_with_ai


def build_categorizer_prompt(videos: list[Video]) -> str:
    video_list = json.dumps(
        [{"video_id": v.video_id, "title": v.title, "channel": v.channel,
          "duration_seconds": v.duration_seconds, "description": v.description or "",
          "upload_date": v.upload_date or v.relative_time}
         for v in videos],
        indent=2,
    )
    return CATEGORIZER_PROMPT.format(json_video_list=video_list)


def parse_categorizer_output(raw: str, videos: list[Video]) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return videos

    lookup = {e["video_id"]: e for e in entries if "video_id" in e}

    for v in videos:
        if v.video_id in lookup:
            e = lookup[v.video_id]
            v.category = e.get("category", "general")
            v.interest_score = max(0, min(100, e.get("interest_score", 50)))
            v.tags = e.get("tags", [])
            v.summary = e.get("brief_summary")
        else:
            v.category = "general"
            v.interest_score = 30
        v.duration_group = get_duration_group(v.duration_seconds)
    return videos


def _apply_rule_categorization(videos: list[Video]) -> None:
    """Rule-based categorization fallback (mutates videos in place)."""
    from .rule_categorizer import categorize_video
    for v in videos:
        result = categorize_video(video_to_dict(v))
        v.category = result["category"]
        v.interest_score = result["interest_score"]
        v.tags = result["tags"]
        v.summary = result["summary"]
        v.duration_group = result["duration_group"]


def _categorize_one_batch(batch: list[Video]) -> int:
    """Categorize a single batch (AI, with per-batch rule fallback). Returns the
    batch size. Safe to run concurrently — it only mutates its own videos."""
    raw = categorize_with_ai(build_categorizer_prompt(batch))
    if raw:
        parse_categorizer_output(raw, batch)
    else:
        _apply_rule_categorization(batch)
    return len(batch)


def categorize_and_rank(videos: list[Video], batch_size: int = 40,
                        max_workers: int | None = None) -> list[Video]:
    """Categorize + rank in batches, RUN IN PARALLEL.

    Each batch is an independent AI call (e.g. one `claude --print`), so they run
    concurrently — wall time is roughly the slowest single batch, not the sum.
    A flaky/oversized batch only sinks itself (per-batch rule-based fallback).
    Override the worker count with YT_CATALOG_AI_WORKERS.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from . import ui

    if not videos:
        return videos

    batches = [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]
    total = len(videos)
    if max_workers is None:
        max_workers = int(os.environ.get("YT_CATALOG_AI_WORKERS", "4"))
    max_workers = max(1, min(max_workers, len(batches)))

    note = ("uses AI to categorize — each batch can take a bit; the spinner "
            "keeps moving while it works (it didn't crash)")
    with ui.live_progress(total, "Categorizing", note=note) as prog:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_categorize_one_batch, b) for b in batches]
            for fut in as_completed(futures):
                prog.advance(fut.result())
    return videos
