import os
from yt_catalog.models import Video
from yt_catalog.vault_generator import (
    generate_category_file,
    generate_mermaid_graph,
    generate_index,
    generate_vault,
    generate_html_index,
    _render_callout_card,
    _callout_type,
)


def _video(vid, title, channel, score, duration, group, tags, summary="Summary", upload="2026-03-14"):
    return Video(
        video_id=vid, title=title, channel=channel, url=f"https://www.youtube.com/watch?v={vid}",
        relative_time="1d", duration_seconds=duration, interest_score=score,
        category="programming", tags=tags, summary=summary, duration_group=group,
        upload_date=upload, thumbnail_path=f"thumbnails/{vid}.jpg",
    )


# ---------------------------------------------------------------------------
# _callout_type
# ---------------------------------------------------------------------------

def test_callout_type_tip():
    assert _callout_type(80) == "tip"
    assert _callout_type(100) == "tip"


def test_callout_type_info():
    assert _callout_type(60) == "info"
    assert _callout_type(79) == "info"


def test_callout_type_note():
    assert _callout_type(40) == "note"
    assert _callout_type(59) == "note"


def test_callout_type_quote():
    assert _callout_type(0) == "quote"
    assert _callout_type(39) == "quote"
    assert _callout_type(None) == "quote"


# ---------------------------------------------------------------------------
# _render_callout_card
# ---------------------------------------------------------------------------

def test_render_callout_card_high_score():
    v = _video("abc", "Learn Python", "Ch1", 90, 600, "long", ["python", "tutorial"])
    card = _render_callout_card(v)
    assert "> [!tip]+" in card
    assert "Learn Python" in card
    assert "⭐90" in card
    assert "Ch1" in card
    assert "`#python`" in card
    assert "`#tutorial`" in card
    assert "▶ Watch on YouTube" in card
    assert "https://www.youtube.com/watch?v=abc" in card
    # thumbnail embedded
    assert "![[thumbnails/abc.jpg|300]]" in card


def test_render_callout_card_low_score():
    v = _video("xyz", "Meh Video", "Ch2", 30, 300, "small", ["general"])
    card = _render_callout_card(v)
    assert "> [!quote]+" in card


def test_render_callout_card_no_thumbnail():
    v = _video("abc", "No Thumb", "Ch1", 80, 600, "long", ["python"])
    v.thumbnail_path = None
    card = _render_callout_card(v)
    assert "thumbnails" not in card


def test_render_callout_card_no_tags():
    v = _video("abc", "No Tags", "Ch1", 70, 600, "long", [])
    card = _render_callout_card(v)
    # no tag line expected
    assert "🏷" not in card


# ---------------------------------------------------------------------------
# generate_category_file
# ---------------------------------------------------------------------------

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
    # callout cards present
    assert "> [!tip]+" in md or "> [!info]+" in md
    # higher-scored video in each group comes first
    # within "small" group: Newer Video (75) > Old Video (70)
    assert md.index("Newer Video") < md.index("Old Video")


def test_generate_category_file_empty_group():
    videos = [_video("a", "Quick Tip", "Ch1", 90, 120, "super-small", ["python"])]
    md = generate_category_file("programming", videos, "2026-03-16")
    assert "*No videos in this duration range.*" in md


# ---------------------------------------------------------------------------
# generate_mermaid_graph
# ---------------------------------------------------------------------------

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


def test_mermaid_graph_limits_to_20():
    videos = [_video(str(i), f"V{i}", "Ch", 100 - i, 600, "long", ["tag"]) for i in range(50)]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=False)
    # top 20 present
    assert "V0" in mermaid
    assert "V19" in mermaid
    # 21st+ absent
    assert "V20" not in mermaid
    assert "V30" not in mermaid


def test_mermaid_graph_category_colors():
    videos = [_video("a", "Code", "Ch1", 90, 600, "long", ["python"])]
    videos[0].category = "programming"
    mermaid = generate_mermaid_graph(videos)
    assert "#22c55e" in mermaid  # programming color


