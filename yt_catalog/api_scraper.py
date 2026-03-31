"""YouTube Data API v3 scraper — fetches recent uploads from subscriptions."""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Video
from .utils import retry, progress_bar

API_BASE = "https://www.googleapis.com/youtube/v3"

# Per-channel RSS feed of recent uploads. NOT subject to the Data API quota —
# this is how we enumerate new videos for 1000+ channels without burning units.
# Returns up to ~15 newest entries per channel as Atom XML.
RSS_FEED_BASE = "https://www.youtube.com/feeds/videos.xml?channel_id="
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_YT_NS = "{http://www.youtube.com/xml/schemas/2015}"


class QuotaExceededError(Exception):
    """Raised when the YouTube Data API returns a 403 quotaExceeded error.

    Retrying is pointless (the daily quota is gone until midnight Pacific), so
    callers treat this as a hard stop rather than a transient failure.
    """


def _http_error_reason(e: urllib.error.HTTPError) -> str:
    """Extract the machine-readable reason from a YouTube API HTTPError body.

    e.g. 'quotaExceeded', 'forbidden', 'accessNotConfigured'. Returns '' if the
    body can't be parsed.
    """
    try:
        body = json.loads(e.read().decode())
        errs = body.get("error", {}).get("errors", [])
        if errs:
            return errs[0].get("reason", "")
    except Exception:
        pass
    return ""


