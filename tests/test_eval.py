"""Eval tests: verify quality of the first production run (2026-03-16).

These tests use vault/runs/2026-03-16/data.json as a golden dataset to assert
that the output meets quality standards. They serve as regression tests for
the full pipeline.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pytest

# Path to the first run data
FIRST_RUN_DATA = Path(__file__).parent.parent / "vault" / "runs" / "2026-03-16" / "data.json"
EXPECTED_VIDEO_COUNT = 232


def _load_first_run():
    """Load and return the first run data."""
    if not FIRST_RUN_DATA.exists():
        pytest.skip(f"First run data not found at {FIRST_RUN_DATA}")
    return json.loads(FIRST_RUN_DATA.read_text())


def _load_videos():
    data = _load_first_run()
    return data["videos"]


# ── Basic data integrity ───────────────────────────────────────────────────────

def test_first_run_has_expected_video_count():
    """The first run should have exactly 232 categorized videos."""
    videos = _load_videos()
    assert len(videos) == EXPECTED_VIDEO_COUNT, (
        f"Expected {EXPECTED_VIDEO_COUNT} videos, got {len(videos)}"
    )


def test_first_run_phase_completed():
    """The first run should be fully completed (categorization phase)."""
    data = _load_first_run()
    assert data["last_completed_phase"] == "categorization", (
        f"Expected 'categorization', got {data['last_completed_phase']!r}"
    )


# ── No shorts remain ──────────────────────────────────────────────────────────

def test_no_shorts_remain():
    """All videos with is_short=True should have been filtered before saving."""
    videos = _load_videos()
    shorts = [v for v in videos if v.get("is_short", False)]
    assert shorts == [], f"Found {len(shorts)} shorts still in data: {[v['video_id'] for v in shorts[:5]]}"


def test_no_videos_under_60_seconds():
    """No video should have duration_seconds < 60 (those are shorts)."""
    videos = _load_videos()
    under_60 = [v for v in videos if v.get("duration_seconds") is not None and v["duration_seconds"] < 60]
    assert under_60 == [], (
        f"Found {len(under_60)} videos under 60s: {[(v['video_id'], v['duration_seconds']) for v in under_60[:5]]}"
    )


# ── No livestreams remain ─────────────────────────────────────────────────────

def test_no_livestreams_remain():
    """The is_live field should not be present (pre-dates the field), or all False if present."""
    videos = _load_videos()
    # First run predates the is_live field addition — it won't have the field.
    # Verify that if is_live is present, none are True.
    live = [v for v in videos if v.get("is_live", False)]
    assert live == [], (
        f"Found {len(live)} livestreams still in data: {[v['video_id'] for v in live[:5]]}"
    )


# ── All videos have required metadata ─────────────────────────────────────────

def test_all_videos_have_category():
    """Every video must have a category assigned."""
    videos = _load_videos()
    missing = [v["video_id"] for v in videos if not v.get("category")]
    assert missing == [], f"Videos missing category: {missing[:10]}"


def test_all_videos_have_interest_score():
    """Every video must have an interest_score assigned."""
    videos = _load_videos()
    missing = [v["video_id"] for v in videos if v.get("interest_score") is None]
    assert missing == [], f"Videos missing interest_score: {missing[:10]}"


def test_all_interest_scores_in_range():
    """All interest scores must be between 0 and 100 inclusive."""
    videos = _load_videos()
    out_of_range = [
        (v["video_id"], v["interest_score"])
        for v in videos
        if v.get("interest_score") is not None and not (0 <= v["interest_score"] <= 100)
    ]
    assert out_of_range == [], f"Out-of-range scores: {out_of_range[:10]}"


def test_all_videos_have_upload_date():
    """Every video should have an upload_date (enriched from InnerTube/API)."""
    videos = _load_videos()
    missing = [v["video_id"] for v in videos if not v.get("upload_date")]
    assert missing == [], f"{len(missing)} videos missing upload_date: {missing[:10]}"


def test_all_videos_have_thumbnail_url():
    """Every video should have a thumbnail_url."""
    videos = _load_videos()
    missing = [v["video_id"] for v in videos if not v.get("thumbnail_url")]
    assert missing == [], f"{len(missing)} videos missing thumbnail_url: {missing[:10]}"


def test_most_videos_have_duration():
    """At least 99% of videos should have a duration_seconds value."""
    videos = _load_videos()
    missing_duration = [v for v in videos if v.get("duration_seconds") is None]
    pct_missing = len(missing_duration) / len(videos) * 100
    assert pct_missing < 1.0, (
        f"{pct_missing:.1f}% of videos missing duration ({len(missing_duration)}/{len(videos)}): "
        f"{[v['video_id'] for v in missing_duration[:5]]}"
    )


# ── Duration groups ───────────────────────────────────────────────────────────

def test_all_videos_have_duration_group():
    """Every video must have a duration_group assigned."""
    videos = _load_videos()
    missing = [v["video_id"] for v in videos if not v.get("duration_group")]
    assert missing == [], f"Videos missing duration_group: {missing[:10]}"


def test_duration_groups_are_valid():
    """All duration_group values must be from known group names.

    'unknown' is permitted for the rare video with no duration data (e.g., the
    one video in the 2026-03-16 run that was missing duration_seconds). The pipeline
    now uses 'long' as the fallback, but legacy data may contain 'unknown'.
    """
    valid_groups = {"super-small", "small", "long", "super-big", "unknown"}
    videos = _load_videos()
    invalid = [
        (v["video_id"], v.get("duration_group"))
        for v in videos
        if v.get("duration_group") not in valid_groups
    ]
    assert invalid == [], f"Invalid duration groups: {invalid[:10]}"


# ── Categories ────────────────────────────────────────────────────────────────

def test_all_categories_are_valid():
    """All category values must be from the known set."""
    valid_cats = {"programming", "tech-news", "comedy", "games", "hardware", "diy-makers", "general", "sleep"}
    videos = _load_videos()
    invalid = [
        (v["video_id"], v.get("category"))
        for v in videos
        if v.get("category") not in valid_cats
    ]
    assert invalid == [], f"Invalid categories: {invalid[:10]}"


def test_multiple_categories_represented():
    """At least 4 different categories should be present in a healthy run."""
    videos = _load_videos()
    categories = {v.get("category") for v in videos if v.get("category")}
    assert len(categories) >= 4, f"Only {len(categories)} categories found: {categories}"


# ── Quality report (informational, always passes) ─────────────────────────────

def test_print_quality_report():
    """Print a quality summary of the first run data. Always passes."""
    data = _load_first_run()
    videos = data["videos"]

    cats: dict[str, int] = {}
    score_sum = 0
    score_count = 0
    no_duration = 0
    no_upload = 0

    for v in videos:
        cat = v.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
        s = v.get("interest_score")
        if s is not None:
            score_sum += s
            score_count += 1
        if v.get("duration_seconds") is None:
            no_duration += 1
        if not v.get("upload_date"):
            no_upload += 1

    avg_score = score_sum / score_count if score_count else 0
    has_is_live = sum(1 for v in videos if "is_live" in v)

    print(f"\n{'='*60}")
    print(f"QUALITY REPORT: vault/runs/2026-03-16/data.json")
    print(f"{'='*60}")
    print(f"  Total videos:       {len(videos)}")
    print(f"  Avg interest score: {avg_score:.1f}")
    print(f"  Missing duration:   {no_duration}")
    print(f"  Missing upload_date:{no_upload}")
    print(f"  Has is_live field:  {has_is_live}/{len(videos)}")
    print(f"\n  By category:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        pct = count / len(videos) * 100
        print(f"    {cat:<15} {count:3d} ({pct:.0f}%)")
    print(f"{'='*60}\n")

    # Always passes — this is just informational
    assert True
