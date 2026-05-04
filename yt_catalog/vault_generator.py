from __future__ import annotations
import re as _re
from pathlib import Path
from datetime import date as _date

from .models import Video
from .config import (
    CATEGORIES, CATEGORY_EMOJIS,
    DURATION_GROUP_ORDER, DURATION_GROUP_LABELS, DURATION_GROUP_SHORT,
    get_duration_group,
)


def _dgroup(v: Video) -> str:
    """Duration group computed live from duration_seconds (don't trust the stored
    field — old runs used a 4-bucket scheme; this renders the current 5)."""
    return get_duration_group(v.duration_seconds)

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
    """Render a video as an Obsidian callout card with inline playback.

    Media Extended (aidenlx/media-extended) only parses `![](URL)` at top-level
    \u2014 inside a blockquote/callout it renders the player chrome but no video. So
    the Media Extended embed lives OUTSIDE the callout, below it. The callout
    still carries a `<details>` iframe as a zero-plugin fallback.
    """
    ctype = _callout_type(v.interest_score)
    score = v.interest_score or 0
    tags_str = " ".join(f"`#{t}`" for t in v.tags) if v.tags else ""
    thumb_line = f"> ![[thumbnails/{v.video_id}.jpg|300]]\n" if v.thumbnail_path else ""
    upload = v.upload_date or v.relative_time or ""
    upload_part = f" | **Uploaded:** {upload}" if upload else ""
    iframe_fallback = (
        f"> <details><summary>\u25b6 Play inline (iframe fallback)</summary>"
        f'<iframe width="560" height="315" '
        f'src="https://www.youtube.com/embed/{v.video_id}" '
        f'title="YouTube video player" frameborder="0" '
        f'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
        f"allowfullscreen></iframe></details>\n"
    )
    callout = (
        f"> [!{ctype}]+ {v.title} \u2b50{score}\n"
        f"{thumb_line}"
        f"> **Channel:** {v.channel} | **Duration:** {v.formatted_duration}"
        f" | **Score:** {score}/100{upload_part}\n"
        + (f"> \U0001f3f7\ufe0f {tags_str}\n" if tags_str else "")
        + f"> [\u25b6 Watch on YouTube]({v.url})\n"
        + iframe_fallback
    )
    # Media Extended embed \u2014 must be at top-level (no `>` prefix) to be parsed.
    safe_alt = (v.title or "video").replace("[", "").replace("]", "")[:60]
    media_extended = f"\n![{safe_alt}]({v.url})\n"
    return callout + media_extended


def generate_category_file(category: str, videos: list[Video], run_date: str) -> str:
    emoji = CATEGORY_EMOJIS.get(category, "")
    display_name = category.replace("-", " ").title()
    lines = [
        "---",
        f"tags: [youtube-catalog, {category}, {run_date}]",
        "---",
        f"# {emoji} {display_name} Videos\n",
    ]
    for group_key in DURATION_GROUP_ORDER:
        label = DURATION_GROUP_LABELS[group_key]
        group_videos = sorted(
            [v for v in videos if _dgroup(v) == group_key],
            key=lambda v: v.interest_score or 0,
            reverse=True,
        )
        if not group_videos:
            continue  # omit empty length sections (keeps the file tight)
        lines.append(f"## {label}\n")
        for v in group_videos:
            lines.append(_render_callout_card(v))
    return "\n".join(lines)


def _sanitize_mermaid_id(s: str) -> str:
    return _re.sub(r'[^a-zA-Z0-9]', '_', s)


def _excalidraw_id(seed: str) -> str:
    import hashlib
    return hashlib.md5(seed.encode()).hexdigest()[:16]