def _print_quota_panel(done: int | None = None, total: int | None = None) -> None:
    """Print a single, clear quota-exhausted panel instead of retry spam."""
    line = "─" * 66
    progress = ""
    if done is not None and total is not None:
        progress = f" (got details for {done}/{total} videos before the cap)"
    print(f"\n{line}", file=sys.stderr)
    print("  ⚠️  YouTube Data API quota exceeded", file=sys.stderr)
    print(f"{line}", file=sys.stderr)
    print(f"  The project's daily quota is spent{progress}.", file=sys.stderr)
    print("  It resets at midnight Pacific (00:00 America/Los_Angeles).", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Options:", file=sys.stderr)
    print("    • Wait for the reset, then re-run (an RSS run costs ~200 units).", file=sys.stderr)
    print("    • Scrape the bell dropdown instead:  yt-catalog run --source chrome", file=sys.stderr)
    print("    • Raise the cap: Google Cloud Console → APIs & Services →", file=sys.stderr)
    print("      YouTube Data API v3 → Quotas → request an increase.", file=sys.stderr)
    print(f"{line}\n", file=sys.stderr)


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        # Try config file
        from .oauth import load_config
        config = load_config()
        key = config.get("api_key", "")
    if not key:
        print("Error: YOUTUBE_API_KEY environment variable not set.", file=sys.stderr)
        print("Get one at: https://console.cloud.google.com/apis/credentials", file=sys.stderr)
        sys.exit(1)
    return key


def _get_auth_headers() -> dict[str, str]:
    """Return OAuth Bearer header if available, else empty dict."""
    try:
        from .oauth import is_authenticated, get_access_token
        if is_authenticated():
            token = get_access_token()
            return {"Authorization": f"Bearer {token}"}
    except Exception:
        pass
    return {}


def _api_get(endpoint: str, params: dict) -> dict:
    """Make a GET request to the YouTube Data API with retry on failure.

    Uses OAuth Bearer token if available, otherwise falls back to API key.
    """
    auth_headers = _get_auth_headers()
    if not auth_headers:
        # Fall back to API key
        api_key = _get_api_key()
        params["key"] = api_key
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    def _do_request():
        req = urllib.request.Request(url)
        for k, v in auth_headers.items():
            req.add_header(k, v)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            # quotaExceeded is terminal until reset — don't waste retries on it.
            if e.code == 403 and _http_error_reason(e) == "quotaExceeded":
                raise QuotaExceededError()
            raise
        return json.loads(resp.read())

    return retry(_do_request, max_retries=3, delay=1, backoff=2,
                 dont_retry=(QuotaExceededError,))


def _fetch_subscriptions_full() -> tuple[list[dict], bool]:
    """Paginate the authenticated channel's subscriptions.

    Returns ([{"id", "title"}], complete). complete=False when not authenticated
    or pagination errored partway, so the caller never treats a partial list as
    the source of truth (and won't overwrite channels.json with a fragment).
    """
    try:
        from .oauth import is_authenticated, get_access_token
        if not is_authenticated():
            return [], False
    except Exception:
        return [], False

    access_token = get_access_token()
    out: list[dict] = []
    page_token = None
    complete = True

    while True:
        params: dict[str, str | int] = {
            "part": "snippet", "mine": "true", "maxResults": 50, "order": "alphabetical",
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"{API_BASE}/subscriptions?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {access_token}")
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception as e:
            print(f"Warning: OAuth subscriptions fetch failed: {e}", file=sys.stderr)
            complete = False
            break
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            cid = sn.get("resourceId", {}).get("channelId")
            if cid:
                out.append({"id": cid, "title": sn.get("title", "")})
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return out, complete


def get_subscriptions_oauth() -> list[str]:
    """Subscribed channel IDs via OAuth (empty on failure)."""
    items, _ = _fetch_subscriptions_full()
    return [it["id"] for it in items]


def load_channel_ids_from_file(path: str) -> list[str]:
    """Read channel IDs from a JSON file in any of the formats we emit/consume:

      - list of ID strings: ["UC...", ...]
      - {name: "UC..."} dict (channels.json)
      - list of objects with id/channelId (e.g. bell_all_channels.json)
    """
    try:
        data = json.loads(Path(path).read_text())
    except Exception:
        return []
    out: list[str] = []
    if isinstance(data, list):
        for x in data:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                out.append(x.get("id") or x.get("channelId") or x.get("channel_id") or "")
    elif isinstance(data, dict):
        out = [v for v in data.values() if isinstance(v, str)]
    return [c for c in out if c and c.startswith("UC")]


def _load_channels_json_ids() -> list[str]:
    """Read channel IDs from channels.json in the current dir (if present)."""
    channels_file = Path.cwd() / "channels.json"
    return load_channel_ids_from_file(str(channels_file)) if channels_file.exists() else []


def _get_subscribed_channel_ids() -> list[str]:
    """Subscriptions are the single source of truth via the OAuth API.

    When the OAuth list comes back COMPLETE, overwrite channels.json with it and
    use it. If the API is unavailable (not authenticated / quota exhausted /
    partial pagination), fall back to the existing channels.json so chrome and
    offline runs still work without corrupting the cached list.
    """
    items, complete = _fetch_subscriptions_full()
    ids = [it["id"] for it in items if it.get("id")]
    if ids and complete:
        mapping = {(it["title"] or it["id"]): it["id"] for it in items if it.get("id")}
        try:
            (Path.cwd() / "channels.json").write_text(
                json.dumps(mapping, indent=2, ensure_ascii=False))
            print(f"  Subscriptions: {len(ids)} channels from the API "
                  f"(channels.json refreshed)", file=sys.stderr)
        except Exception:
            pass
        return ids
    fallback = _load_channels_json_ids()
    if fallback:
        print(f"  Subscriptions: API unavailable, using {len(fallback)} cached "
              f"channels from channels.json", file=sys.stderr)
        return fallback
    return ids


# A channel's RSS feed serves at most this many entries (YouTube cap). If a
# channel posted more than this since the cutoff, RSS alone misses the rest and
# we fall back to the uploads playlist (paginated) for that channel.
RSS_FEED_CAP = 15


def _uploads_playlist_id(channel_id: str) -> str | None:
    """Derive a channel's 'uploads' playlist id without an API call.

    For every standard channel id `UC...`, the uploads playlist is `UU...`
    (verified against channels.list). Returns None for non-standard ids so the
    caller can skip them.
    """
    if channel_id and channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return None


def _get_recent_playlist_items(playlist_id: str, cutoff_date: datetime | None,
                               hard_cap: int = 300) -> list[dict]:
    """Paginate an uploads playlist (newest-first), stopping at cutoff_date.

    Returns [{"video_id", "published"}]. Costs 1 API unit per page. Used only as
    a completeness fallback for channels whose RSS feed was saturated.
    """
    out: list[dict] = []
    page_token: str | None = None
    while len(out) < hard_cap:
        params: dict = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        try:
            data = _api_get("playlistItems", params)
        except QuotaExceededError:
            raise
        except Exception:
            break
        stop = False
        for item in data.get("items", []):
            cd = item.get("contentDetails", {})
            vid = cd.get("videoId")
            published = cd.get("videoPublishedAt", "")
            if not vid:
                continue
            if cutoff_date and published:
                try:
                    if datetime.fromisoformat(published.replace("Z", "+00:00")) < cutoff_date:
                        stop = True  # newest-first: everything past here is older
                        break
                except ValueError:
                    pass
            out.append({"video_id": vid, "published": published})
        if stop:
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out


def _fetch_channel_rss(channel_id: str, cutoff_date: datetime | None = None) -> list[dict]:
    """Fetch a channel's recent uploads via its public RSS feed (no API quota).

    YouTube serves up to ~15 newest uploads per channel as Atom XML at
    feeds/videos.xml?channel_id=<id>. This needs no auth and costs zero Data
    API units, which is what makes scanning 1000+ channels per run feasible.

    Returns a list of {"video_id", "published"} dicts (newest first), dropping
    entries older than cutoff_date when given.
    """
    url = RSS_FEED_BASE + urllib.parse.quote(channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": "yt-catalog/0.1"})
    try:
        raw = urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"Warning: RSS fetch failed for {channel_id}: {e}", file=sys.stderr)
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"Warning: RSS parse failed for {channel_id}: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        vid_el = entry.find(f"{_YT_NS}videoId")
        if vid_el is None or not vid_el.text:
            continue
        pub_el = entry.find(f"{_ATOM_NS}published")
        published = pub_el.text if (pub_el is not None and pub_el.text) else ""
        if cutoff_date and published:
            try:
                if datetime.fromisoformat(published.replace("Z", "+00:00")) < cutoff_date:
                    continue
            except ValueError:
                pass
        title_el = entry.find(f"{_ATOM_NS}title")
        author_el = entry.find(f"{_ATOM_NS}author/{_ATOM_NS}name")
        out.append({
            "video_id": vid_el.text,
            "published": published,
            "title": title_el.text if (title_el is not None and title_el.text) else "Unknown",
            "channel": author_el.text if (author_el is not None and author_el.text) else "Unknown",
        })
    return out


def scrape_recent_via_rss(max_videos: int | None = None, since_date: str | None = None,
                          channel_ids: list[str] | None = None) -> list[Video]:
    """Fetch the most-recent uploads across subscriptions via RSS (no API quota).

    Collects every channel's RSS entries, sorts by publish date (newest first),
    dedups, and keeps the top `max_videos`. Returns Video stubs (id/title/
    channel/url/date) for the InnerTube enrichment phase to flesh out — so this
    path costs zero Data API units and needs no browser. This is the engine
    behind the "tell me a number" / "use the median" notification strategies.
    """
    if channel_ids is None:
        channel_ids = _get_subscribed_channel_ids()
    if not channel_ids:
        print("No channel IDs found. Run 'yt-catalog setup' or 'yt-catalog discover' first.",
              file=sys.stderr)
        return []

    cutoff_date = None
    if since_date:
        try:
            cutoff_date = datetime.fromisoformat(since_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    from concurrent.futures import ThreadPoolExecutor, as_completed

    print(f"  Fetching RSS feeds for {len(channel_ids)} channels (no API quota)...")
    entries: list[dict] = []
    done = 0
    total = len(channel_ids)
    progress_bar(0, total, "RSS ")
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_fetch_channel_rss, c, cutoff_date) for c in channel_ids]
        for fut in as_completed(futures):
            entries.extend(fut.result())
            done += 1
            progress_bar(done, total, "RSS ")

    # Newest first, then dedup by video_id preserving order.
    entries.sort(key=lambda e: e.get("published", ""), reverse=True)
    seen: set[str] = set()
    unique: list[dict] = []
    for e in entries:
        vid = e.get("video_id")
        if vid and vid not in seen:
            seen.add(vid)
            unique.append(e)
    if max_videos:
        unique = unique[:max_videos]

    print(f"  Selected {len(unique)} most-recent videos.")
    return [
        Video(
            video_id=e["video_id"],
            title=e.get("title", "Unknown"),
            channel=e.get("channel", "Unknown"),
            url=f"https://www.youtube.com/watch?v={e['video_id']}",
            relative_time="",
            upload_date=e.get("published", ""),
        )
        for e in unique
    ]


