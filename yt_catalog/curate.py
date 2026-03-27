"""Curation state — watched / skipped videos + hidden channels, persisted across runs.

Two per-video states drive the vault:
  - watched: you saw it -> hide everywhere.
  - skipped: you chose not to watch -> hide everywhere AND count as a skip signal
    (so we can rank channels/categories you keep skipping = unsubscribe candidates).

State lives in <data_dir>/catalog_state.json so a video marked in one run stays
hidden in future runs too.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

from .utils import get_data_dir

STATE_FILENAME = "catalog_state.json"
_META_KEYS = ("channel", "channel_id", "category", "title")

# Watchlist checkbox line: "- [x] [Title](https://...watch?v=VIDEOID)".
# We recover the video id from the URL — no hidden HTML marker needed.
_CHECK_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>.)\]")
_VID_RE = re.compile(r"watch\?v=([\w-]+)")


def _state_path() -> Path:
    return get_data_dir() / STATE_FILENAME


def load_state() -> dict:
    p = _state_path()
    d = {}
    if p.exists():
        try:
            d = json.loads(p.read_text())
        except Exception:
            d = {}
    d.setdefault("watched", {})          # video_id -> {channel, channel_id, category, title}
    d.setdefault("skipped", {})          # video_id -> {...}
    d.setdefault("hidden_channels", [])  # channel_id or channel name
    return d


def save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def excluded_video_ids(state: dict) -> set[str]:
    """Video IDs to hide from the vault (watched + skipped)."""
    return set(state.get("watched", {})) | set(state.get("skipped", {}))


def hidden_channels(state: dict) -> set[str]:
    return set(state.get("hidden_channels", []))


def mark(state: dict, video_meta: dict, status: str) -> None:
    """Record a video as 'watched' or 'skipped' (moves it out of the other bucket)."""
    if status not in ("watched", "skipped"):
        return
    vid = video_meta.get("video_id")
    if not vid:
        return
    other = "skipped" if status == "watched" else "watched"
    state.setdefault(other, {}).pop(vid, None)
    state.setdefault(status, {})[vid] = {k: video_meta.get(k) for k in _META_KEYS}


def filter_videos(videos: list, state: dict) -> list:
    """Drop watched/skipped videos and videos from hidden channels."""
    ex = excluded_video_ids(state)
    hc = hidden_channels(state)
    return [
        v for v in videos
        if v.video_id not in ex
        and v.channel not in hc
        and (v.channel_id or "") not in hc
    ]


def channel_skip_stats(state: dict) -> list[dict]:
    """Per-channel watched/skipped tallies, ranked by skips then skip-rate.

    The top of this list = channels whose videos you most often skip = the best
    candidates to unsubscribe / disable notifications for.
    """
    agg: dict[str, dict] = defaultdict(
        lambda: {"channel": "", "channel_id": "", "watched": 0, "skipped": 0})
    for bucket in ("watched", "skipped"):
        for meta in state.get(bucket, {}).values():
            key = meta.get("channel") or meta.get("channel_id") or "?"
            agg[key][bucket] += 1
            agg[key]["channel"] = meta.get("channel") or key
            agg[key]["channel_id"] = meta.get("channel_id") or ""
    rows = []
    for r in agg.values():
        total = r["watched"] + r["skipped"]
        r["total"] = total
        r["skip_pct"] = round(100 * r["skipped"] / total) if total else 0
        rows.append(r)
    rows.sort(key=lambda r: (r["skipped"], r["skip_pct"], r["total"]), reverse=True)
    return rows


def unmark(state: dict, vid: str) -> bool:
    """Remove a video from watched/skipped (revert to unmarked). True if removed."""
    removed = False
    for bucket in ("watched", "skipped"):
        if vid in state.get(bucket, {}):
            state[bucket].pop(vid, None)
            removed = True
    return removed


def parse_marks(md_text: str) -> dict[str, str]:
    """Parse checkbox marks from markdown -> {video_id: status}.

    Video id comes from the line's `watch?v=` URL (no hidden marker). `[x]` ->
    watched, `[-]`/`[~]` -> skipped, `[ ]` -> "none" (used to REVERT a previously
    marked video). Lines without a video URL (continuation lines) are ignored.
    """
    marks: dict[str, str] = {}
    for line in md_text.splitlines():
        m = _CHECK_RE.match(line)
        if not m:
            continue
        vid = _VID_RE.search(line)
        if not vid:
            continue
        ch = m.group("mark").strip().lower()
        if ch == "x":
            marks[vid.group(1)] = "watched"
        elif ch in ("-", "~"):
            marks[vid.group(1)] = "skipped"
        else:  # "[ ]"
            marks[vid.group(1)] = "none"
    return marks


def latest_run() -> Path | None:
    runs = get_data_dir() / "vault" / "runs"
    if not runs.is_dir():
        return None
    dirs = sorted((d for d in runs.iterdir() if (d / "data.json").exists()),
                  key=lambda d: d.name)
    return dirs[-1] if dirs else None


def resolve_run(arg: str | None) -> Path | None:
    """Resolve a run dir from a CLI arg (dir or its data.json), else the latest."""
    if arg:
        p = Path(arg).expanduser()
        if p.is_file():
            return p.parent
        if p.is_dir():
            return p
    return latest_run()


def apply_run_marks(run_path: Path, state: dict):
    """Apply a run's watchlist marks to the (global) state. Returns (applied, cp).

    Reads every *.md in the run dir for checkbox marks, looks up each video's
    metadata in the run's data.json, and records watched/skipped in the global
    catalog state. The state is global on purpose (skip signal accumulates across
    runs); only the marks come from this run.
    """
    from .models import load_checkpoint
    cp = load_checkpoint(str(run_path / "data.json"))
    by_id = {v.video_id: v for v in cp.videos}

    explicit: dict[str, str] = {}   # vid -> watched/skipped (wins over "[ ]")
    cleared: set[str] = set()       # vid seen as "[ ]"
    for md in run_path.glob("*.md"):
        for vid, status in parse_marks(md.read_text(errors="ignore")).items():
            if status in ("watched", "skipped"):
                explicit[vid] = status
            else:
                cleared.add(vid)

    applied = {"watched": 0, "skipped": 0, "reverted": 0}
    for vid, status in explicit.items():
        v = by_id.get(vid)
        meta = {"video_id": vid}
        if v:
            meta.update({"channel": v.channel, "channel_id": v.channel_id,
                         "category": v.category, "title": v.title})
        mark(state, meta, status)
        applied[status] += 1
    for vid in cleared - set(explicit):   # explicit [ ] for a marked video -> revert
        if unmark(state, vid):
            applied["reverted"] += 1
    return applied, cp


def category_skip_stats(state: dict) -> list[dict]:
    """Per-category watched/skipped tallies, ranked by skip-rate."""
    agg: dict[str, dict] = defaultdict(lambda: {"category": "", "watched": 0, "skipped": 0})
    for bucket in ("watched", "skipped"):
        for meta in state.get(bucket, {}).values():
            key = meta.get("category") or "general"
            agg[key][bucket] += 1
            agg[key]["category"] = key
    rows = []
    for r in agg.values():
        total = r["watched"] + r["skipped"]
        r["total"] = total
        r["skip_pct"] = round(100 * r["skipped"] / total) if total else 0
        rows.append(r)
    rows.sort(key=lambda r: (r["skip_pct"], r["skipped"]), reverse=True)
    return rows