def generate_excalidraw(videos: list[Video], run_dir: str,
                        per_category_cap: int | None = None) -> str:
    """Generate an Excalidraw diagram (Obsidian plugin format).

    Layout: ONE COLUMN PER CATEGORY (left -> right, in CATEGORIES order). Inside
    a column the videos are split into length sub-groups (super-small ... super-big,
    shortest first) under small duration sub-headers, each card showing the
    thumbnail + title + score. Thumbnails are embedded as base64 data URLs
    (Excalidraw renders nothing from a relative path). A card's `link` opens the
    video. To keep the board legible each category is capped at
    ``per_category_cap`` videos; the drop count is noted on the board.
    """
    import json
    import textwrap

    def _wrap(text: str, width: int = 32, max_lines: int = 3) -> tuple[str, int]:
        wrapped = textwrap.wrap(text or "", width=width)[:max_lines] or [""]
        return "\n".join(wrapped), len(wrapped)

    PAD_X = 40
    PAD_Y = 40
    CARD_W = 280
    CARD_H = 230
    IMG_W = 280
    IMG_H = 160
    GAP_X = 24             # between cards in a row
    GAP_Y = 28             # between card rows
    GRID_COLS = 4          # cards per row inside a category section
    SEC_PAD = 28           # padding inside a category section frame
    SEC_GAP = 48           # vertical gap between category sections
    DUR_LABEL_H = 30       # height of a duration sub-label row
    HEADER_H = 46          # category header height
    SEC_W = SEC_PAD * 2 + GRID_COLS * CARD_W + (GRID_COLS - 1) * GAP_X

    elements: list[dict] = []
    # Embedded Files: fileId -> vault path. The Obsidian Excalidraw plugin reads
    # this section and loads the image from the vault at render time — so we DON'T
    # base64-embed (that produced a 70MB+ file for a few hundred thumbnails).
    embedded: dict[str, str] = {}
    thumb_refs: dict[str, str] = {}  # video_id -> fileId

    def _color_for(cat: str) -> str:
        return CATEGORY_COLORS.get(cat, "#6b7280")

    def _text_el(seed: str, x: int, y: int, w: int, h: int, color: str,
                 size: int, text: str, link: str | None = None) -> None:
        elements.append({
            "id": _excalidraw_id(seed), "type": "text", "x": x, "y": y,
            "width": w, "height": h, "angle": 0, "strokeColor": color,
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 2, "strokeStyle": "solid", "roughness": 0,
            "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
            "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False,
            "boundElements": [], "updated": 1, "link": link, "locked": False,
            "fontSize": size, "fontFamily": 1, "text": text, "textAlign": "left",
            "verticalAlign": "top", "containerId": None, "originalText": text,
            "lineHeight": 1.25, "baseline": int(size * 0.8),
        })

    # Group videos by category, score-sorted within. Category SECTIONS are
    # ordered by item count (most videos first) — the same ordering used by the
    # index and the channel summary.
    sorted_all = sorted(videos, key=lambda v: v.interest_score or 0, reverse=True)
    by_cat: dict[str, list[Video]] = {}
    for v in sorted_all:
        by_cat.setdefault(v.category or "general", []).append(v)
    cat_sections = sorted(by_cat.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def _card(v: Video, cat_color: str, x: int, y: int) -> None:
        elements.append({
            "id": _excalidraw_id(f"card-{v.video_id}"), "type": "rectangle",
            "x": x, "y": y, "width": CARD_W, "height": CARD_H, "angle": 0,
            "strokeColor": cat_color, "backgroundColor": "#1e293b",
            "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "groupIds": [f"g-{v.video_id}"],
            "frameId": None, "roundness": {"type": 3}, "seed": 1, "version": 1,
            "versionNonce": 1, "isDeleted": False, "boundElements": [],
            "updated": 1, "link": v.url, "locked": False,
        })
        thumb_file = Path(run_dir) / "thumbnails" / f"{v.video_id}.jpg"
        if thumb_file.exists():
            fid = thumb_refs.get(v.video_id) or _excalidraw_id(f"file-{v.video_id}")
            thumb_refs[v.video_id] = fid
            embedded[fid] = f"thumbnails/{v.video_id}.jpg"
            elements.append({
                "id": _excalidraw_id(f"img-{v.video_id}"), "type": "image",
                "x": x, "y": y, "width": IMG_W, "height": IMG_H, "angle": 0,
                "strokeColor": "transparent", "backgroundColor": "transparent",
                "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
                "roughness": 0, "opacity": 100, "groupIds": [f"g-{v.video_id}"],
                "frameId": None, "roundness": None, "seed": 1, "version": 1,
                "versionNonce": 1, "isDeleted": False, "boundElements": [],
                "updated": 1, "link": v.url, "locked": False, "status": "saved",
                "fileId": fid, "scale": [1, 1],
            })
        wrapped_title, nlines = _wrap(v.title or "", width=32, max_lines=3)
        caption = f"{wrapped_title}\n⭐{v.interest_score or 0} · {v.formatted_duration}"
        _text_el(f"cap-{v.video_id}", x + 8, y + IMG_H + 6, IMG_W - 16,
                 (nlines + 1) * 18, "#f1f5f9", 14, caption, link=v.url)

    def _section_height(vids: list[Video]) -> int:
        by_dur: dict[str, list[Video]] = {}
        for v in vids:
            by_dur.setdefault(_dgroup(v), []).append(v)
        h = HEADER_H
        for dg in DURATION_GROUP_ORDER:
            dn = len(by_dur.get(dg, []))
            if not dn:
                continue
            rows = (dn + GRID_COLS - 1) // GRID_COLS
            h += DUR_LABEL_H + rows * CARD_H + (rows - 1) * GAP_Y + GAP_Y
        return h + SEC_PAD * 2

    dropped = 0
    sec_x = PAD_X
    sec_top = PAD_Y + 36   # leave room for the optional drop-note banner
    for cat, vids in cat_sections:
        sec_y = sec_top
        if per_category_cap and len(vids) > per_category_cap:
            dropped += len(vids) - per_category_cap
            vids = vids[:per_category_cap]
        cat_color = _color_for(cat)
        emoji = CATEGORY_EMOJIS.get(cat, "")
        sec_h = _section_height(vids)

        # Section frame (background rectangle) — visually separates categories.
        elements.append({
            "id": _excalidraw_id(f"sec-{cat}"), "type": "rectangle",
            "x": sec_x, "y": sec_y, "width": SEC_W, "height": sec_h, "angle": 0,
            "strokeColor": cat_color, "backgroundColor": "#0b1220",
            "fillStyle": "solid", "strokeWidth": 3, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "groupIds": [], "frameId": None,
            "roundness": {"type": 3}, "seed": 1, "version": 1, "versionNonce": 1,
            "isDeleted": False, "boundElements": [], "updated": 1, "link": None,
            "locked": False,
        })
        _text_el(f"cathdr-{cat}", sec_x + SEC_PAD, sec_y + SEC_PAD, SEC_W - 2 * SEC_PAD,
                 HEADER_H, cat_color, 30,
                 f"{emoji} {cat.replace('-', ' ').title()} ({len(vids)})")

        by_dur: dict[str, list[Video]] = {}
        for v in vids:
            by_dur.setdefault(_dgroup(v), []).append(v)
        cy = sec_y + SEC_PAD + HEADER_H
        for dg in DURATION_GROUP_ORDER:
            dvids = by_dur.get(dg)
            if not dvids:
                continue
            _text_el(f"durhdr-{cat}-{dg}", sec_x + SEC_PAD, cy, SEC_W - 2 * SEC_PAD,
                     26, "#94a3b8", 18, f"⏱ {DURATION_GROUP_SHORT[dg]} ({len(dvids)})")
            cy += DUR_LABEL_H
            for i, v in enumerate(dvids):
                col = i % GRID_COLS
                row = i // GRID_COLS
                cx = sec_x + SEC_PAD + col * (CARD_W + GAP_X)
                cyy = cy + row * (CARD_H + GAP_Y)
                _card(v, cat_color, cx, cyy)
            rows = (len(dvids) + GRID_COLS - 1) // GRID_COLS
            cy += rows * CARD_H + (rows - 1) * GAP_Y + GAP_Y
        # sections sit side by side (horizontal), each its own column block
        sec_x += SEC_W + SEC_GAP

    if dropped:
        _text_el("dropnote", PAD_X, max(0, PAD_Y - 6), SEC_W, 26, "#f59e0b", 16,
                 f"Showing top {per_category_cap} per category · {dropped} more not shown")

    drawing = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://github.com/zsviczian/obsidian-excalidraw-plugin",
        "elements": elements,
        "appState": {"gridSize": None, "viewBackgroundColor": "#0f172a"},
        # Empty — the plugin rebuilds the file map from the "## Embedded Files"
        # section below (vault-relative paths, not megabytes of base64).
        "files": {},
    }

    embedded_section = "## Embedded Files\n"
    for fid, path in embedded.items():
        embedded_section += f"{fid}: [[{path}]]\n"

    body = (
        "---\n"
        "excalidraw-plugin: parsed\n"
        "tags: [excalidraw, youtube-catalog]\n"
        "---\n\n"
        "==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==\n\n\n"
        "# Excalidraw Data\n\n"
        "## Text Elements\n\n"
        + embedded_section +
        "\n## Drawing\n"
        "```json\n"
        + json.dumps(drawing, ensure_ascii=False, indent=0)
        + "\n```\n%%"
    )
    return body