def _get_video_details(video_ids: list[str]) -> dict[str, dict]:
    """Get detailed info for up to 50 videos at once."""
    if not video_ids:
        return {}
    results = {}
    total = len(video_ids)
    # Process in batches of 50 (videos.list id-query max). Kept serial: it's the
    # quota-bearing call with hard-stop-on-quota semantics; ~1 unit/batch.
    progress_bar(0, total, "Details ")
    for i in range(0, total, 50):
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

                title = snippet.get("title", "")
                description = snippet.get("description", "")[:500]

                results[vid] = {
                    "title": title,
                    "channel": snippet.get("channelTitle", ""),
                    "channel_id": snippet.get("channelId", ""),
                    "description": description,
                    "upload_date": snippet.get("publishedAt", ""),
                    "thumbnail_url": _best_thumbnail(snippet.get("thumbnails", {})),
                    "duration_seconds": duration_seconds,
                    "view_count": int(stats.get("viewCount", 0)) if stats.get("viewCount") else 0,
                    "like_count": int(stats.get("likeCount", 0)) if stats.get("likeCount") else None,
                    "is_live": live is not None or duration_seconds is None,
                    "is_short": _is_short_cheap(duration_seconds, title, description),
                }
        except QuotaExceededError:
            # Terminal — let scrape_via_api report it once and stop cleanly.
            raise
        except Exception as e:
            print(f"\nWarning: Failed to get video details for batch: {e}", file=sys.stderr)
        progress_bar(min(i + 50, total), total, "Details ")
    return results


