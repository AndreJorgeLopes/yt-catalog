"""Tests for run_state module — watermark tracking, daily median, incremental runs."""
import json
from datetime import date

import pytest

from yt_catalog.run_state import (
    _load_state, _save_state, get_last_video_date, get_last_run_video_ids,
    get_daily_median, get_estimated_new_videos, is_first_run, update_after_run,
    STATE_FILE,
)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    fake_state = tmp_path / "vault" / "run_state.json"
    monkeypatch.setattr("yt_catalog.run_state.STATE_FILE", fake_state)
    return fake_state


def test_is_first_run_true():
    assert is_first_run() is True


def test_is_first_run_false(isolate_state):
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    isolate_state.write_text(json.dumps({"last_video_date": "2026-03-16T00:00:00Z"}))
    assert is_first_run() is False


def test_get_last_video_date_none():
    assert get_last_video_date() is None


def test_get_last_video_date(isolate_state):
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    isolate_state.write_text(json.dumps({"last_video_date": "2026-03-16T12:00:00Z"}))
    assert get_last_video_date() == "2026-03-16T12:00:00Z"


def test_daily_median_default():
    assert get_daily_median() == 15.0


def test_daily_median_with_data(isolate_state):
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    isolate_state.write_text(json.dumps({"daily_video_counts": [5, 10, 15, 20, 25]}))
    assert get_daily_median() == 15.0


def test_estimated_new_videos_first_run():
    assert get_estimated_new_videos(None) == 500


def test_estimated_new_videos_incremental():
    estimate = get_estimated_new_videos("2026-03-15T00:00:00Z")
    # 2 days * 15 (default median) * 1.5 buffer = 45
    assert estimate >= 10
    assert estimate < 500


def test_update_after_run_first_run(isolate_state):
    videos = [
        {"video_id": "abc", "upload_date": "2026-03-16T10:00:00Z"},
        {"video_id": "def", "upload_date": "2026-03-17T10:00:00Z"},
    ]
    stats = update_after_run(videos, "2026-03-17")
    assert stats["is_first_run"] is True
    assert stats["total_videos"] == 2
    assert stats["new_videos"] == 2
    assert stats["newest_video_date"] == "2026-03-17T10:00:00Z"


def test_update_after_run_incremental(isolate_state):
    # Simulate first run
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    isolate_state.write_text(json.dumps({
        "last_video_date": "2026-03-16T10:00:00Z",
        "last_video_ids": ["abc", "def"],
        "last_run_date": "2026-03-16",
        "daily_video_counts": [10],
    }))
    # Second run with overlap
    videos = [
        {"video_id": "def", "upload_date": "2026-03-16T10:00:00Z"},  # overlap
        {"video_id": "ghi", "upload_date": "2026-03-17T10:00:00Z"},  # new
        {"video_id": "jkl", "upload_date": "2026-03-17T12:00:00Z"},  # new
    ]
    stats = update_after_run(videos, "2026-03-17")
    assert stats["is_first_run"] is False
    assert stats["total_videos"] == 3
    assert stats["new_videos"] == 2
    assert stats["overlap_with_previous"] == 1


def test_get_last_run_video_ids(isolate_state):
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    isolate_state.write_text(json.dumps({"last_video_ids": ["a", "b", "c"]}))
    ids = get_last_run_video_ids()
    assert ids == {"a", "b", "c"}
