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
    assert result[0].duration_group == "medium"   # 600s -> medium (10-20 min)
    assert result[1].category == "sleep"
    assert result[1].duration_group == "super-big"

def test_parse_categorizer_output_clamps_score():
    raw = '[{"video_id": "abc", "category": "programming", "interest_score": 150, "tags": [], "brief_summary": "test"}]'
    videos = [Video(video_id="abc", title="T", channel="C", url="u", relative_time="1d")]
    result = parse_categorizer_output(raw, videos)
    assert result[0].interest_score == 100


def test_categorize_and_rank_parallel_covers_all_batches(monkeypatch):
    """Every video across multiple batches gets categorized when run in parallel."""
    import yt_catalog.categorizer as cat
    from yt_catalog.models import Video

    vids = [Video(video_id=f"v{i:03d}", title=f"t{i}", channel="C",
                  url=f"u{i}", relative_time="1d") for i in range(95)]

    # fake AI: echo a valid categorization for each id in the batch prompt
    def fake_ai(prompt):
        import json, re
        ids = re.findall(r'"video_id": "(v\d+)"', prompt)
        return json.dumps([{"video_id": i, "category": "programming",
                            "interest_score": 80, "tags": ["x"],
                            "brief_summary": "s"} for i in ids])

    monkeypatch.setattr(cat, "categorize_with_ai", fake_ai)
    out = cat.categorize_and_rank(vids, batch_size=40, max_workers=4)
    assert len(out) == 95
    assert all(v.category == "programming" for v in out)   # all 3 batches applied
    assert all(v.interest_score == 80 for v in out)


def test_categorize_and_rank_falls_back_per_batch(monkeypatch):
    """AI returning nothing -> rule-based fallback still categorizes every video."""
    import yt_catalog.categorizer as cat
    from yt_catalog.models import Video

    vids = [Video(video_id=f"v{i}", title=f"t{i}", channel="C", url=f"u{i}",
                  relative_time="1d") for i in range(50)]
    monkeypatch.setattr(cat, "categorize_with_ai", lambda p: None)
    out = cat.categorize_and_rank(vids, batch_size=40, max_workers=3)
    assert len(out) == 50
    assert all(v.category is not None for v in out)        # rules filled everything
