from .config import SCRAPER_PROMPT
from urllib.parse import urlparse, parse_qs
from .models import Video, extract_json_array
import shutil
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

def _report_chrome_failure(result: subprocess.CompletedProcess, *, no_videos: bool = False) -> None:
    """Print a clear, actionable error. The old code hid stdout (where the
    `claude` agent actually reports problems), so failures looked empty."""
    print("", file=sys.stderr)
    if no_videos:
        print("Chrome scraper ran but returned no parseable videos.", file=sys.stderr)
    else:
        print(f"Chrome scraper failed (exit {result.returncode}).", file=sys.stderr)
    err = (result.stderr or "").strip()
    out = (result.stdout or "").strip()
    if err:
        print(f"  stderr: {err[:600]}", file=sys.stderr)
    if out:
        print(f"  output: {out[:600]}", file=sys.stderr)
    print("  Checklist:", file=sys.stderr)
    print("    • Chrome is open and logged into YouTube.", file=sys.stderr)
    print("    • The Claude-in-Chrome extension is connected to a tab.", file=sys.stderr)
    print("    • Sanity check: claude --print --chrome -p 'say hi'", file=sys.stderr)


def scrape_notifications(max_days: int | None = None, max_videos: int | None = None) -> list[Video]:
    if shutil.which("claude") is None:
        print("Error: the `claude` CLI is not on PATH; --source chrome needs it.", file=sys.stderr)
        print("Install Claude Code, or use --source api.", file=sys.stderr)
        return []
    prompt = build_scraper_prompt(max_days, max_videos)
    try:
        result = subprocess.run(
            # --chrome enables the Claude-in-Chrome integration in headless
            # --print mode. WITHOUT it the subprocess has zero chrome tools and
            # the scrape silently fails — which is exactly what used to happen.
            ["claude", "--print", "--chrome", "--allowedTools",
             "mcp__claude-in-chrome__*", "-p", prompt],
            capture_output=True, text=True, timeout=300,
            stdin=subprocess.DEVNULL,  # avoid blocking on inherited terminal stdin
        )
    except subprocess.TimeoutExpired:
        print("Error: chrome scraper timed out after 300s "
              "(is Chrome open and logged into YouTube?).", file=sys.stderr)
        return []
    if result.returncode != 0:
        _report_chrome_failure(result)
        return []
    videos = parse_scraper_output(result.stdout)
    if not videos:
        _report_chrome_failure(result, no_videos=True)
    return videos
