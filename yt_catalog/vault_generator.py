from __future__ import annotations
import re as _re
from pathlib import Path
from datetime import date as _date

from .models import Video
from .config import CATEGORIES, CATEGORY_EMOJIS, DURATION_THRESHOLDS

DURATION_GROUP_LABELS = {
    "super-small": "Super Small (<5 min)",
    "small": "Small (5-10 min)",
    "long": "Long (10-50 min)",
    "super-big": "Super Big (>50 min)",
}

# Mermaid category color palette
CATEGORY_COLORS = {
    "programming": "#22c55e",
    "tech-news": "#3b82f6",
    "comedy": "#f59e0b",
    "games": "#a855f7",
    "hardware": "#ef4444",
    "diy-makers": "#f97316",
    "general": "#6b7280",
    "sleep": "#06b6d4",
}


def _callout_type(score: int | None) -> str:
    s = score or 0
    if s >= 80:
        return "tip"
    if s >= 60:
        return "info"
    if s >= 40:
        return "note"
    return "quote"


def _render_callout_card(v: Video) -> str:
    """Render a video as an Obsidian callout card."""
    ctype = _callout_type(v.interest_score)
    score = v.interest_score or 0
    tags_str = " ".join(f"`#{t}`" for t in v.tags) if v.tags else ""
    thumb_line = f"> ![[thumbnails/{v.video_id}.jpg|300]]\n" if v.thumbnail_path else ""
    upload = v.upload_date or v.relative_time or ""
    upload_part = f" | **Uploaded:** {upload}" if upload else ""
    return (
        f"> [!{ctype}]+ {v.title} \u2b50{score}\n"
        f"{thumb_line}"
        f"> **Channel:** {v.channel} | **Duration:** {v.formatted_duration}"
        f" | **Score:** {score}/100{upload_part}\n"
        + (f"> \U0001f3f7\ufe0f {tags_str}\n" if tags_str else "")
        + f"> [\u25b6 Watch on YouTube]({v.url})\n"
    )


def generate_category_file(category: str, videos: list[Video], run_date: str) -> str:
    emoji = CATEGORY_EMOJIS.get(category, "")
    display_name = category.replace("-", " ").title()
    lines = [
        "---",
        f"tags: [youtube-catalog, {category}, {run_date}]",
        "---",
        f"# {emoji} {display_name} Videos\n",
    ]
    for group_key in ["super-small", "small", "long", "super-big"]:
        label = DURATION_GROUP_LABELS[group_key]
        group_videos = sorted(
            [v for v in videos if v.duration_group == group_key],
            key=lambda v: v.interest_score or 0,
            reverse=True,
        )
        lines.append(f"## {label}\n")
        if not group_videos:
            lines.append("*No videos in this duration range.*\n")
        else:
            for v in group_videos:
                lines.append(_render_callout_card(v))
    return "\n".join(lines)


def _sanitize_mermaid_id(s: str) -> str:
    return _re.sub(r'[^a-zA-Z0-9]', '_', s)


def generate_mermaid_graph(videos: list[Video], use_thumbnails: bool = True) -> str:
    """Text-only mermaid graph, category-colored, top 20 videos."""
    sorted_videos = sorted(videos, key=lambda v: v.interest_score or 0, reverse=True)
    top = sorted_videos[:20]

    lines = ["```mermaid", "graph LR"]

    for v in top:
        vid_id = f"V_{v.video_id}"
        safe_title = v.title.replace('"', "'").replace("\n", " ")[:35]
        label = f'{safe_title} \u2b50{v.interest_score}'
        lines.append(f'    {vid_id}["{label}"]')

    tag_set: set[tuple[str, str]] = set()
    for v in top:
        vid_id = f"V_{v.video_id}"
        for tag in v.tags:
            tag_id = f"T_{_sanitize_mermaid_id(tag)}"
            tag_set.add((tag_id, tag))
            lines.append(f"    {vid_id} --> {tag_id}")

    for v in top:
        vid_id = f"V_{v.video_id}"
        lines.append(f'    click {vid_id} "{v.url}"')

    for tag_id, tag_name in sorted(tag_set):
        lines.append(f'    {tag_id}["{tag_name}"]')
        lines.append(f"    style {tag_id} fill:#4a9eff,color:#fff")

    for v in top:
        vid_id = f"V_{v.video_id}"
        color = CATEGORY_COLORS.get(v.category or "general", "#6b7280")
        lines.append(f"    style {vid_id} fill:{color},color:#fff")

    lines.append("```")
    return "\n".join(lines)


def generate_index(categories: dict[str, list[Video]], run_date: str, use_thumbnails: bool = True) -> str:
    all_videos = [v for vlist in categories.values() for v in vlist]
    total = len(all_videos)

    main_videos = [v for v in all_videos if v.category != "sleep"]
    sleep_videos = [v for v in all_videos if v.category == "sleep"]

    lines = [
        "---",
        f"tags: [youtube-catalog, {run_date}]",
        "---",
        f"# YouTube Catalog \u2014 {run_date}\n",
        f"**Total videos:** {total} | **Main:** {len(main_videos)} | **Sleep:** {len(sleep_videos)}\n",
    ]

    lines.append("## Categories\n")
    for cat, vids in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        if vids:
            emoji = CATEGORY_EMOJIS.get(cat, "")
            avg_score = sum(v.interest_score or 0 for v in vids) // len(vids)
            lines.append(f"- {emoji} **{cat.replace('-', ' ').title()}**: {len(vids)} videos (avg score: {avg_score})")
    lines.append("")

    if main_videos:
        lines.append("## Video Connection Graph\n")
        lines.append(generate_mermaid_graph(main_videos, use_thumbnails=use_thumbnails))
        lines.append("")

    for cat in CATEGORIES:
        vids = categories.get(cat, [])
        if not vids:
            continue
        emoji = CATEGORY_EMOJIS.get(cat, "")
        display = cat.replace("-", " ").title()
        lines.append(f"## {emoji} {display} ({len(vids)} videos)\n")
        for v in sorted(vids, key=lambda v: v.interest_score or 0, reverse=True):
            lines.append(_render_callout_card(v))
        lines.append("")

    return "\n".join(lines)


