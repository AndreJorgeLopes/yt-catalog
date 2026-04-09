"""Fetch the user's YouTube watch history.

YouTube's public Data API does not expose personal watch history, so we read
youtube.com/feed/history while logged in. The page renders a percent-watched
progress bar per entry, used to apply a "watched enough to count" threshold.

Two paths, web first:

* **Web cookie session (PRIMARY, PAGINATED).** First page from the GET's
  server-rendered ``ytInitialData``, then walk the lazy-load continuations via
  the InnerTube ``browse`` POST signed with a ``SAPISIDHASH`` Authorization
  header (``web_session.sapisidhash`` — the piece that turns the "dead-end" POST
  into a working one). Capped at ``max_pages``; a mid-walk device re-challenge
  just stops the walk and keeps the partial result.
* **Claude-in-Chrome scrape (FALLBACK).** Scrolls the page. Used when the web
  session is unavailable on the first GET (the documented device-bound
  re-challenge) or returns nothing.
"""
from __future__ import annotations
import json
import subprocess
import sys

from .config import HISTORY_PROMPT
from .models import extract_json_array


def _build_history_prompt(since_date: str) -> str:
    # NOTE: use str.replace, not .format — HISTORY_PROMPT embeds JS snippets with
    # literal braces (e.g. scrollIntoView({block: 'end'})) that .format chokes on.
    return HISTORY_PROMPT.replace("{since_date}", since_date)


def parse_history_output(raw: str, min_percent: int) -> set[str]:
    """Parse the chrome agent's JSON output into a set of video IDs watched >= min_percent."""
    entries = extract_json_array(raw)
    if not entries:
        return set()
    watched: set[str] = set()
    for e in entries:
        vid = e.get("video_id")
        if not vid:
            continue
        try:
            pct = int(e.get("percent_watched", 0))
        except (TypeError, ValueError):
            pct = 0
        if pct >= min_percent:
            watched.add(vid)
    return watched


def _find_percent(node) -> int:
    """First ``percentDurationWatched`` integer found anywhere in a subtree (0 if
    none). This is the resume-bar value YouTube renders in ``ytInitialData``."""
    if isinstance(node, dict):
        if "percentDurationWatched" in node:
            try:
                return int(node["percentDurationWatched"])
            except (TypeError, ValueError):
                return 0
        for v in node.values():
            p = _find_percent(v)
            if p:
                return p
    elif isinstance(node, list):
        for x in node:
            p = _find_percent(x)
            if p:
                return p
    return 0


def _harvest_history(node, out: list[dict]) -> None:
    """Collect ``[{video_id, percent_watched}]`` from a /feed/history blob.

    Handles the classic ``videoRenderer`` (videoId + resume-bar in
    ``thumbnailOverlays``) and the newer ``lockupViewModel`` (``contentId`` +
    resume % somewhere in its subtree). Shorts use a different renderer and are
    naturally skipped (no videoId/contentId match).
    """
    if isinstance(node, list):
        for x in node:
            _harvest_history(x, out)
    elif isinstance(node, dict):
        vr = node.get("videoRenderer")
        if isinstance(vr, dict) and vr.get("videoId"):
            out.append({"video_id": vr["videoId"], "percent_watched": _find_percent(vr)})
        lv = node.get("lockupViewModel")
        if isinstance(lv, dict):
            vid = lv.get("contentId")
            if isinstance(vid, str) and len(vid) == 11:
                out.append({"video_id": vid, "percent_watched": _find_percent(lv)})
        for v in node.values():
            _harvest_history(v, out)


def parse_history_initial_data(data: dict, min_percent: int) -> set[str]:
    """Video IDs watched >= ``min_percent`` from a /feed/history ``ytInitialData``.

    De-dupes by id keeping the max observed percent (an id can appear in more
    than one renderer)."""
    rows: list[dict] = []
    _harvest_history(data, rows)
    best: dict[str, int] = {}
    for r in rows:
        vid = r["video_id"]
        best[vid] = max(best.get(vid, 0), r["percent_watched"])
    return {vid for vid, pct in best.items() if pct >= min_percent}


