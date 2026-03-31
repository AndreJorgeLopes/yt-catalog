"""Tests for api_scraper module — unit tests that don't make real API calls."""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from yt_catalog.api_scraper import (
    _parse_iso_duration,
    _best_thumbnail,
    _get_subscribed_channel_ids,
    _get_video_details,
    scrape_via_api,
)


# ── _parse_iso_duration ───────────────────────────────────────────────────────

def test_parse_iso_duration_minutes_seconds():
    assert _parse_iso_duration("PT12M34S") == 754

def test_parse_iso_duration_hours_minutes_seconds():
    assert _parse_iso_duration("PT1H2M3S") == 3723

def test_parse_iso_duration_seconds_only():
    assert _parse_iso_duration("PT45S") == 45

def test_parse_iso_duration_minutes_only():
    assert _parse_iso_duration("PT10M") == 600

def test_parse_iso_duration_zero_returns_none():
    """A zero-duration video is a livestream — should return None."""
    assert _parse_iso_duration("PT0S") is None

def test_parse_iso_duration_p0d_returns_none():
    """P0D is used for active livestreams."""
    assert _parse_iso_duration("P0D") is None

def test_parse_iso_duration_empty_returns_none():
    assert _parse_iso_duration("") is None

def test_parse_iso_duration_none_returns_none():
    assert _parse_iso_duration(None) is None

def test_parse_iso_duration_invalid_returns_none():
    assert _parse_iso_duration("not-a-duration") is None

def test_parse_iso_duration_hours_only():
    assert _parse_iso_duration("PT2H") == 7200


# ── _best_thumbnail ────────────────────────────────────────────────────────────

def test_best_thumbnail_prefers_maxres():
    thumbnails = {
        "default": {"url": "https://img/default.jpg"},
        "medium": {"url": "https://img/medium.jpg"},
        "high": {"url": "https://img/high.jpg"},
        "maxres": {"url": "https://img/maxres.jpg"},
    }
    assert _best_thumbnail(thumbnails) == "https://img/maxres.jpg"

def test_best_thumbnail_falls_back_to_high():
    thumbnails = {
        "default": {"url": "https://img/default.jpg"},
        "high": {"url": "https://img/high.jpg"},
    }
    assert _best_thumbnail(thumbnails) == "https://img/high.jpg"

def test_best_thumbnail_empty_returns_empty_string():
    assert _best_thumbnail({}) == ""

def test_best_thumbnail_only_default():
    thumbnails = {"default": {"url": "https://img/default.jpg"}}
    assert _best_thumbnail(thumbnails) == "https://img/default.jpg"


# ── _get_subscribed_channel_ids ────────────────────────────────────────────────

def test_get_subscribed_channel_ids_from_list(tmp_path, monkeypatch):
    channels_file = tmp_path / "channels.json"
    channels_file.write_text(json.dumps(["UC123", "UC456"]))
    monkeypatch.chdir(tmp_path)
    ids = _get_subscribed_channel_ids()
    assert ids == ["UC123", "UC456"]

def test_get_subscribed_channel_ids_from_dict(tmp_path, monkeypatch):
    channels_file = tmp_path / "channels.json"
    channels_file.write_text(json.dumps({"Chan A": "UC111", "Chan B": "UC222"}))
    monkeypatch.chdir(tmp_path)
    ids = _get_subscribed_channel_ids()
    assert set(ids) == {"UC111", "UC222"}

def test_get_subscribed_channel_ids_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = _get_subscribed_channel_ids()
    assert ids == []


# ── scrape_via_api ─────────────────────────────────────────────────────────────

def test_scrape_via_api_no_channels_returns_empty(tmp_path, monkeypatch, capsys):
    """Returns empty list and prints message when no channel IDs found."""
    monkeypatch.chdir(tmp_path)
    result = scrape_via_api()
    assert result == []
    captured = capsys.readouterr()
    assert "channels.json" in captured.err


def _make_playlist_item(video_id: str, published: str = "2026-03-15T10:00:00Z") -> dict:
    return {
        "snippet": {"publishedAt": published},
        "contentDetails": {"videoId": video_id},
    }


def _make_video_api_item(video_id: str, duration: str = "PT10M", is_live: bool = False) -> dict:
    item = {
        "id": video_id,
        "snippet": {
            "title": f"Video {video_id}",
            "channelTitle": "Test Channel",
            "description": "A test description",
            "publishedAt": "2026-03-15T10:00:00Z",
            "thumbnails": {
                "high": {"url": f"https://img/{video_id}/high.jpg"},
                "maxres": {"url": f"https://img/{video_id}/maxres.jpg"},
            },
        },
        "contentDetails": {"duration": duration},
        "statistics": {"viewCount": "1000"},
    }
    if is_live:
        item["liveStreamingDetails"] = {"actualStartTime": "2026-03-15T10:00:00Z"}
    return item