def generate_channel_summary(videos: list[Video], avatars_subpath: str = "avatars") -> str:
    """TL;DR block: one row per channel, with avatar, video count, categories, top tags.

    `avatars_subpath` is the path (relative to the note) where avatar images live.
    """
    from collections import Counter, defaultdict

    by_channel: dict[str, list[Video]] = defaultdict(list)
    for v in videos:
        key = v.channel or "Unknown"
        by_channel[key].append(v)

    lines = [
        "## Channel TL;DR\n",
        "| Channel | Videos | Categories | Top Tags | Avg Score |",
        "|---|---|---|---|---|",
    ]
    rows = []
    for channel, vids in by_channel.items():
        cat_counts = Counter(v.category or "general" for v in vids)
        cat_str = " ".join(
            f"{CATEGORY_EMOJIS.get(c, '')}×{n}" for c, n in cat_counts.most_common(4)
        ).strip()
        tag_counts = Counter(t for v in vids for t in (v.tags or []))
        tag_str = " ".join(f"`#{t}`" for t, _ in tag_counts.most_common(4))
        avg = sum((v.interest_score or 0) for v in vids) // max(1, len(vids))
        cid = next((v.channel_id for v in vids if v.channel_id), "")
        if cid:
            avatar_cell = f"![\\|40]({avatars_subpath}/{cid}.jpg) **{channel}**"
        else:
            avatar_cell = f"**{channel}**"
        rows.append((len(vids), avg, channel, avatar_cell, cat_str, tag_str))

    # Sort by video count desc, then avg score desc
    rows.sort(key=lambda r: (-r[0], -r[1], r[2].lower()))
    for count, avg, _channel, avatar_cell, cat_str, tag_str in rows:
        lines.append(f"| {avatar_cell} | {count} | {cat_str or '—'} | {tag_str or '—'} | {avg} |")
    lines.append("")
    return "\n".join(lines)


