"""YouTube Data API v3 scraper — fetches recent uploads from subscriptions."""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

from models import Video
from utils import retry

API_BASE = "https://www.googleapis.com/youtube/v3"


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("Error: YOUTUBE_API_KEY environment variable not set.", file=sys.stderr)
        print("Get one at: https://console.cloud.google.com/apis/credentials", file=sys.stderr)
        sys.exit(1)
    return key


def _api_get(endpoint: str, params: dict) -> dict:
    """Make a GET request to the YouTube Data API with retry on failure."""
    api_key = _get_api_key()
    params["key"] = api_key
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    def _do_request():
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())

    return retry(_do_request, max_retries=3, delay=1, backoff=2)


def _get_subscribed_channel_ids() -> list[str]:
    """Get channel IDs from channels.json (populated by chrome runs)."""
    channels_file = os.path.join(os.path.dirname(__file__), "channels.json")
    if os.path.exists(channels_file):
        with open(channels_file) as f:
            data = json.load(f)
        # Support both list of IDs and dict of {name: id}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [v for v in data.values() if v]
    return []


def _get_channel_uploads_playlist(channel_id: str) -> str | None:
    """Get the 'uploads' playlist ID for a channel."""
    try:
        data = _api_get("channels", {
            "part": "contentDetails",
            "id": channel_id,
        })
        items = data.get("items", [])
        if items:
            return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"Warning: Failed to get uploads playlist for {channel_id}: {e}", file=sys.stderr)
    return None


def _get_recent_playlist_items(playlist_id: str, max_results: int = 5) -> list[dict]:
    """Get recent items from a playlist."""
    try:
        data = _api_get("playlistItems", {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(max_results, 50),
        })
        return data.get("items", [])
    except Exception as e:
        print(f"Warning: Failed to get playlist items for {playlist_id}: {e}", file=sys.stderr)
    return []


def _get_video_details(video_ids: list[str]) -> dict[str, dict]:
    """Get detailed info for up to 50 videos at once."""
    if not video_ids:
        return {}
    results = {}
    # Process in batches of 50
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        try:
            data = _api_get("videos", {
                "part": "snippet,contentDetails,statistics,liveStreamingDetails",
                "id": ",".join(batch),
            })
            for item in data.get("items", []):
                vid = item["id"]
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                stats = item.get("statistics", {})
                live = item.get("liveStreamingDetails")

                # Parse duration (ISO 8601: PT1H2M3S)
                duration_str = content.get("duration", "PT0S")
                duration_seconds = _parse_iso_duration(duration_str)

                results[vid] = {
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "description": snippet.get("description", "")[:500],
                    "upload_date": snippet.get("publishedAt", ""),
                    "thumbnail_url": _best_thumbnail(snippet.get("thumbnails", {})),
                    "duration_seconds": duration_seconds,
                    "view_count": int(stats.get("viewCount", 0)) if stats.get("viewCount") else 0,
                    "like_count": int(stats.get("likeCount", 0)) if stats.get("likeCount") else None,
                    "is_live": live is not None or duration_seconds is None,
                    "is_short": duration_seconds is not None and 0 < duration_seconds < 60,
                }
        except Exception as e:
            print(f"Warning: Failed to get video details for batch: {e}", file=sys.stderr)
    return results


def _parse_iso_duration(duration: str) -> int | None:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds. Returns None for livestreams."""
    if not duration or duration == "P0D":
        return None  # Likely a livestream
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return None
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    total = h * 3600 + m * 60 + s
    return total if total > 0 else None


def _best_thumbnail(thumbnails: dict) -> str:
    """Get highest resolution thumbnail URL."""
    for key in ("maxres", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url", "")
    return ""


def scrape_via_api(max_days: int | None = None, max_videos: int | None = None) -> list[Video]:
    """Scrape recent uploads from subscribed channels via YouTube Data API."""
    channel_ids = _get_subscribed_channel_ids()
    if not channel_ids:
        print("No channel IDs found. Create a channels.json file with channel IDs,", file=sys.stderr)
        print("or run with --source chrome first to auto-generate it.", file=sys.stderr)
        return []

    cutoff_date = None
    if max_days:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)

    # Step 1: Get uploads playlist for each channel
    print(f"  Fetching upload playlists for {len(channel_ids)} channels...")
    all_video_ids: list[str] = []
    for i, cid in enumerate(channel_ids):
        playlist_id = _get_channel_uploads_playlist(cid)
        if not playlist_id:
            continue
        items = _get_recent_playlist_items(playlist_id, max_results=5)
        for item in items:
            vid = item.get("contentDetails", {}).get("videoId")
            published = item.get("snippet", {}).get("publishedAt", "")
            if vid:
                if cutoff_date and published:
                    try:
                        pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        if pub_dt < cutoff_date:
                            continue
                    except ValueError:
                        pass
                all_video_ids.append(vid)
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(channel_ids)} channels processed...")

    # Deduplicate while preserving order
    all_video_ids = list(dict.fromkeys(all_video_ids))
    if max_videos:
        all_video_ids = all_video_ids[:max_videos]

    print(f"  Found {len(all_video_ids)} unique videos. Fetching details...")

    # Step 2: Get full video details
    details = _get_video_details(all_video_ids)

    # Step 3: Build Video objects, filtering shorts and livestreams
    videos: list[Video] = []
    shorts_count = 0
    live_count = 0
    for vid in all_video_ids:
        d = details.get(vid)
        if not d:
            continue
        if d["is_short"]:
            shorts_count += 1
            continue
        if d["is_live"]:
            live_count += 1
            continue
        videos.append(Video(
            video_id=vid,
            title=d["title"],
            channel=d["channel"],
            url=f"https://www.youtube.com/watch?v={vid}",
            relative_time="",
            duration_seconds=d["duration_seconds"],
            description=d["description"],
            view_count=d["view_count"],
            like_count=d["like_count"],
            upload_date=d["upload_date"],
            thumbnail_url=d["thumbnail_url"],
            is_short=False,
            is_live=False,
        ))

    print(f"  Filtered: {shorts_count} shorts, {live_count} livestreams")
    return videos
