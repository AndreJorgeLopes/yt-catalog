from models import Video
from enricher import batch_videos, build_enricher_prompt, parse_enricher_output

def _make_video(vid: str) -> Video:
    return Video(video_id=vid, title=f"V{vid}", channel="C", url=f"https://www.youtube.com/watch?v={vid}", relative_time="1d")

def test_batch_videos():
    videos = [_make_video(str(i)) for i in range(23)]
    batches = batch_videos(videos, batch_size=10)
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 3

def test_build_enricher_prompt():
    batch = [_make_video("abc"), _make_video("def")]
    prompt = build_enricher_prompt(batch)
    assert "1. https://www.youtube.com/watch?v=abc" in prompt
    assert "2. https://www.youtube.com/watch?v=def" in prompt

def test_parse_enricher_output():
    raw = '''[
        {"video_id": "abc", "duration_seconds": 754, "description": "Learn Python basics", "view_count": 12000, "like_count": 500, "upload_date": "2026-03-14", "thumbnail_url": "https://i.ytimg.com/vi/abc/maxresdefault.jpg", "is_short": false},
        {"video_id": "def", "duration_seconds": 45, "description": "Quick tip", "view_count": 500, "like_count": null, "upload_date": "2026-03-15", "thumbnail_url": "https://i.ytimg.com/vi/def/maxresdefault.jpg", "is_short": true}
    ]'''
    batch = [_make_video("abc"), _make_video("def")]
    enriched = parse_enricher_output(raw, batch)
    assert enriched[0].duration_seconds == 754
    assert enriched[0].description == "Learn Python basics"
    assert enriched[1].is_short is True

def test_parse_enricher_output_with_wrapper_text():
    raw = '''Here are the results:
    [{"video_id": "abc", "duration_seconds": 300, "description": "test", "view_count": 100, "like_count": 10, "upload_date": "2026-03-14", "thumbnail_url": "https://img/abc.jpg", "is_short": false}]
    Done!'''
    batch = [_make_video("abc")]
    enriched = parse_enricher_output(raw, batch)
    assert enriched[0].duration_seconds == 300