def generate_mermaid_graph(videos: list[Video], use_thumbnails: bool = True) -> str:
    """Original left-to-right connection graph: video -> tag. Top 20 videos."""
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


def generate_mermaid_mindmap(categories: dict[str, list[Video]]) -> str:
    """Radial mindmap: catalog root -> category branches -> top videos per category.

    Renders as a wide, tree-shaped alternative to the linear graph. Up to 5 top
    videos per category to keep the layout legible.
    """
    lines = ["```mermaid", "mindmap", "  root((Catalog))"]

    def _safe(text: str) -> str:
        # Mindmap treats [], (), {}, (()) and "" as shape delimiters. Strip them.
        out = text
        for ch in '[](){}"`':
            out = out.replace(ch, "")
        # Collapse remaining whitespace/punctuation noise.
        out = _re.sub(r'\s+', ' ', out).strip()
        # Trailing colons also trip the parser.
        out = out.rstrip(':').rstrip('#')
        return out[:45]

    cats = sorted(categories.items(), key=lambda x: len(x[1]), reverse=True)
    for cat, vids in cats:
        if not vids:
            continue
        emoji = CATEGORY_EMOJIS.get(cat, "")
        cat_label = f"{emoji} {cat.replace('-', ' ').title()}".strip()
        lines.append(f"    {cat_label}")
        top = sorted(vids, key=lambda v: v.interest_score or 0, reverse=True)[:5]
        for v in top:
            label = f"{_safe(v.title)} \u2b50{v.interest_score}"
            lines.append(f"      {label}")
    lines.append("```")
    return "\n".join(lines)


