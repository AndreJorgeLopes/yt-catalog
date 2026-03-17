import json
from unittest.mock import patch, MagicMock
from yt_catalog.models import Video
from yt_catalog.enricher import batch_videos, build_enricher_prompt, parse_enricher_output, enrich_videos_innertube


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


def _make_innertube_response(video_id: str, duration_seconds: int = 300,
                              is_live: bool = False, is_short: bool = False) -> dict:
    duration = str(duration_seconds) if not is_live else "0"
    view = 1000 if not is_live else 0
    return {
        "videoDetails": {
            "videoId": video_id,
            "lengthSeconds": duration,
            "viewCount": str(view),
            "shortDescription": "A test video description",
            "isLiveContent": is_live,
            "thumbnail": {
                "thumbnails": [
                    {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", "width": 480, "height": 360},
                    {"url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg", "width": 1280, "height": 720},
                ]
            },
        },
        "microformat": {
            "playerMicroformatRenderer": {
                "uploadDate": "2026-03-14",
                "publishDate": "2026-03-14",
            }
        },
    }


def _mock_urlopen(url_request, timeout=None):
    import json as _json
    body = json.loads(url_request.data.decode())
    vid = body.get("videoId", "unknown")
    resp_data = _make_innertube_response(vid, duration_seconds=300)
    mock_resp = MagicMock()
    mock_resp.read.return_value = _json.dumps(resp_data).encode()
    return mock_resp


def test_innertube_enrichment_basic():
    """InnerTube enrichment populates duration, view_count, upload_date, thumbnail_url."""
    videos = [_make_video("abc123")]
    with patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=_mock_urlopen):
        enriched = enrich_videos_innertube(videos)
    assert enriched[0].duration_seconds == 300
    assert enriched[0].view_count == 1000
    assert enriched[0].upload_date == "2026-03-14"
    assert "maxresdefault" in enriched[0].thumbnail_url
    assert enriched[0].is_live is False
    assert enriched[0].is_short is False


def test_innertube_enrichment_marks_live():
    """InnerTube enrichment sets is_live=True when isLiveContent=True."""
    videos = [_make_video("live1")]

    def _mock_live_urlopen(url_request, timeout=None):
        import json as _json
        body = json.loads(url_request.data.decode())
        vid = body.get("videoId", "unknown")
        resp_data = _make_innertube_response(vid, duration_seconds=0, is_live=True)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _json.dumps(resp_data).encode()
        return mock_resp

    with patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=_mock_live_urlopen):
        enriched = enrich_videos_innertube(videos)
    assert enriched[0].is_live is True


def test_innertube_enrichment_marks_short():
    """InnerTube enrichment sets is_short=True for videos under 60 seconds."""
    videos = [_make_video("short1")]

    def _mock_short_urlopen(url_request, timeout=None):
        import json as _json
        body = json.loads(url_request.data.decode())
        vid = body.get("videoId", "unknown")
        resp_data = _make_innertube_response(vid, duration_seconds=45)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _json.dumps(resp_data).encode()
        return mock_resp

    with patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=_mock_short_urlopen):
        enriched = enrich_videos_innertube(videos)
    assert enriched[0].is_short is True
    assert enriched[0].duration_seconds == 45


def test_innertube_enrichment_handles_failure_gracefully():
    """Failed InnerTube requests leave video unchanged rather than crashing."""
    videos = [_make_video("badid")]
    with patch("yt_catalog.enricher.urllib.request.urlopen", side_effect=Exception("network error")):
        enriched = enrich_videos_innertube(videos)
    # Should return videos unchanged, not crash
    assert len(enriched) == 1
    assert enriched[0].duration_seconds is None
