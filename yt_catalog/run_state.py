"""Run state persistence — tracks watermarks, daily medians, and run history.

Enables incremental runs: after the first run fetches everything, subsequent
runs only fetch videos uploaded after the last seen video. A rolling daily
median helps estimate how many new videos to expect.
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime, timezone, date
from pathlib import Path

STATE_FILE = Path("vault") / "run_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_last_video_date() -> str | None:
    """Get the upload date of the most recent video from the last run.

    Returns ISO 8601 date string or None if no previous run.
    """
    state = _load_state()
    return state.get("last_video_date")


def get_last_run_video_ids() -> set[str]:
    """Get the set of video IDs from the last run (for dedup across runs)."""
    state = _load_state()
    return set(state.get("last_video_ids", []))


def get_daily_median() -> float:
    """Get the rolling median of videos-per-day.

    Returns the median, or 15.0 as a conservative default if insufficient data.
    """
    state = _load_state()
    daily_counts = state.get("daily_video_counts", [])
    if len(daily_counts) < 2:
        return 15.0  # Conservative default
    return statistics.median(daily_counts)


def get_estimated_new_videos(since_date: str | None = None) -> int:
    """Estimate how many new videos to expect since a given date.

    Uses the daily median * days elapsed. Adds a 50% buffer for safety.
    """
    if not since_date:
        return 500  # First run: get everything

    try:
        last_dt = datetime.fromisoformat(since_date.replace("Z", "+00:00"))
        # Ensure timezone-aware
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 500

    now = datetime.now(timezone.utc)
    days_elapsed = max(1, (now - last_dt).days)
    median = get_daily_median()
    estimate = int(days_elapsed * median * 1.5)  # 50% buffer
    return max(10, estimate)  # At least 10


def is_first_run() -> bool:
    """Check if this is the first run (no previous state)."""
    state = _load_state()
    return "last_video_date" not in state


def update_after_run(videos: list[dict], run_date: str) -> dict:
    """Update run state after a successful run.

    Tracks:
    - last_video_date: upload date of the newest video
    - last_video_ids: set of video IDs for cross-run dedup
    - daily_video_counts: rolling list for median calculation
    - run_history: list of {date, count} for each run

    Returns a summary dict with stats.
    """
    state = _load_state()

    # Find the newest video by upload_date
    dates = []
    for v in videos:
        ud = v.get("upload_date", "")
        if ud:
            dates.append(ud)
    dates.sort(reverse=True)
    newest_date = dates[0] if dates else None

    # Update watermark
    if newest_date:
        state["last_video_date"] = newest_date

    # Update video ID set (keep last 2 runs for overlap detection)
    prev_ids = set(state.get("last_video_ids", []))
    current_ids = [v.get("video_id", "") for v in videos if v.get("video_id")]
    state["last_video_ids"] = current_ids

    # Calculate daily video count
    prev_date_str = state.get("last_run_date")
    if prev_date_str:
        try:
            prev_date = date.fromisoformat(prev_date_str)
            curr_date = date.fromisoformat(run_date)
            days = max(1, (curr_date - prev_date).days)
            new_count = len(set(current_ids) - prev_ids)
            daily_rate = new_count / days
        except (ValueError, TypeError):
            daily_rate = len(videos)
    else:
        # First run — estimate from total / reasonable window
        daily_rate = len(videos) / 30.0  # Assume ~30 days of history

    daily_counts = state.get("daily_video_counts", [])
    daily_counts.append(round(daily_rate, 1))
    # Keep last 30 data points
    state["daily_video_counts"] = daily_counts[-30:]

    # Run history
    history = state.get("run_history", [])
    history.append({"date": run_date, "video_count": len(videos)})
    state["run_history"] = history[-50:]  # Keep last 50 runs

    state["last_run_date"] = run_date

    _save_state(state)

    # Calculate overlap with previous run
    overlap = len(prev_ids & set(current_ids)) if prev_ids else 0

    return {
        "is_first_run": not prev_date_str,
        "newest_video_date": newest_date,
        "total_videos": len(videos),
        "new_videos": len(set(current_ids) - prev_ids) if prev_ids else len(videos),
        "overlap_with_previous": overlap,
        "daily_median": get_daily_median(),
        "estimated_next_run": get_estimated_new_videos(newest_date),
    }