_SHORTS_HASHTAG_RE = re.compile(r'(?i)(?:^|\s|#)#?shorts?\b')

# Hard floor: anything this long or shorter is short-form / not worth
# cataloguing. Set above the 180s Shorts cap to also drop near-short clips, so
# no per-video /shorts/ probe is needed. 225s = 3:45.
MIN_DURATION_SECONDS = 225


def _is_short_cheap(duration_seconds: int | None, title: str, description: str) -> bool:
    """Fast-path shorts detection using only metadata we already have.

    Catches sub-60s always, and 60-180s carrying a #shorts tag. Anything else
    short-form is caught by the MIN_DURATION_SECONDS floor at filter time.
    """
    if duration_seconds is None or duration_seconds <= 0:
        return False
    if duration_seconds < 60:
        return True
    if duration_seconds <= 180:
        blob = f"{title}\n{description[:200]}"
        if _SHORTS_HASHTAG_RE.search(blob):
            return True
    return False


def _is_too_short(duration_seconds: int | None) -> bool:
    """Hard floor: drop anything at/under MIN_DURATION_SECONDS even if not flagged as a Short."""
    if duration_seconds is None or duration_seconds <= 0:
        return False
    return duration_seconds <= MIN_DURATION_SECONDS


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


def fetch_channel_info(channel_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch channel metadata (title + avatar URL) via YouTube channels.list.

    Returns {channel_id: {"title": ..., "avatar_url": ...}}. Empty on failure.
    """
    result: dict[str, dict] = {}
    if not channel_ids:
        return result
    ids = [c for c in channel_ids if c]
    total = len(ids)
    progress_bar(0, total, "Avatars ")
    for i in range(0, total, 50):
        batch = ids[i:i + 50]
        try:
            data = _api_get("channels", {"part": "snippet", "id": ",".join(batch)})
        except Exception as e:
            print(f"\nWarning: channels.list failed for batch: {e}", file=sys.stderr)
            progress_bar(min(i + 50, total), total, "Avatars ")
            continue
        for item in data.get("items", []):
            cid = item.get("id")
            snip = item.get("snippet", {})
            thumbs = snip.get("thumbnails", {})
            avatar = (
                thumbs.get("high", {}).get("url")
                or thumbs.get("medium", {}).get("url")
                or thumbs.get("default", {}).get("url")
                or ""
            )
            if cid:
                result[cid] = {"title": snip.get("title", ""), "avatar_url": avatar}
        progress_bar(min(i + 50, total), total, "Avatars ")
    return result


def scrape_via_api(max_days: int | None = None, max_videos: int | None = None,
                   since_date: str | None = None, channel_ids: list[str] | None = None) -> list[Video]:
    """Scrape recent uploads from subscribed channels via YouTube Data API.

    Args:
        max_days: Only fetch videos from the last N days.
        max_videos: Cap total video count.
        since_date: ISO 8601 date — only fetch videos uploaded after this date.
                    Used for incremental runs (watermark from previous run).
        channel_ids: Explicit channel list (e.g. your bell-on channels). When
                    None, falls back to the merged subscription list.
    """
    if channel_ids is None:
        channel_ids = _get_subscribed_channel_ids()
    if not channel_ids:
        print("No channel IDs found. Create a channels.json file with channel IDs,", file=sys.stderr)
        print("or run with --source chrome first to auto-generate it.", file=sys.stderr)
        return []

    cutoff_date = None
    if since_date:
        try:
            cutoff_date = datetime.fromisoformat(since_date.replace("Z", "+00:00"))
            print(f"  Incremental mode: fetching videos after {since_date}")
        except (ValueError, TypeError):
            pass
    if max_days and not cutoff_date:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)

    # Step 1: Fetch each channel's recent uploads via its RSS feed (parallel,
    # no API quota). RSS serves at most RSS_FEED_CAP entries/channel; channels
    # that hit that cap (i.e. cutoff trimmed nothing) likely posted more than
    # the feed shows, so we record them for an uploads-playlist fallback.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print(f"  Fetching RSS feeds for {len(channel_ids)} channels (no API quota)...")

    all_video_ids: list[str] = []
    empty = 0
    saturated: list[str] = []
    done = 0
    total = len(channel_ids)
    progress_bar(0, total, "RSS ")
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_fetch_channel_rss, cid, cutoff_date): cid for cid in channel_ids}
        for future in as_completed(futures):
            done += 1
            cid = futures[future]
            entries = future.result()
            if not entries:
                empty += 1
            else:
                all_video_ids.extend(e["video_id"] for e in entries if e.get("video_id"))
                if len(entries) >= RSS_FEED_CAP:
                    saturated.append(cid)
            progress_bar(done, total, "RSS ")

    if empty:
        print(f"  Note: {empty}/{total} channels returned no recent uploads.")

    # Completeness fallback: channels whose RSS feed was full likely have more
    # uploads since the cutoff than RSS exposes. Page their uploads playlist.
    if saturated and cutoff_date is not None:
        print(f"  {len(saturated)} channels posted >{RSS_FEED_CAP} videos since the "
              f"cutoff; fetching the rest via the uploads playlist (API)...")
        done = 0
        progress_bar(0, len(saturated), "Backfill ")
        with ThreadPoolExecutor(max_workers=8) as pool:
            def _backfill(cid: str) -> list[str]:
                pl = _uploads_playlist_id(cid)
                if not pl:
                    return []
                return [e["video_id"] for e in _get_recent_playlist_items(pl, cutoff_date)]
            futures = {pool.submit(_backfill, cid): cid for cid in saturated}
            for future in as_completed(futures):
                done += 1
                try:
                    all_video_ids.extend(future.result())
                except QuotaExceededError:
                    _print_quota_panel()
                    return []
                progress_bar(done, len(saturated), "Backfill ")

    # Deduplicate while preserving order
    all_video_ids = list(dict.fromkeys(all_video_ids))
    if max_videos:
        all_video_ids = all_video_ids[:max_videos]

    print(f"  Found {len(all_video_ids)} unique videos. Fetching details...")

    # Step 2: Get full video details (the only quota-bearing step). If the
    # daily quota runs out, stop cleanly with one clear message rather than
    # cataloging a silent fraction of the videos.
    try:
        details = _get_video_details(all_video_ids)
    except QuotaExceededError:
        _print_quota_panel(total=len(all_video_ids))
        return []

    # NOTE: no /shorts/ probe here. Shorts are <=180s and the MIN_DURATION_SECONDS
    # floor below already drops everything under 180s, so probing 60-210s changed
    # essentially nothing while costing one slow HTTP request per ambiguous video
    # (5950+ on a big run). The cheap-check + the 180s floor cover shorts removal.

    # Step 3: Build Video objects, filtering shorts, livestreams, and sub-3min
    videos: list[Video] = []
    shorts_count = 0
    live_count = 0
    too_short_count = 0
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
        if _is_too_short(d["duration_seconds"]):
            too_short_count += 1
            continue
        videos.append(Video(
            video_id=vid,
            title=d["title"],
            channel=d["channel"],
            channel_id=d.get("channel_id", ""),
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

    print(f"  Filtered: {shorts_count} shorts, {live_count} livestreams, {too_short_count} under {MIN_DURATION_SECONDS}s")
    return videos
