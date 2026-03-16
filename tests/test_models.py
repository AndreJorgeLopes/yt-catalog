import os
from models import Video, video_to_dict, video_from_dict, extract_json_array, CatalogRun, save_checkpoint, load_checkpoint

def test_video_creation():
    v = Video(
        video_id="abc123",
        title="Test Video",
        channel="Test Channel",
        url="https://www.youtube.com/watch?v=abc123",
        relative_time="3 days ago",
    )
    assert v.video_id == "abc123"
    assert v.duration_seconds is None
    assert v.is_short is False
    assert v.tags == []

def test_formatted_duration_minutes():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago", duration_seconds=754)
    assert v.formatted_duration == "12:34"

def test_formatted_duration_hours():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago", duration_seconds=3661)
    assert v.formatted_duration == "1:01:01"

def test_formatted_duration_none():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago")
    assert v.formatted_duration == "??:??"

def test_video_round_trip():
    v = Video(
        video_id="abc", title="Test", channel="Ch", url="http://yt/abc",
        relative_time="1d ago", duration_seconds=300, tags=["python", "ai"],
    )
    d = video_to_dict(v)
    assert d["video_id"] == "abc"
    assert d["tags"] == ["python", "ai"]
    v2 = video_from_dict(d)
    assert v2.video_id == v.video_id
    assert v2.tags == v.tags
    assert v2.duration_seconds == 300

def test_extract_json_array():
    text = 'Here is the result: [{"a": 1}, {"b": 2}] done.'
    result = extract_json_array(text)
    assert result == [{"a": 1}, {"b": 2}]

def test_extract_json_array_none():
    assert extract_json_array("no json here") is None

def test_checkpoint_round_trip(tmp_path):
    videos = [
        Video(video_id="v1", title="T1", channel="C1", url="http://yt/v1", relative_time="1d ago"),
        Video(video_id="v2", title="T2", channel="C2", url="http://yt/v2", relative_time="2d ago", tags=["python"]),
    ]
    run_dir = str(tmp_path / "run")
    save_checkpoint(videos, run_dir, phase="scraping")

    loaded = load_checkpoint(os.path.join(run_dir, "data.json"))
    assert loaded.last_completed_phase == "scraping"
    assert len(loaded.videos) == 2
    assert loaded.videos[0].video_id == "v1"
    assert loaded.videos[1].tags == ["python"]