def fetch_watched_ids_web(min_percent: int = 50, max_pages: int = 25) -> set[str] | None:
    """Watch history via the cookie web session, paginated.

    First page from the GET's ``ytInitialData``, then walks the lazy-load
    continuations via the SAPISIDHASH-signed InnerTube ``browse`` POST (the
    headless equivalent of scrolling). Stops at ``max_pages`` (cost + the doc's
    "keep frequency low" guidance) or when tokens run out; a mid-walk
    re-challenge breaks the loop and keeps the partial result.

    Returns the watched-id set, or None to signal the caller to fall back to
    chrome (SessionError on the very first GET / parse miss). Never raises.

    Over-collecting watched ids is safe: the set only DROPS videos the user has
    actually watched, so no since_date cutoff is needed here.
    """
    try:
        from . import web_session
        # reextract=False: run uses only the `yt-catalog login` token, never a
        # yt-dlp --cookies-from-browser grab.
        data, html, cookies = web_session.get_page("/feed/history", reextract=False)
    except Exception as e:  # SessionError, URLError, JSON errors, yt-dlp missing
        print(f"  Web history read unavailable ({type(e).__name__}: {e}).", file=sys.stderr)
        return None

    rows: list[dict] = []
    _harvest_history(data, rows)
    client_version = web_session.innertube_client_version(html)
    token = web_session.find_continuation_token(data)
    pages = 1
    while token and pages < max_pages:
        try:
            nxt = web_session.innertube_continuation(token, cookies, client_version)
        except Exception:
            break  # device re-challenge / network — keep what we have
        before = len(rows)
        _harvest_history(nxt, rows)
        token = web_session.find_continuation_token(nxt)
        pages += 1
        if len(rows) == before and not token:
            break

    if not rows:
        return None

    best: dict[str, int] = {}
    for r in rows:
        vid = r["video_id"]
        best[vid] = max(best.get(vid, 0), r["percent_watched"])
    ids = {vid for vid, pct in best.items() if pct >= min_percent}
    print(f"  Watch history via cookie web session: {len(ids)} watched "
          f">= {min_percent}% across {pages} page(s).", file=sys.stderr)
    return ids if ids else None


def fetch_watched_ids(since_date: str, min_percent: int = 50, timeout: int = 600) -> set[str]:
    """Return the set of video IDs the user has watched at least `min_percent`% of,
    with watch timestamps on or after `since_date` (ISO 8601 date string).

    Web cookie session first (paginated via signed InnerTube continuation);
    falls back to the Claude-in-Chrome scrape when the web session is
    unavailable. Returns an empty set if both fail.
    """
    web_ids = fetch_watched_ids_web(min_percent)
    if web_ids is not None:
        return web_ids

    prompt = _build_history_prompt(since_date)
    try:
        result = subprocess.run(
            # --chrome is required to expose the Claude-in-Chrome tools in
            # headless --print mode; without it the subprocess has no browser.
            ["claude", "--print", "--chrome", "--allowedTools",
             "mcp__claude-in-chrome__*", "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,  # avoid blocking on inherited terminal stdin
        )
    except subprocess.TimeoutExpired:
        print("Warning: history scraper timed out; skipping watch filter.", file=sys.stderr)
        return set()
    except FileNotFoundError:
        print("Warning: `claude` CLI not found; skipping watch filter.", file=sys.stderr)
        return set()

    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        print(f"Warning: history scraper failed (exit {result.returncode}): {detail[:300]}", file=sys.stderr)
        print("  (Chrome open + logged into YouTube? Try: claude --print --chrome -p 'hi')", file=sys.stderr)
        return set()

    return parse_history_output(result.stdout, min_percent)
