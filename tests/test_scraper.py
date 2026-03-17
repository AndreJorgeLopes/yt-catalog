import json
from yt_catalog.scraper import build_scraper_prompt, parse_scraper_output

def test_scraper_prompt_no_limits():
    prompt = build_scraper_prompt(max_days=None, max_videos=None)
    assert "youtube.com/feed/notifications" in prompt
    assert "Stop scrolling when" not in prompt
    assert "Stop after collecting" not in prompt

def test_scraper_prompt_with_max_days():
    prompt = build_scraper_prompt(max_days=7, max_videos=None)
    assert "7 days" in prompt

def test_scraper_prompt_with_max_videos():
    prompt = build_scraper_prompt(max_days=None, max_videos=50)
    assert "50" in prompt

def test_parse_scraper_output():
    raw = '''Here are the results:
    [{"title": "Learn Python", "channel": "CodeCh", "url": "https://www.youtube.com/watch?v=abc123", "time": "2 days ago"},
     {"title": "Short Video", "channel": "ShortCh", "url": "https://www.youtube.com/shorts/def456", "time": "1 day ago"}]
    Some trailing text'''
    videos = parse_scraper_output(raw)
    assert len(videos) == 1
    assert videos[0].video_id == "abc123"
    assert videos[0].title == "Learn Python"
    assert videos[0].channel == "CodeCh"

def test_parse_scraper_output_no_json():
    raw = "I couldn't find any notifications."
    videos = parse_scraper_output(raw)
    assert videos == []

def test_parse_scraper_output_dedup():
    raw = '[{"title": "V1", "channel": "C", "url": "https://www.youtube.com/watch?v=abc", "time": "1d"}, {"title": "V1 dup", "channel": "C", "url": "https://www.youtube.com/watch?v=abc", "time": "1d"}]'
    videos = parse_scraper_output(raw)
    assert len(videos) == 1

def test_parse_scraper_output_filters_livestream():
    """Entries explicitly marked is_live should be excluded."""
    raw = json.dumps([
        {"title": "Normal Video", "channel": "C", "url": "https://www.youtube.com/watch?v=normal1", "time": "1d"},
        {"title": "Live Stream", "channel": "C", "url": "https://www.youtube.com/watch?v=live1", "time": "1d", "is_live": True},
    ])
    videos = parse_scraper_output(raw)
    assert len(videos) == 1
    assert videos[0].video_id == "normal1"

def test_parse_scraper_output_video_has_is_live_false():
    """Parsed videos default to is_live=False."""
    raw = '[{"title": "V", "channel": "C", "url": "https://www.youtube.com/watch?v=vid1", "time": "1d"}]'
    videos = parse_scraper_output(raw)
    assert len(videos) == 1
    assert videos[0].is_live is False
