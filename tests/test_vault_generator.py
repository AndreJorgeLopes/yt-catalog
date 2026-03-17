import os
from yt_catalog.models import Video
from yt_catalog.vault_generator import generate_category_file, generate_mermaid_graph, generate_index, generate_vault

def _video(vid, title, channel, score, duration, group, tags, summary="Summary", upload="2026-03-14"):
    return Video(
        video_id=vid, title=title, channel=channel, url=f"https://www.youtube.com/watch?v={vid}",
        relative_time="1d", duration_seconds=duration, interest_score=score,
        category="programming", tags=tags, summary=summary, duration_group=group,
        upload_date=upload, thumbnail_path=f"thumbnails/{vid}.jpg",
    )

def test_generate_category_file():
    videos = [
        _video("a", "Quick Tip", "Ch1", 90, 120, "super-small", ["python"]),
        _video("b", "Long Tutorial", "Ch2", 85, 1800, "long", ["python", "django"]),
        _video("c", "Old Video", "Ch3", 70, 400, "small", ["react"], upload="2026-03-10"),
        _video("d", "Newer Video", "Ch4", 75, 500, "small", ["react"], upload="2026-03-13"),
    ]
    md = generate_category_file("programming", videos, "2026-03-16")
    assert "---" in md
    assert "youtube-catalog" in md
    assert "## Super Small" in md
    assert "## Small" in md
    assert "## Long" in md
    assert md.index("Old Video") < md.index("Newer Video")

def test_mermaid_graph_basic():
    videos = [
        _video("a", "Learn Python", "Ch1", 90, 600, "long", ["python", "tutorial"]),
        _video("b", "React Intro", "Ch2", 80, 900, "long", ["react", "tutorial"]),
    ]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=True)
    assert "```mermaid" in mermaid
    assert "python" in mermaid
    assert "tutorial" in mermaid
    assert "react" in mermaid

def test_mermaid_graph_limits_to_30():
    videos = [_video(str(i), f"V{i}", "Ch", 100 - i, 600, "long", ["tag"]) for i in range(50)]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=False)
    assert "V0" in mermaid
    assert "V29" in mermaid
    assert "V30" not in mermaid

def test_generate_index():
    videos = [
        _video("a", "Learn Python", "Ch1", 90, 600, "long", ["python"]),
        _video("b", "ASMR Sleep", "Ch2", 70, 3700, "super-big", ["asmr"]),
    ]
    videos[1].category = "sleep"
    categories = {"programming": [videos[0]], "sleep": [videos[1]]}
    md = generate_index(categories, "2026-03-16", use_thumbnails=False)
    assert "# YouTube Catalog" in md
    assert "2026-03-16" in md
    assert "```mermaid" in md

def test_generate_vault(tmp_path):
    videos = [
        _video("a", "Learn Python", "Ch1", 90, 600, "long", ["python"]),
        _video("b", "Funny Cat", "Ch2", 80, 300, "small", ["comedy"]),
    ]
    videos[0].category = "programming"
    videos[1].category = "comedy"
    run_dir = str(tmp_path / "vault" / "runs" / "2026-03-16")
    generate_vault(videos, run_dir, mermaid_thumbnails=False)

    assert os.path.exists(os.path.join(run_dir, "index.md"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "programming.md"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "comedy.md"))
    assert not os.path.exists(os.path.join(run_dir, "by-category", "games.md"))
    vault_root = os.path.dirname(os.path.dirname(run_dir))
    assert os.path.exists(os.path.join(vault_root, "graph-tags.md"))

def test_mermaid_sanitizes_quotes():
    videos = [_video("a", 'He said "hello" today', "Ch1", 90, 600, "long", ["test"])]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=False)
    assert '"hello"' not in mermaid  # double quotes in title should be replaced
    assert "'hello'" in mermaid  # replaced with single quotes