def test_mermaid_graph_no_img_tags():
    """HTML <img> tags must not appear in mermaid output."""
    videos = [_video("a", "Learn Python", "Ch1", 90, 600, "long", ["python"])]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=True)
    assert "<img" not in mermaid


def test_mermaid_sanitizes_quotes():
    videos = [_video("a", 'He said "hello" today', "Ch1", 90, 600, "long", ["test"])]
    mermaid = generate_mermaid_graph(videos, use_thumbnails=False)
    assert '"hello"' not in mermaid  # double quotes in title should be replaced
    assert "'hello'" in mermaid  # replaced with single quotes


# ---------------------------------------------------------------------------
# generate_index
# ---------------------------------------------------------------------------

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
    # callout cards instead of tables
    assert "> [!tip]+" in md or "> [!info]+" in md
    # no old-style table syntax
    assert "| | Title |" not in md


def test_generate_index_no_table_pipes():
    """Index must not use gallery table rows with escaped pipe."""
    videos = [_video("a", "Test Video", "Ch1", 85, 600, "long", ["tag"])]
    categories = {"programming": videos}
    md = generate_index(categories, "2026-03-16", use_thumbnails=False)
    assert r"\|80]]" not in md
    assert "| | Title |" not in md


# ---------------------------------------------------------------------------
# generate_html_index
# ---------------------------------------------------------------------------

def test_generate_html_index_basic():
    videos = [
        _video("QUHrntlfPo4", "Claude Code MCP", "Better Stack", 85, 369, "small", ["claude-code", "ai"]),
    ]
    html = generate_html_index({"programming": videos}, "2026-03-16")
    assert "<!DOCTYPE html>" in html
    assert "YouTube Catalog" in html
    assert "2026-03-16" in html
    assert "i.ytimg.com/vi/QUHrntlfPo4/mqdefault.jpg" in html
    assert "Claude Code MCP" in html
    assert "Better Stack" in html
    assert "⭐ 85" in html


def test_generate_html_index_score_colors():
    low = _video("a", "Low", "Ch", 30, 300, "small", [])
    med = _video("b", "Med", "Ch", 65, 300, "small", [])
    high = _video("c", "High", "Ch", 90, 300, "small", [])
    html = generate_html_index({"programming": [low, med, high]}, "2026-03-16")
    assert "#22c55e" in html   # high score green
    assert "#3b82f6" in html   # medium score blue
    assert "#9ca3af" in html   # low score muted


def test_generate_html_index_all_categories():
    categories = {}
    for i, cat in enumerate(["programming", "games", "sleep"]):
        categories[cat] = [_video(str(i), f"Video {i}", "Ch", 70, 600, "long", ["tag"])]
        categories[cat][0].category = cat
    html = generate_html_index(categories, "2026-03-16")
    assert "Programming" in html
    assert "Games" in html
    assert "Sleep" in html


# ---------------------------------------------------------------------------
# generate_vault
# ---------------------------------------------------------------------------

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
    assert os.path.exists(os.path.join(run_dir, "index.html"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "programming.md"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "comedy.md"))
    assert not os.path.exists(os.path.join(run_dir, "by-category", "games.md"))
    vault_root = os.path.dirname(os.path.dirname(run_dir))
    assert os.path.exists(os.path.join(vault_root, "graph-tags.md"))


def test_generate_vault_html_content(tmp_path):
    videos = [_video("abc123", "Python Tutorial", "Ch1", 85, 600, "long", ["python"])]
    videos[0].category = "programming"
    run_dir = str(tmp_path / "vault" / "runs" / "2026-03-16")
    generate_vault(videos, run_dir, mermaid_thumbnails=False)

    html = open(os.path.join(run_dir, "index.html")).read()
    assert "i.ytimg.com/vi/abc123/mqdefault.jpg" in html
    assert "Python Tutorial" in html
