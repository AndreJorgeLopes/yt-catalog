from __future__ import annotations
import re as _re
from pathlib import Path

from models import Video
from config import CATEGORIES, CATEGORY_EMOJIS, DURATION_THRESHOLDS

DURATION_GROUP_LABELS = {
    "super-small": "Super Small (<5 min)",
    "small": "Small (5-10 min)",
    "long": "Long (10-50 min)",
    "super-big": "Super Big (>50 min)",
}

def _render_video_entry(v: Video) -> str:
    thumb = f"![[thumbnails/{v.video_id}.jpg|200]]" if v.thumbnail_path else ""
    tags_str = " ".join(f"#{t}" for t in v.tags) if v.tags else ""
    summary = f"> {v.summary}" if v.summary else ""
    upload = v.upload_date or v.relative_time
    return f"""### [{v.title}]({v.url}) — \u2b50 {v.interest_score}/100
{thumb}
**Channel:** {v.channel} | **Duration:** {v.formatted_duration} | **Uploaded:** {upload}
**Tags:** {tags_str}
{summary}

---
"""

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
            key=lambda v: v.upload_date or "9999",
        )
        lines.append(f"## {label}\n")
        if not group_videos:
            lines.append("*No videos in this duration range.*\n")
        else:
            for v in group_videos:
                lines.append(_render_video_entry(v))
    return "\n".join(lines)

def _sanitize_mermaid_id(s: str) -> str:
    return _re.sub(r'[^a-zA-Z0-9]', '_', s)

def generate_mermaid_graph(videos: list[Video], use_thumbnails: bool = True) -> str:
    sorted_videos = sorted(videos, key=lambda v: v.interest_score or 0, reverse=True)
    top = sorted_videos[:30]

    lines = ["```mermaid", "graph LR"]

    for v in top:
        vid_id = f"V_{v.video_id}"
        safe_title = v.title.replace('"', "'").replace("\n", " ")[:50]
        if use_thumbnails and v.thumbnail_path:
            label = f'<img src="thumbnails/{v.video_id}.jpg" width="60"/><br/>{safe_title} \u2b50{v.interest_score}'
        else:
            label = f'{safe_title} \u2b50{v.interest_score}'
        lines.append(f'    {vid_id}["{label}"]')

    tag_set = set()
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

    lines.append("```")
    return "\n".join(lines)

def generate_gallery_row(v: Video) -> str:
    thumb = f"![[thumbnails/{v.video_id}.jpg\\|80]]" if v.thumbnail_path else ""
    return f"| {thumb} | [{v.title}]({v.url}) | \u2b50{v.interest_score} | {v.formatted_duration} | {v.channel} |"

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
        lines.append("| | Title | Score | Duration | Channel |")
        lines.append("|---|---|---|---|---|")
        for v in sorted(vids, key=lambda v: v.interest_score or 0, reverse=True):
            lines.append(generate_gallery_row(v))
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

    # Write graph-tags.md at vault root (not inside run dir)
    vault_root = run_path.parent.parent  # vault/runs/YYYY-MM-DD -> vault/
    tags_content = generate_graph_tags(videos)
    (vault_root / "graph-tags.md").write_text(tags_content)
