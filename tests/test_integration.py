"""Integration tests: exercises full pipeline with mocked Claude CLI calls and network calls."""
import json
import os
from datetime import date
from unittest.mock import patch, MagicMock

import pytest
from yt_catalog.models import Video, load_checkpoint
from yt_catalog.cataloger import main


MOCK_SCRAPER_OUTPUT = json.dumps([
    {"title": "Python Tutorial", "channel": "CodeAcademy", "url": "https://www.youtube.com/watch?v=py1", "time": "1 day ago"},
    {"title": "ASMR Sleep", "channel": "SleepSounds", "url": "https://www.youtube.com/watch?v=asmr1", "time": "2 days ago"},
    {"title": "Short", "channel": "Shorts", "url": "https://www.youtube.com/shorts/short1", "time": "1 day ago"},
    {"title": "Live Event", "channel": "LiveCh", "url": "https://www.youtube.com/watch?v=live1", "time": "1 day ago", "is_live": True},
])

MOCK_CATEGORIZER_OUTPUT = json.dumps([
    {"video_id": "py1", "category": "programming", "interest_score": 85, "tags": ["python", "tutorial"], "brief_summary": "A beginner Python tutorial"},
    {"video_id": "asmr1", "category": "sleep", "interest_score": 72, "tags": ["asmr", "relaxing"], "brief_summary": "Relaxing sounds for sleeping"},
])


def _make_innertube_response(video_id: str, duration_seconds: int = 300,
                              is_live: bool = False) -> dict:
    return {
        "videoDetails": {
            "videoId": video_id,
            "lengthSeconds": str(duration_seconds),
            "viewCount": "1000",
            "shortDescription": "Test description",
            "isLiveContent": is_live,
            "thumbnail": {
                "thumbnails": [
                    {"url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"},
                ]
            },
        },
        "microformat": {
            "playerMicroformatRenderer": {
                "uploadDate": "2026-03-14",
            }
        },
    }


def _mock_innertube_urlopen(url_request, timeout=None):
    body = json.loads(url_request.data.decode())
    vid = body.get("videoId", "unknown")
    duration = 300
    if vid == "py1":
        duration = 754
    elif vid == "asmr1":
        duration = 3600
    resp_data = _make_innertube_response(vid, duration_seconds=duration)
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(resp_data).encode()
    return mock_resp


def _mock_subprocess(cmd, **kwargs):
    """Single mock for all subprocess.run calls (scraper and categorizer share the same module)."""
    mock = MagicMock()
    mock.returncode = 0
    prompt = cmd[-1] if cmd else ""
    if "notifications" in prompt:
        mock.stdout = MOCK_SCRAPER_OUTPUT
    elif "categorizing" in prompt.lower():
        mock.stdout = MOCK_CATEGORIZER_OUTPUT
    else:
        mock.stdout = "[]"
    return mock


def test_full_pipeline_chrome_source(tmp_path, monkeypatch):
    """Full pipeline with chrome source: shorts and livestreams are filtered."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "runs").mkdir(parents=True)

    # Note: scraper and categorizer both use subprocess, which is the same module object.
    # Patch subprocess.run once at the top level to avoid the second patch overriding the first.
    with patch("subprocess.run", side_effect=_mock_subprocess), \
         patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=_mock_innertube_urlopen), \
         patch("yt_catalog.enricher.urllib.request.urlretrieve"):
        main(["--no-mermaid-thumbnails"])

    run_dir = tmp_path / "vault" / "runs" / date.today().isoformat()
    assert (run_dir / "index.md").exists()
    assert (run_dir / "by-category" / "programming.md").exists()
    assert (run_dir / "by-category" / "sleep.md").exists()
    assert (run_dir / "data.json").exists()

    cp = load_checkpoint(str(run_dir / "data.json"))
    assert cp.last_completed_phase == "categorization"
    # shorts and the live entry from MOCK_SCRAPER_OUTPUT are filtered
    assert len(cp.videos) == 2
    video_ids = {v.video_id for v in cp.videos}
    assert "py1" in video_ids
    assert "asmr1" in video_ids
    assert "live1" not in video_ids

    assert (tmp_path / "vault" / "graph-tags.md").exists()


def test_full_pipeline_filters_livestreams_after_enrichment(tmp_path, monkeypatch):
    """Videos enriched as is_live are removed after enrichment phase."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "runs").mkdir(parents=True)

    scraper_output = json.dumps([
        {"title": "Normal", "channel": "C", "url": "https://www.youtube.com/watch?v=norm1", "time": "1d"},
        {"title": "Will Be Live", "channel": "C", "url": "https://www.youtube.com/watch?v=islive1", "time": "1d"},
    ])

    categorizer_output = json.dumps([
        {"video_id": "norm1", "category": "general", "interest_score": 50, "tags": ["test"], "brief_summary": "Normal"},
    ])

    def mock_subprocess(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        prompt = cmd[-1] if cmd else ""
        if "notifications" in prompt:
            m.stdout = scraper_output
        elif "categorizing" in prompt.lower():
            m.stdout = categorizer_output
        else:
            m.stdout = "[]"
        return m

    def innertube_mock(url_request, timeout=None):
        body = json.loads(url_request.data.decode())
        vid = body.get("videoId")
        is_live = vid == "islive1"
        duration = 0 if is_live else 300
        resp = _make_innertube_response(vid, duration_seconds=duration, is_live=is_live)
        m = MagicMock()
        m.read.return_value = json.dumps(resp).encode()
        return m

    with patch("subprocess.run", side_effect=mock_subprocess), \
         patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=innertube_mock), \
         patch("yt_catalog.enricher.urllib.request.urlretrieve"):
        main(["--no-mermaid-thumbnails"])

    run_dir = tmp_path / "vault" / "runs" / date.today().isoformat()
    cp = load_checkpoint(str(run_dir / "data.json"))
    assert cp.last_completed_phase == "categorization"
    assert len(cp.videos) == 1
    assert cp.videos[0].video_id == "norm1"


def test_full_pipeline_api_source(tmp_path, monkeypatch):
    """Full pipeline with --source api skips chrome scraping and enrichment."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "runs").mkdir(parents=True)

    api_videos = [
        Video(
            video_id="api1",
            title="API Video",
            channel="ApiChannel",
            url="https://www.youtube.com/watch?v=api1",
            relative_time="",
            duration_seconds=600,
            description="From API",
            view_count=5000,
            upload_date="2026-03-14",
            thumbnail_url="https://img/api1.jpg",
        ),
    ]

    categorizer_output = json.dumps([
        {"video_id": "api1", "category": "general", "interest_score": 60, "tags": ["test"], "brief_summary": "API test"},
    ])

    def mock_categorizer(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = categorizer_output
        return m

    with patch("yt_catalog.cataloger.scrape_via_api", return_value=api_videos), \
         patch("yt_catalog.enricher.urllib.request.urlretrieve"), \
         patch("subprocess.run", side_effect=mock_categorizer):
        main(["--source", "api", "--no-mermaid-thumbnails"])

    run_dir = tmp_path / "vault" / "runs" / date.today().isoformat()
    assert (run_dir / "index.md").exists()
    cp = load_checkpoint(str(run_dir / "data.json"))
    assert cp.last_completed_phase == "categorization"
    assert len(cp.videos) == 1
    assert cp.videos[0].video_id == "api1"