def generate_index(
    categories: dict[str, list[Video]],
    run_date: str,
    use_thumbnails: bool = True,
    all_videos: list[Video] | None = None,
) -> str:
    if all_videos is None:
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
        f"[\U0001f5bc\ufe0f Open Excalidraw diagram](diagram.excalidraw.md)\n",
        # Inline refresh button (yt-skip-checkbox plugin).
        "```yt-refresh\n```\n",
    ]

    lines.append(generate_channel_summary(all_videos))

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

        main_categories = {c: [v for v in vs if v.category != "sleep"]
                           for c, vs in categories.items()}
        main_categories = {c: vs for c, vs in main_categories.items() if vs}
        if main_categories:
            lines.append("## Mindmap View\n")
            lines.append(generate_mermaid_mindmap(main_categories))
            lines.append("")

    # Same ordering as the diagram + channel summary: most videos first.
    for cat, vids in sorted(categories.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if not vids:
            continue
        emoji = CATEGORY_EMOJIS.get(cat, "")
        display = cat.replace("-", " ").title()
        lines.append(f"## {emoji} {display} ({len(vids)} videos)\n")
        # Sub-divide each category by video length (super-small ... super-big).
        for dg in DURATION_GROUP_ORDER:
            dvids = sorted([v for v in vids if _dgroup(v) == dg],
                           key=lambda v: v.interest_score or 0, reverse=True)
            if not dvids:
                continue
            lines.append(f"### {DURATION_GROUP_LABELS[dg]} ({len(dvids)})\n")
            for v in dvids:
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


def _download_channel_avatars(videos: list[Video], run_dir: Path) -> None:
    """Fetch and cache channel avatars into run_dir/avatars/<channel_id>.jpg."""
    import urllib.request
    import sys
    from concurrent.futures import ThreadPoolExecutor

    avatars_dir = run_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    unique_ids = {v.channel_id for v in videos if v.channel_id}
    missing = [cid for cid in unique_ids if not (avatars_dir / f"{cid}.jpg").exists()]
    if not missing:
        return

    try:
        from .api_scraper import fetch_channel_info
        info = fetch_channel_info(missing)
    except Exception as e:
        print(f"Warning: could not fetch channel avatars: {e}", file=sys.stderr)
        return

    def _dl(cid: str) -> None:
        url = info.get(cid, {}).get("avatar_url")
        if not url:
            return
        try:
            urllib.request.urlretrieve(url, str(avatars_dir / f"{cid}.jpg"))
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(_dl, missing))


