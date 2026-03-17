from yt_catalog.models import Video
from yt_catalog.categorizer import build_categorizer_prompt, parse_categorizer_output

def test_categorizer_prompt_includes_videos():
    videos = [
        Video(video_id="abc", title="Learn Python", channel="CodeCh", url="http://yt/abc",
              relative_time="1d", duration_seconds=600, description="Python tutorial"),
    ]
    prompt = build_categorizer_prompt(videos)
    assert "Learn Python" in prompt
    assert "CodeCh" in prompt
    assert "Main Content Scoring Rubric" in prompt
    assert "Sleep Content Scoring Rubric" in prompt

def test_parse_categorizer_output():
    raw = '''[
        {"video_id": "abc", "category": "programming", "interest_score": 85, "tags": ["python", "tutorial"], "brief_summary": "A Python tutorial"},
        {"video_id": "def", "category": "sleep", "interest_score": 72, "tags": ["asmr", "relaxing"], "brief_summary": "Relaxing sounds"}
    ]'''
    videos = [
        Video(video_id="abc", title="Learn Python", channel="CodeCh", url="http://yt/abc",
              relative_time="1d", duration_seconds=600),
        Video(video_id="def", title="ASMR Sounds", channel="SleepCh", url="http://yt/def",
              relative_time="2d", duration_seconds=3700),
    ]
    result = parse_categorizer_output(raw, videos)
    assert result[0].category == "programming"
    assert result[0].interest_score == 85
    assert result[0].tags == ["python", "tutorial"]
    assert result[0].duration_group == "long"
    assert result[1].category == "sleep"
    assert result[1].duration_group == "super-big"

def test_parse_categorizer_output_clamps_score():
    raw = '[{"video_id": "abc", "category": "programming", "interest_score": 150, "tags": [], "brief_summary": "test"}]'
    videos = [Video(video_id="abc", title="T", channel="C", url="u", relative_time="1d")]
    result = parse_categorizer_output(raw, videos)
    assert result[0].interest_score == 100
