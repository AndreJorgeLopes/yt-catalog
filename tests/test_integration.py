"""Integration test: exercises full pipeline with mocked Claude CLI calls."""
import json
import os
from datetime import date
from unittest.mock import patch, MagicMock
from models import load_checkpoint
from cataloger import main

MOCK_SCRAPER_OUTPUT = json.dumps([
    {"title": "Python Tutorial", "channel": "CodeAcademy", "url": "https://www.youtube.com/watch?v=py1", "time": "1 day ago"},
    {"title": "ASMR Sleep", "channel": "SleepSounds", "url": "https://www.youtube.com/watch?v=asmr1", "time": "2 days ago"},
    {"title": "Short", "channel": "Shorts", "url": "https://www.youtube.com/shorts/short1", "time": "1 day ago"},
])

MOCK_ENRICHER_OUTPUT = json.dumps([
    {"video_id": "py1", "duration_seconds": 754, "description": "Learn Python basics", "view_count": 12000, "like_count": 500, "upload_date": "2026-03-15", "thumbnail_url": "https://i.ytimg.com/vi/py1/maxres.jpg", "is_short": False},
    {"video_id": "asmr1", "duration_seconds": 3600, "description": "Relaxing sounds for sleep", "view_count": 8000, "like_count": 200, "upload_date": "2026-03-14", "thumbnail_url": "https://i.ytimg.com/vi/asmr1/maxres.jpg", "is_short": False},
])

MOCK_CATEGORIZER_OUTPUT = json.dumps([
    {"video_id": "py1", "category": "programming", "interest_score": 85, "tags": ["python", "tutorial"], "brief_summary": "A beginner Python tutorial"},
    {"video_id": "asmr1", "category": "sleep", "interest_score": 72, "tags": ["asmr", "relaxing"], "brief_summary": "Relaxing sounds for sleeping"},
])

def _mock_subprocess(cmd, **kwargs):
    mock = MagicMock()
    mock.returncode = 0
    prompt = cmd[-1] if cmd else ""
    if "notifications" in prompt:
        mock.stdout = MOCK_SCRAPER_OUTPUT
    elif "IN ORDER" in prompt:
        mock.stdout = MOCK_ENRICHER_OUTPUT
    elif "categorizing" in prompt.lower():
        mock.stdout = MOCK_CATEGORIZER_OUTPUT
    else:
        mock.stdout = "[]"
    return mock

def test_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "runs").mkdir(parents=True)

    with patch("scraper.subprocess.run", side_effect=_mock_subprocess), \
         patch("enricher.subprocess.run", side_effect=_mock_subprocess), \
         patch("enricher.urllib.request.urlretrieve"), \
         patch("categorizer.subprocess.run", side_effect=_mock_subprocess):
        main(["--no-mermaid-thumbnails"])

    run_dir = tmp_path / "vault" / "runs" / date.today().isoformat()
    assert (run_dir / "index.md").exists()
    assert (run_dir / "by-category" / "programming.md").exists()
    assert (run_dir / "by-category" / "sleep.md").exists()
    assert (run_dir / "data.json").exists()

    # Verify checkpoint
    cp = load_checkpoint(str(run_dir / "data.json"))
    assert cp.last_completed_phase == "categorization"
    assert len(cp.videos) == 2  # short was filtered

    # Verify graph-tags at vault root
    assert (tmp_path / "vault" / "graph-tags.md").exists()
