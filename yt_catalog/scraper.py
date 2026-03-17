from .config import SCRAPER_PROMPT
from urllib.parse import urlparse, parse_qs
from .models import Video, extract_json_array
import subprocess
import sys

def build_scraper_prompt(max_days: int | None, max_videos: int | None) -> str:
    limits = []
    if max_days is not None:
        limits.append(f"Stop scrolling when you encounter notifications older than {max_days} days.")
    if max_videos is not None:
        limits.append(f"Stop after collecting {max_videos} video entries.")
    limits_clause = "\n".join(limits) if limits else ""
    return SCRAPER_PROMPT.format(limits_clause=limits_clause)

def _extract_video_id(url: str) -> str | None:
    if "/shorts/" in url:
        return None
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        return parse_qs(parsed.query).get("v", [None])[0]
    return None

def parse_scraper_output(raw: str) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return []
    videos = []
    for entry in entries:
        url = entry.get("url", "")
        if "/shorts/" in url:
            continue
        # Filter livestreams: entries explicitly marked as live
        if entry.get("is_live", False):
            continue
        vid = _extract_video_id(url)
        if not vid:
            continue
        videos.append(Video(
            video_id=vid,
            title=entry.get("title", "Unknown"),
            channel=entry.get("channel", "Unknown"),
            url=url,
            relative_time=entry.get("time", ""),
        ))
    # Deduplicate by video_id
    seen = set()
    unique = []
    for v in videos:
        if v.video_id not in seen:
            seen.add(v.video_id)
            unique.append(v)
    return unique

def scrape_notifications(max_days: int | None = None, max_videos: int | None = None) -> list[Video]:
    prompt = build_scraper_prompt(max_days, max_videos)
    result = subprocess.run(
        ["claude", "--print", "--allowedTools", "mcp__claude-in-chrome__*", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"Scraper failed: {result.stderr}", file=sys.stderr)
        return []
    return parse_scraper_output(result.stdout)