def test_scrape_via_api_filters_shorts_and_live(tmp_path, monkeypatch):
    """API scraper filters out shorts (<60s) and livestreams."""
    channels_file = tmp_path / "channels.json"
    channels_file.write_text(json.dumps(["UC_TEST"]))
    monkeypatch.chdir(tmp_path)

    # Channel uploads now come from the RSS feed (no API quota); only the
    # videos.list details call still goes through _api_get.
    rss_entries = [
        {"video_id": "normal1", "published": "2026-03-15T10:00:00Z"},
        {"video_id": "short1", "published": "2026-03-15T10:00:00Z"},
        {"video_id": "live1", "published": "2026-03-15T10:00:00Z"},
    ]
    videos_response = {"items": [
        _make_video_api_item("normal1", duration="PT10M"),     # 600s — normal
        _make_video_api_item("short1", duration="PT30S"),      # 30s — short
        _make_video_api_item("live1", duration="P0D", is_live=True),  # live
    ]}

    def mock_api_get(endpoint, params):
        return videos_response if endpoint == "videos" else {}

    with patch("yt_catalog.api_scraper._fetch_channel_rss", return_value=rss_entries), \
         patch("yt_catalog.api_scraper._api_get", side_effect=mock_api_get), \
         patch("yt_catalog.api_scraper._get_api_key", return_value="fake-key"):
        result = scrape_via_api()

    assert len(result) == 1
    assert result[0].video_id == "normal1"
    assert result[0].is_short is False
    assert result[0].is_live is False


# ── scrape_recent_via_rss ───────────────────────────────────────────────────────

def test_scrape_recent_via_rss_sorts_by_recency_and_caps(tmp_path, monkeypatch):
    """RSS-by-recency keeps the newest N across channels, returns Video stubs."""
    from yt_catalog.api_scraper import scrape_recent_via_rss
    (tmp_path / "channels.json").write_text(json.dumps(["UC_A", "UC_B"]))
    monkeypatch.chdir(tmp_path)
    feeds = {
        "UC_A": [
            {"video_id": "a_old", "published": "2026-01-01T00:00:00Z", "title": "A old", "channel": "A"},
            {"video_id": "a_new", "published": "2026-03-01T00:00:00Z", "title": "A new", "channel": "A"},
        ],
        "UC_B": [
            {"video_id": "b_mid", "published": "2026-02-01T00:00:00Z", "title": "B mid", "channel": "B"},
        ],
    }
    with patch("yt_catalog.api_scraper._fetch_channel_rss",
               side_effect=lambda cid, cutoff_date=None: feeds[cid]):
        result = scrape_recent_via_rss(max_videos=2)

    assert [v.video_id for v in result] == ["a_new", "b_mid"]  # newest first, capped to 2
    assert result[0].title == "A new"
    assert result[0].channel == "A"
    assert result[0].url == "https://www.youtube.com/watch?v=a_new"


def test_scrape_via_api_backfills_saturated_channels(tmp_path, monkeypatch):
    """A channel whose RSS feed is full (>=15 after cutoff) gets backfilled from
    the uploads playlist so we don't miss older-but-still-new uploads."""
    from yt_catalog.api_scraper import RSS_FEED_CAP
    (tmp_path / "channels.json").write_text(json.dumps(["UCsaturated0000000000", "UCsmall00000000000000"]))
    monkeypatch.chdir(tmp_path)

    rss = {
        "UCsaturated0000000000": [
            {"video_id": f"s{i}", "published": "2026-06-10T00:00:00Z", "title": "t", "channel": "c"}
            for i in range(RSS_FEED_CAP)
        ],
        "UCsmall00000000000000": [
            {"video_id": "small1", "published": "2026-06-10T00:00:00Z", "title": "t", "channel": "c"},
        ],
    }
    backfill = [{"video_id": f"extra{i}", "published": "2026-06-01T00:00:00Z"} for i in range(5)]
    all_ids = [f"s{i}" for i in range(RSS_FEED_CAP)] + ["small1"] + [f"extra{i}" for i in range(5)]
    videos_items = {"items": [_make_video_api_item(v, duration="PT10M") for v in all_ids]}

    def mock_api_get(endpoint, params):
        return videos_items if endpoint == "videos" else {}

    with patch("yt_catalog.api_scraper._fetch_channel_rss", side_effect=lambda cid, cutoff=None: rss[cid]), \
         patch("yt_catalog.api_scraper._get_recent_playlist_items", return_value=backfill), \
         patch("yt_catalog.api_scraper._api_get", side_effect=mock_api_get), \
         patch("yt_catalog.api_scraper._get_api_key", return_value="k"):
        result = scrape_via_api(since_date="2026-05-01T00:00:00Z")

    ids = {v.video_id for v in result}
    assert "extra0" in ids and "extra4" in ids   # backfilled uploads included
    assert "s0" in ids and "small1" in ids
