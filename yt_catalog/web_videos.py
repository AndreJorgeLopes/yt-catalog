"""Recent uploads from the authenticated subscriptions feed (/feed/subscriptions).

A quota-free video source: the logged-in subscriptions feed server-renders recent
uploads into ``ytInitialData`` (one GET, like the bell page). A richer alternative
to the RSS path and to the Chrome notification-dropdown scrape, usable as a
rate-limit fallback. Scraped fields are minimal — full metadata (duration, views,
short/live flags) is filled in afterward by the stateless InnerTube enrichment,
exactly like the chrome path.

PRIMARY/FALLBACK: this is the body of ``--source web``. ``web_session`` raises
``SessionError`` on the documented device-bound re-challenge; the caller (run.py)
catches it and falls back to chrome.
"""
from __future__ import annotations

from . import web_session
from .models import Video

_WATCH = "https://www.youtube.com/watch?v="


def _text(node) -> str:
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return node["simpleText"]
    if "runs" in node:
        return "".join(r.get("text", "") for r in node["runs"])
    return ""


def _byline(vr: dict) -> tuple[str, str | None]:
    """(channel_title, channel_id) from a videoRenderer's byline."""
    by = vr.get("longBylineText") or vr.get("ownerText") or {}
    title = _text(by)
    cid = None
    for run in by.get("runs", []) if isinstance(by, dict) else []:
        nav = (run.get("navigationEndpoint") or {}).get("browseEndpoint") or {}
        bid = nav.get("browseId")
        if isinstance(bid, str) and bid.startswith("UC"):
            cid = bid
            break
    return title, cid


def parse_subscriptions_feed(data: dict, max_videos: int | None = None) -> list[Video]:
    """Extract recent uploads from a /feed/subscriptions ``ytInitialData`` blob.

    Pure function. De-dupes by video id, preserves feed order (newest first).
    """
    rows: list[dict] = []

    def harvest(node):
        if isinstance(node, list):
            for x in node:
                harvest(x)
        elif isinstance(node, dict):
            vr = node.get("videoRenderer")
            if isinstance(vr, dict) and vr.get("videoId"):
                rows.append(vr)
            for v in node.values():
                harvest(v)

    harvest(data)

    out: list[Video] = []
    seen: set[str] = set()
    for vr in rows:
        vid = vr["videoId"]
        if vid in seen:
            continue
        seen.add(vid)
        channel, cid = _byline(vr)
        out.append(Video(
            video_id=vid,
            title=_text(vr.get("title")),
            channel=channel,
            url=f"{_WATCH}{vid}",
            relative_time=_text(vr.get("publishedTimeText")),
            channel_id=cid,
        ))
        if max_videos and len(out) >= max_videos:
            break
    return out


def scrape_via_web(max_videos: int | None = None, **kw) -> list[Video]:
    """Recent uploads from the authenticated subscriptions feed.

    Raises ``web_session.SessionError`` when the session is unusable — the caller
    falls back to chrome. Keyword args pass through to
    ``web_session.get_initial_data`` (``browser``, ``cookie_file``, ``timeout``).
    """
    data = web_session.get_initial_data("/feed/subscriptions", **kw)
    return parse_subscriptions_feed(data, max_videos=max_videos)