def generate_watchlist(videos: list[Video], run_date: str,
                       avatars_subpath: str = "avatars") -> str:
    """A markdown checklist for marking videos watched/skipped, grouped by channel.

    `[x]` = watched, `[-]` = skipped; both hide the video on the next
    `yt-catalog refresh`. Each channel header carries its avatar; each video
    shows its thumbnail, with the rating + length ALWAYS on their own indented
    continuation line (so long and short titles wrap identically). No hidden
    marker — `refresh`/`insights` recover the video id straight from the URL.
    """
    from collections import defaultdict
    lines = [
        "---", f"tags: [youtube-catalog, watchlist, {run_date}]", "---",
        f"# Watchlist — {run_date}\n",
        # Inline button (rendered by the yt-skip-checkbox plugin) — runs refresh.
        "```yt-refresh\n```\n",
        "Mark videos, then hit the button above (or run `yt-catalog refresh`):",
        "- `[x]` = **watched** — hide it  (click, or shift-click for skip)",
        "- `[-]` = **skipped** — hide it AND count it toward channel skip stats "
        "(shift-click the box)",
        "- leave `[ ]` to keep it\n",
        "> Then **click the Refresh button above** (or run `yt-catalog refresh "
        "<run>`). For skip stats + the list of what you marked, open "
        "**insights.md** and rebuild it (its button, or `yt-catalog insights <run>`).\n",
    ]
    by_ch: dict[str, list[Video]] = defaultdict(list)
    for v in videos:
        by_ch[v.channel or "Unknown"].append(v)
    for ch, vids in sorted(by_ch.items(), key=lambda x: len(x[1]), reverse=True):
        cid = next((v.channel_id for v in vids if v.channel_id), "")
        avatar = f"![\\|28]({avatars_subpath}/{cid}.jpg) " if cid else ""
        lines.append(f"\n## {avatar}{ch} ({len(vids)})\n")
        for v in sorted(vids, key=lambda v: v.interest_score or 0, reverse=True):
            thumb = (f"\n      ![\\|240](thumbnails/{v.video_id}.jpg)"
                     if v.thumbnail_path else "")
            lines.append(
                f"- [ ] [{v.title}]({v.url})"
                f"\n      ⭐{v.interest_score or 0} · {v.formatted_duration}"
                f"{thumb}")
    return "\n".join(lines)


def _yt_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def generate_insights(state: dict, run_date: str,
                      run_video_ids: set[str] | None = None) -> str:
    """Curation analytics from the accumulated (global) watched/skipped marks.

    Tables + graphs aggregate ALL runs. The video LISTS are split into "this run"
    (ids present in this run's data.json, via ``run_video_ids``) vs "earlier
    runs", so you can see what you just marked separately from the history.
    """
    from . import curate
    ch_rows = curate.channel_skip_stats(state)
    cat_rows = curate.category_skip_stats(state)
    watched = state.get("watched", {})
    skipped = state.get("skipped", {})
    nwatched, nskipped = len(watched), len(skipped)
    ids = run_video_ids if run_video_ids is not None else set()
    lines = [
        "---", "tags: [youtube-catalog, insights]", "---",
        "# Curation Insights\n",
        # button + command (both work)
        "```yt-insights\n```",
        "_Rebuild this with the button above, or run `yt-catalog insights <run>`._\n",
        f"**Watched (all runs):** {nwatched} | **Skipped (all runs):** {nskipped}\n",
    ]
    if not ch_rows:
        lines.append("_Nothing marked yet. Tick `[x]` (watched) or `[-]` (skipped) "
                     "in `watchlist.md`, hit its Refresh button (or run "
                     "`yt-catalog refresh <run>`), then rebuild this._")
        return "\n".join(lines)

    # The actual marked videos — so you can confirm what's set and REVERT it:
    # uncheck a box here and rebuild (insights/refresh) to un-mark that video.
    def _mark_list(items: list, box: str, title: str) -> None:
        if not items:
            return
        lines.append(f"\n## {title} ({len(items)})\n")
        lines.append("_Uncheck a box to revert it, then rebuild (button / "
                     "`yt-catalog insights <run>`)._\n")
        for vid, meta in items:
            ch = meta.get("channel") or meta.get("channel_id") or "?"
            ttl = meta.get("title") or vid
            lines.append(f"- [{box}] [{ttl}]({_yt_url(vid)}) — {ch}")

    def _split(bucket: dict):
        items = sorted(bucket.items(),
                       key=lambda kv: (kv[1].get("channel") or "", kv[1].get("title") or ""))
        this_run = [it for it in items if it[0] in ids]
        earlier = [it for it in items if it[0] not in ids]
        return this_run, earlier

    w_now, w_prev = _split(watched)
    s_now, s_prev = _split(skipped)
    if run_video_ids is not None:
        lines.append("\n# This run")
        _mark_list(w_now, "x", "✅ Watched — this run")
        _mark_list(s_now, "-", "⏭️ Skipped — this run")
        lines.append("\n# Earlier runs")
        _mark_list(w_prev, "x", "✅ Watched — earlier runs")
        _mark_list(s_prev, "-", "⏭️ Skipped — earlier runs")
    else:
        _mark_list(w_now + w_prev, "x", "✅ Watched")
        _mark_list(s_now + s_prev, "-", "⏭️ Skipped")

    lines.append("\n> Raw counts only — `skipped` just means you skipped that video. "
                 "Use this however you like to build your own channel lists.\n")
    lines.append("## Per-channel: watched vs skipped\n")
    lines.append("| Channel | Skipped | Watched | Skip % |")
    lines.append("|---|--:|--:|:--|")
    for r in ch_rows[:50]:
        bar = "█" * round(r["skip_pct"] / 10)
        lines.append(f"| {r['channel']} | {r['skipped']} | {r['watched']} | {r['skip_pct']}% {bar} |")

    lines.append("\n## Per-category: watched vs skipped\n")
    lines.append("| Category | Skipped | Watched | Skip % |")
    lines.append("|---|--:|--:|--:|")
    for r in cat_rows:
        lines.append(f"| {r['category']} | {r['skipped']} | {r['watched']} | {r['skip_pct']}% |")

    top = [r for r in ch_rows if r["skipped"] > 0][:8]
    if top:
        lines.append("\n## Top skipped channels\n")
        lines.append("```mermaid")
        lines.append("pie showData")
        lines.append("    title Skips by channel")
        for r in top:
            name = r["channel"].replace('"', "'")[:30]
            lines.append(f'    "{name}" : {r["skipped"]}')
        lines.append("```")
    return "\n".join(lines)


