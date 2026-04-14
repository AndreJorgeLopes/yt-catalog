"""Fetch the notification (bell) channels from youtube.com/feed/channels, with a
weekly cadence so we don't re-scrape every run.

The Data API can't see the notification bell, so a logged-in web read is the only
way to know which channels actually notify you. PRIMARY path is the headless
cookie session (``bell_scraper`` -> ``web_session``); if that fails for any
reason (the documented device-bound re-challenge, stale cookies, no yt-dlp, etc.)
we fall back to the Claude-in-Chrome scrape. Result is cached in
bell_all_channels.json (channel id/title/bell) for the catalog to use as its
scrape source.
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from .config import CHANNELS_PROMPT
from .models import extract_json_array

BELL_FILE = "bell_all_channels.json"
# "bell on" = bell set to ALL (notify on every upload). NOT "personalized":
# Personalized is YouTube's default for most subscriptions, so including it would
# 10x the catalog source. The user's verified bell list (~95 channels) is the
# All-only set, so we match that here for both the web and chrome paths.
_NOTIFY_ON = {"all"}
_REFRESH_DAYS = 7


def load_bell_ids() -> list[str]:
    """Bell-ON channel IDs from the cached file (empty if missing).

    Filters by bell state (``_NOTIFY_ON`` = All-only). This matters because the
    cache file may legitimately hold the FULL subscription dump with every bell
    state (All/Personalized/None) — e.g. a /feed/channels scrape that captured
    everything. Returning every UC id here would silently turn "bell-on only"
    into "all subscriptions". Entries with no ``bell`` field (older All-only
    caches) are kept for back-compat.
    """
    p = Path(BELL_FILE)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    out = []
    for x in data if isinstance(data, list) else []:
        if isinstance(x, dict):
            cid = x.get("id") or ""
            bell = x.get("bell")
            # keep if no bell field (legacy) or bell is notify-on
            if bell is not None and str(bell).strip().lower() not in _NOTIFY_ON:
                continue
        else:
            cid = x or ""
        if isinstance(cid, str) and cid.startswith("UC"):
            out.append(cid)
    return out


def should_fetch_bell(state: dict, *, first_run: bool, force: bool,
                      today: str | None = None) -> bool:
    """Refresh the bell list on first run, on force (flag/--fresh), if the cache
    is missing, or once the cache is >= _REFRESH_DAYS old."""
    if force or first_run or not Path(BELL_FILE).exists():
        return True
    last = state.get("last_bell_fetch")
    if not last:
        return True
    try:
        y, m, d = (int(x) for x in last.split("-"))
        today = today or date.today().isoformat()
        ty, tm, td = (int(x) for x in today.split("-"))
        return (date(ty, tm, td) - date(y, m, d)).days >= _REFRESH_DAYS
    except Exception:
        return True


def _normalize(entries) -> list[dict]:
    """Keep bell-on rows (``_NOTIFY_ON`` = All-only) as ``[{id,title,bell}]``.

    Tolerates either bell casing — the web parser emits lowercase, the chrome
    prompt emits "All"/"Personalized".
    """
    channels = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        cid = (e.get("id") or "").strip()
        bell = (e.get("bell") or "").strip().lower()
        if cid.startswith("UC") and bell in _NOTIFY_ON:
            channels.append({"id": cid, "title": e.get("title", ""), "bell": e.get("bell", "")})
    return channels


def _fetch_bell_web() -> list[dict] | None:
    """Headless cookie path (PRIMARY). Returns notify-on channels, or None to
    signal the caller to fall back to chrome.

    None on ANY failure: the device-bound session re-challenge (SessionError),
    missing yt-dlp/cookies, a network error, or a parse miss. The bell page is a
    single full-render GET, so a logged-in success returns the COMPLETE list —
    an empty result means a parse/auth miss, not "no bells", so we fall back.
    """
    try:
        from . import bell_scraper
        # reextract=False: the run path uses ONLY the token captured by
        # `yt-catalog login` (Option C). It never falls back to a yt-dlp
        # --cookies-from-browser grab (the rotating-session anti-pattern).
        rows = bell_scraper.get_bell_all(reextract=False)   # All-only (see _NOTIFY_ON)
    except Exception as e:  # SessionError, URLError, JSON errors, yt-dlp missing
        print(f"  Web bell read unavailable ({type(e).__name__}: {e}).", file=sys.stderr)
        return None
    channels = _normalize(rows)
    if not channels:
        return None
    print(f"  Read {len(channels)} notify-on channels via the cookie web session.")
    return channels


def _fetch_bell_chrome(timeout: int = 600) -> list[dict] | None:
    """Claude-in-Chrome scrape of /feed/channels (FALLBACK)."""
    if shutil.which("claude") is None:
        print("Error: `claude` CLI not found; cannot fetch bell channels.", file=sys.stderr)
        return None
    try:
        result = subprocess.run(
            ["claude", "--print", "--chrome", "--allowedTools",
             "mcp__claude-in-chrome__*", "-p", CHANNELS_PROMPT],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,  # avoid blocking on inherited terminal stdin
        )
    except subprocess.TimeoutExpired:
        print("Bell-channel fetch timed out (Chrome open + logged in?).", file=sys.stderr)
        return None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:300]
        print(f"Bell-channel fetch failed (exit {result.returncode}): {detail}", file=sys.stderr)
        return None
    return _normalize(extract_json_array(result.stdout))


def fetch_bell_channels(timeout: int = 600) -> list[dict] | None:
    """Notification-on channels [{id,title,bell}] or None (caller keeps cache).

    Web cookie session first; Chrome scrape as automatic fallback.
    """
    web = _fetch_bell_web()
    if web is not None:
        return web
    print("  Falling back to the Chrome scrape for bell channels...", file=sys.stderr)
    return _fetch_bell_chrome(timeout)


def save_bell_channels(channels: list[dict], *, guard: bool = True) -> tuple[bool, int, int]:
    """Save the bell list. Returns (saved, old_count, new_count).

    Guards known-good data: if `guard` and the new scrape is non-empty but less
    than half the existing cached list, it's likely a partial/timed-out scrape —
    write it to `<file>.new` and KEEP the old file instead of clobbering it.
    """
    new_n = len(channels)
    old_n = len(load_bell_ids())
    payload = json.dumps(channels, indent=2, ensure_ascii=False)
    if guard and old_n > 0 and 0 < new_n < old_n * 0.5:
        Path(BELL_FILE + ".new").write_text(payload)
        return False, old_n, new_n
    Path(BELL_FILE).write_text(payload)
    return True, old_n, new_n