def generate_graph_tags(videos: list[Video]) -> str:
    tag_groups: dict[str, set[str]] = {}
    for v in videos:
        cat = v.category or "general"
        for tag in v.tags:
            tag_groups.setdefault(cat, set()).add(tag)

    lines = ["# Video Tag Taxonomy\n"]
    for cat in sorted(tag_groups.keys()):
        emoji = CATEGORY_EMOJIS.get(cat, "")
        display = cat.replace("-", " ").title()
        tags = sorted(tag_groups[cat])
        lines.append(f"## {emoji} {display}")
        lines.append(", ".join(f"#{t}" for t in tags))
        lines.append("")
    return "\n".join(lines)


def generate_html_index(categories: dict[str, list[Video]], run_date: str) -> str:
    """Generate a standalone HTML visual index using YouTube thumbnail URLs."""

    def _score_badge_color(score: int | None) -> str:
        s = score or 0
        if s >= 80:
            return "#22c55e"
        if s >= 60:
            return "#3b82f6"
        if s >= 40:
            return "#6b7280"
        return "#9ca3af"

    sections: list[str] = []
    for cat in CATEGORIES:
        vids = categories.get(cat, [])
        if not vids:
            continue
        emoji = CATEGORY_EMOJIS.get(cat, "")
        display = cat.replace("-", " ").title()
        sorted_vids = sorted(vids, key=lambda v: v.interest_score or 0, reverse=True)
        cards: list[str] = []
        for v in sorted_vids:
            thumb_url = f"https://i.ytimg.com/vi/{v.video_id}/mqdefault.jpg"
            score = v.interest_score or 0
            badge_color = _score_badge_color(score)
            tags_html = " ".join(
                f'<span style="background:#1e293b;padding:2px 6px;border-radius:4px;font-size:11px;">#{t}</span>'
                for t in v.tags
            )
            safe_title = v.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cards.append(f"""
    <a href="{v.url}" target="_blank" style="text-decoration:none;color:inherit;">
      <div class="video-card">
        <img src="{thumb_url}" alt="{safe_title}" loading="lazy">
        <div class="info">
          <div class="title">{safe_title}</div>
          <div class="meta">{v.channel} &bull; {v.formatted_duration}</div>
          <div style="margin-top:6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="score-badge" style="background:{badge_color};">\u2b50 {score}</span>
            {tags_html}
          </div>
        </div>
      </div>
    </a>""")
        sections.append(f"""
  <section>
    <h2 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:8px;">{emoji} {display} ({len(vids)} videos)</h2>
    <div class="video-grid">{"".join(cards)}
    </div>
  </section>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YouTube Catalog &mdash; {run_date}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; color: #f1f5f9; font-family: system-ui, -apple-system, sans-serif; padding: 24px; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 24px; color: #f8fafc; }}
  h2 {{ font-size: 1.2rem; margin-bottom: 16px; }}
  section {{ margin-bottom: 48px; }}
  .video-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
  .video-card {{ border-radius: 10px; overflow: hidden; background: #1e293b; transition: transform 0.15s, box-shadow 0.15s; }}
  .video-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
  .video-card img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }}
  .video-card .info {{ padding: 12px; }}
  .video-card .title {{ font-weight: 600; font-size: 13px; line-height: 1.4; color: #f1f5f9; margin-bottom: 4px; }}
  .video-card .meta {{ font-size: 12px; color: #94a3b8; }}
  .score-badge {{ color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
</style>
</head>
<body>
<h1>YouTube Catalog &mdash; {run_date}</h1>
{"".join(sections)}
</body>
</html>"""


def generate_vault(videos: list[Video], run_dir: str, mermaid_thumbnails: bool = True) -> None:
    run_path = Path(run_dir)
    cat_path = run_path / "by-category"
    cat_path.mkdir(parents=True, exist_ok=True)

    categories: dict[str, list[Video]] = {}
    for v in videos:
        cat = v.category or "general"
        categories.setdefault(cat, []).append(v)

    run_date = run_path.name

    for cat, vids in categories.items():
        content = generate_category_file(cat, vids, run_date)
        (cat_path / f"{cat}.md").write_text(content)

    index_content = generate_index(categories, run_date, use_thumbnails=mermaid_thumbnails)
    (run_path / "index.md").write_text(index_content)

    html_content = generate_html_index(categories, run_date)
    (run_path / "index.html").write_text(html_content)

    # Write graph-tags.md at vault root (not inside run dir)
    vault_root = run_path.parent.parent  # vault/runs/YYYY-MM-DD -> vault/
    tags_content = generate_graph_tags(videos)
    (vault_root / "graph-tags.md").write_text(tags_content)