def generate_vault(videos: list[Video], run_dir: str, mermaid_thumbnails: bool = True,
                   state: dict | None = None) -> None:
    from . import curate
    if state is None:
        state = {"watched": {}, "skipped": {}, "hidden_channels": []}

    run_path = Path(run_dir)
    cat_path = run_path / "by-category"
    cat_path.mkdir(parents=True, exist_ok=True)

    # Hide watched / skipped videos and hidden channels from every view + count.
    visible = curate.filter_videos(videos, state)
    # Also enforce the short-form floor here, so regenerating an OLD run (scraped
    # under a lower floor) retroactively drops now-too-short videos.
    from .api_scraper import _is_too_short
    visible = [v for v in visible if not _is_too_short(v.duration_seconds)]

    categories: dict[str, list[Video]] = {}
    for v in visible:
        categories.setdefault(v.category or "general", []).append(v)

    run_date = run_path.name

    _download_channel_avatars(visible, run_path)

    # Clear stale category files (a category may be empty now after hiding).
    for old in cat_path.glob("*.md"):
        old.unlink()
    for cat, vids in categories.items():
        (cat_path / f"{cat}.md").write_text(generate_category_file(cat, vids, run_date))

    (run_path / "index.md").write_text(
        generate_index(categories, run_date, use_thumbnails=mermaid_thumbnails, all_videos=visible))
    (run_path / "index.html").write_text(generate_html_index(categories, run_date))
    (run_path / "watchlist.md").write_text(generate_watchlist(visible, run_date))
    (run_path / "insights.md").write_text(
        generate_insights(state, run_date,
                          run_video_ids={v.video_id for v in videos}))

    try:
        (run_path / "diagram.excalidraw.md").write_text(generate_excalidraw(visible, str(run_path)))
    except Exception as e:
        import sys as _sys
        print(f"Warning: excalidraw generation failed: {e}", file=_sys.stderr)

    vault_root = run_path.parent.parent  # vault/runs/YYYY-MM-DD -> vault/
    (vault_root / "graph-tags.md").write_text(generate_graph_tags(visible))
