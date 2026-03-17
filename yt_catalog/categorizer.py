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


def categorize_and_rank(videos: list[Video]) -> list[Video]:
    prompt = build_categorizer_prompt(videos)
    raw = categorize_with_ai(prompt)
    if raw:
        return parse_categorizer_output(raw, videos)
    # Fallback to rule-based
    from .rule_categorizer import categorize_video
    for v in videos:
        result = categorize_video(video_to_dict(v))
        v.category = result["category"]
        v.interest_score = result["interest_score"]
        v.tags = result["tags"]
        v.summary = result["summary"]
        v.duration_group = result["duration_group"]
    return videos
