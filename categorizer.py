from __future__ import annotations
import json
import subprocess
import sys

from models import Video, extract_json_array
from config import CATEGORIZER_PROMPT, get_duration_group

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
    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"Categorizer failed: {result.stderr}", file=sys.stderr)
        for v in videos:
            v.category = "general"
            v.interest_score = 30
            v.duration_group = get_duration_group(v.duration_seconds)
        return videos
    return parse_categorizer_output(result.stdout, videos)
