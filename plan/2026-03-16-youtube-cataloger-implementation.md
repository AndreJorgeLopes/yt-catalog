# YouTube Notification Cataloger Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI tool that scrapes YouTube notifications via Chrome automation, categorizes videos with Claude AI, and generates an Obsidian vault with mermaid-visualized, ranked video lists.

**Architecture:** Four-phase pipeline — Scraper (chrome) -> Enricher (sequential chrome) -> Categorizer (Claude AI) -> Vault Generator (pure Python). All orchestrated by a single CLI entry point with checkpoint-based resume. No external pip dependencies.

**Tech Stack:** Python 3.12+ stdlib only, `claude` CLI for subagent spawning, claude-in-chrome MCP for browser automation.

**Spec:** `docs/specs/2026-03-16-youtube-notification-cataloger-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `cataloger.py` | CLI entry point, argparse, phase orchestration, checkpoint resume |
| `models.py` | `Video` and `CatalogRun` dataclasses, serialization/deserialization, shared `extract_json_array` utility |
| `config.py` | Constants: categories, base scores, modifiers, duration thresholds, prompt templates |
| `scraper.py` | Build scraper prompt, spawn `claude --print`, parse scraped JSON output |
| `enricher.py` | Batch videos, build enrichment prompts, spawn sequential `claude --print`, parse output, download thumbnails |
| `categorizer.py` | Build categorization prompt, spawn `claude --print` (no chrome needed), parse output, assign categories/scores/tags |
| `vault_generator.py` | Generate all Obsidian markdown: index.md, category files, mermaid graphs, gallery tables, graph-tags.md |
| `tests/test_models.py` | Unit tests for Video/CatalogRun serialization, formatted_duration, duration_group |
| `tests/test_config.py` | Unit tests for config constants and prompt template rendering |
| `tests/test_vault_generator.py` | Unit tests for markdown generation, mermaid graph, category files |
| `tests/test_cataloger.py` | Unit tests for checkpoint save/load, phase ordering, CLI arg parsing |
| `tests/test_scraper.py` | Unit tests for prompt construction and output parsing (mock subprocess) |
| `tests/test_enricher.py` | Unit tests for batching, prompt construction, output parsing, thumbnail download |
| `tests/test_categorizer.py` | Unit tests for prompt construction and output parsing |

### Spec Deviations (intentional)

- **`CatalogRun.categories` omitted** — The spec includes a `categories` dict field, but it's recomputed from `videos` in `vault_generator.py`. Storing it in the checkpoint adds no value and complicates serialization.
- **`templates/video-card.md` omitted** — The video card template is inlined in `vault_generator._render_video_entry()`. A separate template file adds indirection with no benefit.
- **`scraped_at` per-video field omitted** — The spec's checkpoint shows this field, but the `scrape_date` at the run level is sufficient. Not worth adding to the Video dataclass.
- **`graph-tags.md` location** — The spec shows this at `vault/graph-tags.md` (vault root). We place it there, NOT inside the run directory.

---

## Chunk 1: Data Model, Config, and Checkpoint I/O

### Task 1: Video dataclass and serialization

**Files:**
- Create: `models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for Video dataclass creation**

```python
# tests/test_models.py
from models import Video

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py::test_video_creation -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Implement Video dataclass**

```python
# models.py
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Video:
    video_id: str
    title: str
    channel: str
    url: str
    relative_time: str
    duration_seconds: int | None = None
    description: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    upload_date: str | None = None
    thumbnail_url: str | None = None
    thumbnail_path: str | None = None
    is_short: bool = False
    category: str | None = None
    interest_score: int | None = None
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
    duration_group: str | None = None

    @property
    def formatted_duration(self) -> str:
        if self.duration_seconds is None:
            return "??:??"
        h, rem = divmod(self.duration_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py::test_video_creation -v`
Expected: PASS

- [ ] **Step 5: Write failing test for formatted_duration**

```python
# tests/test_models.py (append)
def test_formatted_duration_minutes():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago", duration_seconds=754)
    assert v.formatted_duration == "12:34"

def test_formatted_duration_hours():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago", duration_seconds=3661)
    assert v.formatted_duration == "1:01:01"

def test_formatted_duration_none():
    v = Video(video_id="a", title="t", channel="c", url="u", relative_time="1h ago")
    assert v.formatted_duration == "??:??"
```

- [ ] **Step 6: Run tests — should all pass (already implemented)**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 7: Write failing test for Video serialization to/from dict**

```python
# tests/test_models.py (append)
from models import video_to_dict, video_from_dict

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
```

- [ ] **Step 8: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py::test_video_round_trip -v`
Expected: FAIL — `ImportError: cannot import name 'video_to_dict'`

- [ ] **Step 9: Implement serialization functions**

```python
# models.py (append)
import dataclasses
import json
import re

def video_to_dict(v: Video) -> dict:
    return dataclasses.asdict(v)

def video_from_dict(d: dict) -> Video:
    return Video(**{k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(Video)}})

def extract_json_array(text: str) -> list[dict] | None:
    """Extract first JSON array from text that may contain surrounding prose."""
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None
```

- [ ] **Step 10: Run all model tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 11: Commit**

```bash
cd ~/dev/youtube-cataloger && git add models.py tests/test_models.py && git commit -m "feat: add Video dataclass with serialization and duration formatting"
```

### Task 2: CatalogRun dataclass and checkpoint I/O

**Files:**
- Modify: `models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing test for checkpoint save/load**

```python
# tests/test_models.py (append)
import tempfile, os
from models import CatalogRun, save_checkpoint, load_checkpoint

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py::test_checkpoint_round_trip -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement CatalogRun and checkpoint I/O**

```python
# models.py (append)
import json
from pathlib import Path
from datetime import datetime, timezone

@dataclass
class CatalogRun:
    run_date: str
    last_completed_phase: str
    total_scraped: int
    shorts_filtered: int
    videos: list[Video]

def save_checkpoint(videos: list[Video], run_dir: str, phase: str, shorts_filtered: int = 0) -> None:
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    data = {
        "scrape_date": datetime.now(timezone.utc).isoformat(),
        "last_completed_phase": phase,
        "total_scraped": len(videos),
        "shorts_filtered": shorts_filtered,
        "videos": [video_to_dict(v) for v in videos],
    }
    (path / "data.json").write_text(json.dumps(data, indent=2))

def load_checkpoint(path: str) -> CatalogRun:
    data = json.loads(Path(path).read_text())
    videos = [video_from_dict(v) for v in data["videos"]]
    return CatalogRun(
        run_date=data["scrape_date"],
        last_completed_phase=data["last_completed_phase"],
        total_scraped=data["total_scraped"],
        shorts_filtered=data.get("shorts_filtered", 0),
        videos=videos,
    )
```

- [ ] **Step 4: Run all tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_models.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/dev/youtube-cataloger && git add models.py tests/test_models.py && git commit -m "feat: add CatalogRun dataclass with checkpoint save/load"
```

### Task 3: Config constants and prompt templates

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test for config constants**

```python
# tests/test_config.py
from config import CATEGORIES, BASE_SCORES, DURATION_THRESHOLDS, PHASE_ORDER

def test_categories_exist():
    assert "programming" in CATEGORIES
    assert "sleep" in CATEGORIES
    assert len(CATEGORIES) == 8  # 7 main + sleep

def test_base_scores():
    assert BASE_SCORES["programming"] == 70
    assert BASE_SCORES["general"] == 30

def test_duration_thresholds():
    assert DURATION_THRESHOLDS["super-small"] == (0, 300)
    assert DURATION_THRESHOLDS["small"] == (300, 600)
    assert DURATION_THRESHOLDS["long"] == (600, 3000)
    assert DURATION_THRESHOLDS["super-big"] == (3000, float("inf"))

def test_phase_order():
    assert PHASE_ORDER["scraping"] < PHASE_ORDER["enrichment"]
    assert PHASE_ORDER["enrichment"] < PHASE_ORDER["categorization"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_config.py -v`
Expected: FAIL

- [ ] **Step 3: Implement config.py**

```python
# config.py
CATEGORIES = [
    "programming", "tech-news", "comedy", "games",
    "hardware", "diy-makers", "general", "sleep",
]

BASE_SCORES = {
    "programming": 70,
    "tech-news": 70,
    "comedy": 70,
    "diy-makers": 60,
    "hardware": 55,
    "games": 45,
    "general": 30,
    "sleep": 50,
}

FAVORITE_CHANNELS = [
    "evan and katelyn", "mrwhosetheboss", "bernardo almeida",
]

DURATION_THRESHOLDS = {
    "super-small": (0, 300),        # < 5 min
    "small": (300, 600),            # 5-10 min
    "long": (600, 3000),            # 10-50 min
    "super-big": (3000, float("inf")),  # > 50 min
}

PHASE_ORDER = {"scraping": 1, "enrichment": 2, "categorization": 3}

CATEGORY_EMOJIS = {
    "programming": "\U0001f4bb",
    "tech-news": "\U0001f4f1",
    "comedy": "\U0001f923",
    "games": "\U0001f3ae",
    "hardware": "\U0001f527",
    "diy-makers": "\U0001f6e0\ufe0f",
    "general": "\U0001f4cc",
    "sleep": "\U0001f634",
}

SCRAPER_PROMPT = """Navigate to https://www.youtube.com/feed/notifications

IMPORTANT: Do NOT click the notification bell icon. Navigate directly to the URL above.

Then extract ALL notification entries from the page by:
1. Use javascript_tool to query the DOM for notification entries
2. Scroll down and re-extract after each scroll to get more entries
3. Keep scrolling until no new entries appear (3 consecutive scrolls with same count)
{limits_clause}

For each notification, extract:
- title: the video title text
- channel: the channel name
- url: the video URL (the href of the thumbnail link)
- time: the relative timestamp (e.g., "3 days ago")

Skip any entries that:
- Don't have a video URL (community posts, live stream notifications)
- Have a URL containing "/shorts/"

Return the results as a JSON array. Return ONLY the JSON array, no other text.
Example format:
[{{"title": "Video Title", "channel": "Channel Name", "url": "https://www.youtube.com/watch?v=...", "time": "3 days ago"}}]
"""

ENRICHER_PROMPT = """Visit each of the following YouTube video pages IN ORDER.
For each video, navigate to the URL, extract the metadata, then move to the next.

Videos:
{video_list}

For each video, extract using javascript_tool or page reading:
- video_id: string (from the URL, the v= parameter)
- duration_seconds: integer (total seconds of the video)
- description: string (first 500 characters of the description)
- view_count: integer (number of views)
- like_count: integer or null (if not visible)
- upload_date: string (ISO 8601 format, e.g. "2026-03-14")
- thumbnail_url: string (from og:image meta tag or video player thumbnail)
- is_short: boolean (true if duration < 60 seconds)

Return a JSON array with one object per video, in the same order as the input list.
Return ONLY the JSON array, no other text.
"""

CATEGORIZER_PROMPT = """You are categorizing YouTube videos for a user with these interests:
- Top interests: Programming, Tech News, Comedy
- Portuguese content gets a significant boost (+15 points)
- Favorite channels (always +20): Evan and Katelyn, MrWhoseTheBoss, Bernardo Almeida
- ASMR/chiropractic/massage = sleep content (separate tier, separate scoring)

## Main Content Scoring Rubric (0-100)
Base scores: Programming=70, Tech News=70, Comedy=70, DIY/Makers=60, Hardware=55, Games=45, General=30
Modifiers: Portuguese language +15, Favorite channel +20, Uploaded <24h ago +5, Your judgment +/-15
Clamp final score to 0-100.

## Sleep Content Scoring Rubric (0-100)
For ASMR, chiropractic, and massage videos, score on a SEPARATE scale:
- Channel reputation for relaxation content (known creators score higher)
- Video length: >30min gets +15, >1hr gets +25 (longer = better for sleep)
- Title signals: keywords like "sleep", "relaxing", "no talking" get +10
- Your judgment on relaxation quality +/-15
Base score for sleep content: 50. Apply modifiers. Clamp to 0-100.

For each video, provide:
1. category: one of [programming, tech-news, comedy, games, hardware, diy-makers, general, sleep]
2. interest_score: 0-100 (use the APPROPRIATE rubric)
3. tags: 3-5 topic tags for graph view connections (lowercase, e.g., "python", "react", "nvidia")
4. brief_summary: 1-2 sentence description

Videos list:
{json_video_list}

Return a JSON array with one object per video containing: video_id, category, interest_score, tags, brief_summary.
Return ONLY the JSON array, no other text.
"""
```

- [ ] **Step 4: Run tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_config.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Write failing test for duration_group assignment helper**

```python
# tests/test_config.py (append)
from config import get_duration_group

def test_duration_group_super_small():
    assert get_duration_group(120) == "super-small"

def test_duration_group_small():
    assert get_duration_group(450) == "small"

def test_duration_group_long():
    assert get_duration_group(1800) == "long"

def test_duration_group_super_big():
    assert get_duration_group(4000) == "super-big"

def test_duration_group_none():
    assert get_duration_group(None) == "long"  # default
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_config.py::test_duration_group_super_small -v`
Expected: FAIL

- [ ] **Step 7: Implement get_duration_group**

```python
# config.py (append)
def get_duration_group(duration_seconds: int | None) -> str:
    if duration_seconds is None:
        return "long"  # default assumption
    for group, (low, high) in DURATION_THRESHOLDS.items():
        if low <= duration_seconds < high:
            return group
    return "long"
```

- [ ] **Step 8: Run all config tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_config.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 9: Commit**

```bash
cd ~/dev/youtube-cataloger && git add config.py tests/test_config.py && git commit -m "feat: add config constants, prompt templates, and duration grouping"
```

---

## Chunk 2: Scraper, Enricher, and Categorizer (Claude CLI integration)

### Task 4: Scraper — prompt construction and output parsing

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write failing test for scraper prompt construction**

```python
# tests/test_scraper.py
from scraper import build_scraper_prompt

def test_scraper_prompt_no_limits():
    prompt = build_scraper_prompt(max_days=None, max_videos=None)
    assert "youtube.com/feed/notifications" in prompt
    assert "Stop scrolling when" not in prompt
    assert "Stop after collecting" not in prompt

def test_scraper_prompt_with_max_days():
    prompt = build_scraper_prompt(max_days=7, max_videos=None)
    assert "7 days" in prompt

def test_scraper_prompt_with_max_videos():
    prompt = build_scraper_prompt(max_days=None, max_videos=50)
    assert "50" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_scraper.py -v`
Expected: FAIL

- [ ] **Step 3: Implement build_scraper_prompt**

```python
# scraper.py
from config import SCRAPER_PROMPT

def build_scraper_prompt(max_days: int | None, max_videos: int | None) -> str:
    limits = []
    if max_days is not None:
        limits.append(f"Stop scrolling when you encounter notifications older than {max_days} days.")
    if max_videos is not None:
        limits.append(f"Stop after collecting {max_videos} video entries.")
    limits_clause = "\n".join(limits) if limits else ""
    return SCRAPER_PROMPT.format(limits_clause=limits_clause)
```

- [ ] **Step 4: Run tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for parse_scraper_output**

```python
# tests/test_scraper.py (append)
from scraper import parse_scraper_output

def test_parse_scraper_output():
    raw = '''Here are the results:
    [{"title": "Learn Python", "channel": "CodeCh", "url": "https://www.youtube.com/watch?v=abc123", "time": "2 days ago"},
     {"title": "Short Video", "channel": "ShortCh", "url": "https://www.youtube.com/shorts/def456", "time": "1 day ago"}]
    Some trailing text'''
    videos = parse_scraper_output(raw)
    assert len(videos) == 1  # shorts filtered out
    assert videos[0].video_id == "abc123"
    assert videos[0].title == "Learn Python"
    assert videos[0].channel == "CodeCh"

def test_parse_scraper_output_no_json():
    raw = "I couldn't find any notifications."
    videos = parse_scraper_output(raw)
    assert videos == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_scraper.py::test_parse_scraper_output -v`
Expected: FAIL

- [ ] **Step 7: Implement parse_scraper_output**

```python
# scraper.py (append)
from urllib.parse import urlparse, parse_qs
from models import Video, extract_json_array

def _extract_video_id(url: str) -> str | None:
    if "/shorts/" in url:
        return None
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        return parse_qs(parsed.query).get("v", [None])[0]
    return None

def parse_scraper_output(raw: str) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return []
    videos = []
    for entry in entries:
        url = entry.get("url", "")
        if "/shorts/" in url:
            continue
        vid = _extract_video_id(url)
        if not vid:
            continue
        videos.append(Video(
            video_id=vid,
            title=entry.get("title", "Unknown"),
            channel=entry.get("channel", "Unknown"),
            url=url,
            relative_time=entry.get("time", ""),
        ))
    # Deduplicate by video_id
    seen = set()
    unique = []
    for v in videos:
        if v.video_id not in seen:
            seen.add(v.video_id)
            unique.append(v)
    return unique
```

- [ ] **Step 8: Run all scraper tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_scraper.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 9: Implement scrape_notifications (subprocess call)**

```python
# scraper.py (append)
import subprocess
import sys

def scrape_notifications(max_days: int | None = None, max_videos: int | None = None) -> list[Video]:
    prompt = build_scraper_prompt(max_days, max_videos)
    result = subprocess.run(
        ["claude", "--print", "--allowedTools", "mcp__claude-in-chrome__*", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"Scraper failed: {result.stderr}", file=sys.stderr)
        return []
    return parse_scraper_output(result.stdout)
```

- [ ] **Step 10: Commit**

```bash
cd ~/dev/youtube-cataloger && git add scraper.py tests/test_scraper.py && git commit -m "feat: add scraper with prompt construction and output parsing"
```

### Task 5: Enricher — batching, prompt construction, output parsing, thumbnail download

**Files:**
- Create: `enricher.py`
- Create: `tests/test_enricher.py`

- [ ] **Step 1: Write failing test for batch_videos**

```python
# tests/test_enricher.py
from models import Video
from enricher import batch_videos

def _make_video(vid: str) -> Video:
    return Video(video_id=vid, title=f"V{vid}", channel="C", url=f"http://yt/{vid}", relative_time="1d")

def test_batch_videos():
    videos = [_make_video(str(i)) for i in range(23)]
    batches = batch_videos(videos, batch_size=10)
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_enricher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement batch_videos and build_enricher_prompt**

```python
# enricher.py
from __future__ import annotations
import subprocess
import sys
import urllib.request
from pathlib import Path

from models import Video, extract_json_array
from config import ENRICHER_PROMPT

def batch_videos(videos: list[Video], batch_size: int = 10) -> list[list[Video]]:
    return [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]

def build_enricher_prompt(batch: list[Video]) -> str:
    video_list = "\n".join(
        f"{i+1}. {v.url}" for i, v in enumerate(batch)
    )
    return ENRICHER_PROMPT.format(video_list=video_list)
```

- [ ] **Step 4: Run test**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_enricher.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for parse_enricher_output**

```python
# tests/test_enricher.py (append)
from enricher import parse_enricher_output

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
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_enricher.py::test_parse_enricher_output -v`
Expected: FAIL

- [ ] **Step 7: Implement parse_enricher_output**

```python
# enricher.py (append)

def parse_enricher_output(raw: str, batch: list[Video]) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return batch  # return unchanged if parsing fails

    # Build lookup by video_id
    lookup = {e["video_id"]: e for e in entries if "video_id" in e}

    for v in batch:
        if v.video_id in lookup:
            e = lookup[v.video_id]
            v.duration_seconds = e.get("duration_seconds")
            v.description = e.get("description")
            v.view_count = e.get("view_count")
            v.like_count = e.get("like_count")
            v.upload_date = e.get("upload_date")
            v.thumbnail_url = e.get("thumbnail_url")
            v.is_short = e.get("is_short", False)
    return batch
```

- [ ] **Step 8: Run all enricher tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_enricher.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 9: Implement download_thumbnails and enrich_videos**

```python
# enricher.py (append)

def download_thumbnails(videos: list[Video], run_dir: str) -> None:
    thumb_dir = Path(run_dir) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    for v in videos:
        if not v.thumbnail_url:
            continue
        dest = thumb_dir / f"{v.video_id}.jpg"
        try:
            urllib.request.urlretrieve(v.thumbnail_url, str(dest))
            v.thumbnail_path = str(dest)
        except Exception as e:
            print(f"Warning: Failed to download thumbnail for {v.video_id}: {e}", file=sys.stderr)

def enrich_videos(videos: list[Video]) -> list[Video]:
    batches = batch_videos(videos)
    for i, batch in enumerate(batches):
        print(f"Enriching batch {i+1}/{len(batches)} ({len(batch)} videos)...")
        prompt = build_enricher_prompt(batch)
        result = subprocess.run(
            ["claude", "--print", "--allowedTools", "mcp__claude-in-chrome__*", "-p", prompt],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            print(f"Warning: Enrichment batch {i+1} failed: {result.stderr}", file=sys.stderr)
            continue
        parse_enricher_output(result.stdout, batch)
    return videos
```

- [ ] **Step 10: Commit**

```bash
cd ~/dev/youtube-cataloger && git add enricher.py tests/test_enricher.py && git commit -m "feat: add enricher with batching, prompt construction, output parsing, thumbnail download"
```

### Task 6: Categorizer — prompt construction and output parsing

**Files:**
- Create: `categorizer.py`
- Create: `tests/test_categorizer.py`

- [ ] **Step 1: Write failing test for categorizer prompt construction**

```python
# tests/test_categorizer.py
from models import Video
from categorizer import build_categorizer_prompt

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_categorizer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement build_categorizer_prompt**

```python
# categorizer.py
from __future__ import annotations
import json
import subprocess
import sys

from models import Video, extract_json_array
from config import CATEGORIZER_PROMPT, get_duration_group

def build_categorizer_prompt(videos: list[Video]) -> str:
    video_list = json.dumps(
        [{"video_id": v.video_id, "title": v.title, "channel": v.channel,
          "duration_seconds": v.duration_seconds, "description": v.description or "",
          "upload_date": v.upload_date or v.relative_time}
         for v in videos],
        indent=2,
    )
    return CATEGORIZER_PROMPT.format(json_video_list=video_list)
```

- [ ] **Step 4: Run test**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_categorizer.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for parse_categorizer_output**

```python
# tests/test_categorizer.py (append)
from categorizer import parse_categorizer_output

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
    assert result[0].duration_group == "long"  # 600s = 10 min
    assert result[1].category == "sleep"
    assert result[1].duration_group == "super-big"  # 3700s > 50 min
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_categorizer.py::test_parse_categorizer_output -v`
Expected: FAIL

- [ ] **Step 7: Implement parse_categorizer_output**

```python
# categorizer.py (append)

def parse_categorizer_output(raw: str, videos: list[Video]) -> list[Video]:
    entries = extract_json_array(raw)
    if not entries:
        return videos

    lookup = {e["video_id"]: e for e in entries if "video_id" in e}

    for v in videos:
        if v.video_id in lookup:
            e = lookup[v.video_id]
            v.category = e.get("category", "general")
            v.interest_score = max(0, min(100, e.get("interest_score", 50)))
            v.tags = e.get("tags", [])
            v.summary = e.get("brief_summary")
        else:
            v.category = "general"
            v.interest_score = 30
        v.duration_group = get_duration_group(v.duration_seconds)
    return videos

def categorize_and_rank(videos: list[Video]) -> list[Video]:
    prompt = build_categorizer_prompt(videos)
    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"Categorizer failed: {result.stderr}", file=sys.stderr)
        # Assign defaults
        for v in videos:
            v.category = "general"
            v.interest_score = 30
            v.duration_group = get_duration_group(v.duration_seconds)
        return videos
    return parse_categorizer_output(result.stdout, videos)
```

- [ ] **Step 8: Run all categorizer tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_categorizer.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 9: Commit**

```bash
cd ~/dev/youtube-cataloger && git add categorizer.py tests/test_categorizer.py && git commit -m "feat: add categorizer with prompt construction and output parsing"
```

---

## Chunk 3: Vault Generator

### Task 7: Category file generation

**Files:**
- Create: `vault_generator.py`
- Create: `tests/test_vault_generator.py`

- [ ] **Step 1: Write failing test for generate_category_file**

```python
# tests/test_vault_generator.py
from models import Video
from vault_generator import generate_category_file

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
    assert "---" in md  # frontmatter
    assert "youtube-catalog" in md
    assert "## Super Small" in md
    assert "## Small" in md
    assert "## Long" in md
    # Oldest first within duration group
    assert md.index("Old Video") < md.index("Newer Video")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement generate_category_file**

```python
# vault_generator.py
from __future__ import annotations
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
```

- [ ] **Step 4: Run test**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ~/dev/youtube-cataloger && git add vault_generator.py tests/test_vault_generator.py && git commit -m "feat: add category file generation for Obsidian vault"
```

### Task 8: Mermaid graph and index.md generation

**Files:**
- Modify: `vault_generator.py`
- Modify: `tests/test_vault_generator.py`

- [ ] **Step 1: Write failing test for mermaid graph generation**

```python
# tests/test_vault_generator.py (append)
from vault_generator import generate_mermaid_graph

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
    # Should only include top 30 by score
    assert "V0" in mermaid  # score 100
    assert "V29" in mermaid  # score 71
    assert "V30" not in mermaid  # score 70 — excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py::test_mermaid_graph_basic -v`
Expected: FAIL

- [ ] **Step 3: Implement generate_mermaid_graph**

```python
# vault_generator.py (append)
import re as _re

def _sanitize_mermaid_id(s: str) -> str:
    return _re.sub(r'[^a-zA-Z0-9]', '_', s)

def generate_mermaid_graph(videos: list[Video], use_thumbnails: bool = True) -> str:
    # Limit to top 30 by interest score
    sorted_videos = sorted(videos, key=lambda v: v.interest_score or 0, reverse=True)
    top = sorted_videos[:30]

    lines = ["```mermaid", "graph LR"]

    # Define video nodes
    for v in top:
        vid_id = f"V_{v.video_id}"
        safe_title = v.title.replace('"', "'").replace("\n", " ")[:50]
        if use_thumbnails and v.thumbnail_path:
            label = f'<img src="thumbnails/{v.video_id}.jpg" width="60"/><br/>{safe_title} \u2b50{v.interest_score}'
        else:
            label = f'{safe_title} \u2b50{v.interest_score}'
        lines.append(f'    {vid_id}["{label}"]')

    # Collect all tags and connect videos to tags
    tag_set = set()
    for v in top:
        vid_id = f"V_{v.video_id}"
        for tag in v.tags:
            tag_id = f"T_{_sanitize_mermaid_id(tag)}"
            tag_set.add((tag_id, tag))
            lines.append(f"    {vid_id} --> {tag_id}")

    # Add click links
    for v in top:
        vid_id = f"V_{v.video_id}"
        lines.append(f'    click {vid_id} "{v.url}"')

    # Style tag nodes
    for tag_id, tag_name in sorted(tag_set):
        lines.append(f'    {tag_id}["{tag_name}"]')
        lines.append(f"    style {tag_id} fill:#4a9eff,color:#fff")

    lines.append("```")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for generate_index**

```python
# tests/test_vault_generator.py (append)
from vault_generator import generate_index

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
    assert "Programming" in md or "programming" in md
    assert "```mermaid" in md
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py::test_generate_index -v`
Expected: FAIL

- [ ] **Step 7: Implement generate_index**

```python
# vault_generator.py (append)

def generate_gallery_row(v: Video) -> str:
    thumb = f"![[thumbnails/{v.video_id}.jpg\\|80]]" if v.thumbnail_path else ""
    return f"| {thumb} | [{v.title}]({v.url}) | \u2b50{v.interest_score} | {v.formatted_duration} | {v.channel} |"

def generate_index(categories: dict[str, list[Video]], run_date: str, use_thumbnails: bool = True) -> str:
    all_videos = [v for vlist in categories.values() for v in vlist]
    total = len(all_videos)

    # Separate main and sleep
    main_videos = [v for v in all_videos if v.category != "sleep"]
    sleep_videos = [v for v in all_videos if v.category == "sleep"]

    lines = [
        "---",
        f"tags: [youtube-catalog, {run_date}]",
        "---",
        f"# YouTube Catalog — {run_date}\n",
        f"**Total videos:** {total} | **Main:** {len(main_videos)} | **Sleep:** {len(sleep_videos)}\n",
    ]

    # Per-category counts
    lines.append("## Categories\n")
    for cat, vids in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        if vids:
            emoji = CATEGORY_EMOJIS.get(cat, "")
            avg_score = sum(v.interest_score or 0 for v in vids) // len(vids)
            lines.append(f"- {emoji} **{cat.replace('-', ' ').title()}**: {len(vids)} videos (avg score: {avg_score})")
    lines.append("")

    # Mermaid graph (main content only)
    if main_videos:
        lines.append("## Video Connection Graph\n")
        lines.append(generate_mermaid_graph(main_videos, use_thumbnails=use_thumbnails))
        lines.append("")

    # Gallery per category
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
```

- [ ] **Step 8: Run all vault generator tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 9: Commit**

```bash
cd ~/dev/youtube-cataloger && git add vault_generator.py tests/test_vault_generator.py && git commit -m "feat: add mermaid graph and index.md generation"
```

### Task 9: Full vault generation (write files to disk)

**Files:**
- Modify: `vault_generator.py`
- Modify: `tests/test_vault_generator.py`

- [ ] **Step 1: Write failing test for generate_vault**

```python
# tests/test_vault_generator.py (append)
import os
from vault_generator import generate_vault

def test_generate_vault(tmp_path):
    videos = [
        _video("a", "Learn Python", "Ch1", 90, 600, "long", ["python"]),
        _video("b", "Funny Cat", "Ch2", 80, 300, "small", ["comedy"]),
    ]
    videos[0].category = "programming"
    videos[1].category = "comedy"
    # Simulate vault/runs/YYYY-MM-DD structure so graph-tags.md goes to vault root
    run_dir = str(tmp_path / "vault" / "runs" / "2026-03-16")
    generate_vault(videos, run_dir, mermaid_thumbnails=False)

    assert os.path.exists(os.path.join(run_dir, "index.md"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "programming.md"))
    assert os.path.exists(os.path.join(run_dir, "by-category", "comedy.md"))
    # Empty categories should not have files
    assert not os.path.exists(os.path.join(run_dir, "by-category", "games.md"))
    # graph-tags.md should exist at vault root (parent of runs/)
    vault_root = os.path.dirname(os.path.dirname(run_dir))  # vault/
    assert os.path.exists(os.path.join(vault_root, "graph-tags.md"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py::test_generate_vault -v`
Expected: FAIL

- [ ] **Step 3: Implement generate_vault and generate_graph_tags**

```python
# vault_generator.py (append)

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

    # Group by category
    categories: dict[str, list[Video]] = {}
    for v in videos:
        cat = v.category or "general"
        categories.setdefault(cat, []).append(v)

    run_date = run_path.name  # e.g., "2026-03-16"

    # Write category files
    for cat, vids in categories.items():
        content = generate_category_file(cat, vids, run_date)
        (cat_path / f"{cat}.md").write_text(content)

    # Write index.md
    index_content = generate_index(categories, run_date, use_thumbnails=mermaid_thumbnails)
    (run_path / "index.md").write_text(index_content)

    # Write graph-tags.md at vault root (not inside run dir)
    vault_root = run_path.parent.parent  # vault/runs/YYYY-MM-DD -> vault/
    tags_content = generate_graph_tags(videos)
    (vault_root / "graph-tags.md").write_text(tags_content)
```

- [ ] **Step 4: Run all vault generator tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_vault_generator.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/dev/youtube-cataloger && git add vault_generator.py tests/test_vault_generator.py && git commit -m "feat: add full vault generation with category files, index, and graph-tags"
```

---

## Chunk 4: CLI Orchestrator

### Task 10: CLI argument parsing and main orchestration

**Files:**
- Create: `cataloger.py`
- Create: `tests/test_cataloger.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write failing test for CLI arg parsing**

```python
# tests/test_cataloger.py
from cataloger import parse_args

def test_parse_args_defaults():
    args = parse_args([])
    assert args.max_days is None
    assert args.max_videos is None
    assert args.from_checkpoint is None
    assert args.no_mermaid_thumbnails is False

def test_parse_args_with_options():
    args = parse_args(["--max-days", "7", "--max-videos", "50", "--no-mermaid-thumbnails"])
    assert args.max_days == 7
    assert args.max_videos == 50
    assert args.no_mermaid_thumbnails is True

def test_parse_args_checkpoint():
    args = parse_args(["--from-checkpoint", "/path/to/data.json"])
    assert args.from_checkpoint == "/path/to/data.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_cataloger.py -v`
Expected: FAIL

- [ ] **Step 3: Implement cataloger.py**

```python
#!/usr/bin/env python3
# cataloger.py — YouTube Notification Cataloger
"""Scrape YouTube notifications, categorize with AI, generate Obsidian vault."""

from __future__ import annotations
import argparse
import sys
from datetime import date
from pathlib import Path

from config import PHASE_ORDER
from models import save_checkpoint, load_checkpoint
from scraper import scrape_notifications
from enricher import enrich_videos, download_thumbnails
from categorizer import categorize_and_rank
from vault_generator import generate_vault


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Notification Cataloger")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Only scrape notifications from the last N days")
    parser.add_argument("--max-videos", type=int, default=None,
                        help="Stop after scraping N videos")
    parser.add_argument("--from-checkpoint", type=str, default=None,
                        help="Resume from a previous data.json (skips completed phases)")
    parser.add_argument("--no-mermaid-thumbnails", action="store_true",
                        help="Use text-only mermaid nodes (no HTML img attempts)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run_date = date.today().isoformat()
    run_dir = str(Path("vault") / "runs" / run_date)

    # Load checkpoint if resuming
    checkpoint = None
    completed_phase = 0
    if args.from_checkpoint:
        checkpoint = load_checkpoint(args.from_checkpoint)
        completed_phase = PHASE_ORDER.get(checkpoint.last_completed_phase, 0)
        videos = checkpoint.videos
    else:
        videos = []

    # Phase 1: Scrape
    if completed_phase >= PHASE_ORDER["scraping"]:
        print(f"Skipping scraping (already completed in checkpoint)")
    else:
        print("Phase 1: Scraping YouTube notifications...")
        videos = scrape_notifications(
            max_days=args.max_days,
            max_videos=args.max_videos,
        )
        if not videos:
            print("No videos found. Nothing to catalog.")
            return
        save_checkpoint(videos, run_dir, phase="scraping")
        print(f"  Scraped {len(videos)} videos")

    # Phase 2: Enrich
    if completed_phase < PHASE_ORDER["enrichment"]:
        print("Phase 2: Enriching video metadata...")
        videos = enrich_videos(videos)
        pre_filter = len(videos)
        videos = [v for v in videos if not v.is_short]
        shorts_removed = pre_filter - len(videos)
        if shorts_removed:
            print(f"  Removed {shorts_removed} Shorts")
        print(f"  Downloading thumbnails...")
        download_thumbnails(videos, run_dir)
        save_checkpoint(videos, run_dir, phase="enrichment", shorts_filtered=shorts_removed)
        print(f"  Enriched {len(videos)} videos")
    else:
        print("Skipping enrichment (already completed in checkpoint)")

    # Phase 3: Categorize & Rank
    if completed_phase < PHASE_ORDER["categorization"]:
        print("Phase 3: Categorizing and ranking videos...")
        videos = categorize_and_rank(videos)
        save_checkpoint(videos, run_dir, phase="categorization")
        print(f"  Categorized {len(videos)} videos")
    else:
        print("Skipping categorization (already completed in checkpoint)")

    # Phase 4: Generate Obsidian vault
    print("Phase 4: Generating Obsidian vault...")
    generate_vault(videos, run_dir,
                   mermaid_thumbnails=not args.no_mermaid_thumbnails)
    print(f"Done! Vault generated at {run_dir}/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create tests/__init__.py**

```bash
touch ~/dev/youtube-cataloger/tests/__init__.py
```

- [ ] **Step 5: Run all tests**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/dev/youtube-cataloger && git add cataloger.py tests/test_cataloger.py tests/__init__.py && git commit -m "feat: add CLI orchestrator with argparse and phase-based execution"
```

---

## Chunk 5: Integration Testing and Polish

### Task 11: End-to-end dry run with mock data

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test that exercises the full pipeline with mock subprocess**

```python
# tests/test_integration.py
"""Integration test: exercises full pipeline with mocked Claude CLI calls."""
import json
from unittest.mock import patch, MagicMock
from models import Video, load_checkpoint
from cataloger import main

MOCK_SCRAPER_OUTPUT = json.dumps([
    {"title": "Python Tutorial", "channel": "CodeAcademy", "url": "https://www.youtube.com/watch?v=py1", "time": "1 day ago"},
    {"title": "ASMR Sleep", "channel": "SleepSounds", "url": "https://www.youtube.com/watch?v=asmr1", "time": "2 days ago"},
    {"title": "Short", "channel": "Shorts", "url": "https://www.youtube.com/shorts/short1", "time": "1 day ago"},
])

MOCK_ENRICHER_OUTPUT = json.dumps([
    {"video_id": "py1", "duration_seconds": 754, "description": "Learn Python basics", "view_count": 12000, "like_count": 500, "upload_date": "2026-03-15", "thumbnail_url": "https://i.ytimg.com/vi/py1/maxres.jpg", "is_short": False},
    {"video_id": "asmr1", "duration_seconds": 3600, "description": "Relaxing sounds for sleep", "view_count": 8000, "like_count": 200, "upload_date": "2026-03-14", "thumbnail_url": "https://i.ytimg.com/vi/asmr1/maxres.jpg", "is_short": False},
])

MOCK_CATEGORIZER_OUTPUT = json.dumps([
    {"video_id": "py1", "category": "programming", "interest_score": 85, "tags": ["python", "tutorial"], "brief_summary": "A beginner Python tutorial"},
    {"video_id": "asmr1", "category": "sleep", "interest_score": 72, "tags": ["asmr", "relaxing"], "brief_summary": "Relaxing sounds for sleeping"},
])

def _mock_subprocess(cmd, **kwargs):
    mock = MagicMock()
    mock.returncode = 0
    prompt = cmd[-1] if cmd else ""
    if "notifications" in prompt:
        mock.stdout = MOCK_SCRAPER_OUTPUT
    elif "IN ORDER" in prompt:
        mock.stdout = MOCK_ENRICHER_OUTPUT
    elif "categorizing" in prompt.lower():
        mock.stdout = MOCK_CATEGORIZER_OUTPUT
    else:
        mock.stdout = "[]"
    return mock

def test_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "runs").mkdir(parents=True)

    with patch("scraper.subprocess.run", side_effect=_mock_subprocess), \
         patch("enricher.subprocess.run", side_effect=_mock_subprocess), \
         patch("enricher.urllib.request.urlretrieve"),  \
         patch("categorizer.subprocess.run", side_effect=_mock_subprocess):
        main(["--no-mermaid-thumbnails"])

    # Verify vault was generated
    import os
    from datetime import date
    run_dir = tmp_path / "vault" / "runs" / date.today().isoformat()
    assert (run_dir / "index.md").exists()
    assert (run_dir / "by-category" / "programming.md").exists()
    assert (run_dir / "by-category" / "sleep.md").exists()
    assert (run_dir / "data.json").exists()

    # Verify checkpoint
    cp = load_checkpoint(str(run_dir / "data.json"))
    assert cp.last_completed_phase == "categorization"
    assert len(cp.videos) == 2  # short was filtered
```

- [ ] **Step 2: Run the integration test**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd ~/dev/youtube-cataloger && git add tests/test_integration.py && git commit -m "test: add end-to-end integration test with mocked subprocess calls"
```

### Task 12: Make cataloger.py executable and add README-like docstring

**Files:**
- Modify: `cataloger.py` (add shebang, verify it's already there)

- [ ] **Step 1: Make executable**

```bash
chmod +x ~/dev/youtube-cataloger/cataloger.py
```

- [ ] **Step 2: Run final full test suite**

Run: `cd ~/dev/youtube-cataloger && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Final commit**

```bash
cd ~/dev/youtube-cataloger && git add cataloger.py && git commit -m "chore: make cataloger.py executable"
```

- [ ] **Step 4: Run the tool with --help to verify CLI**

Run: `cd ~/dev/youtube-cataloger && python cataloger.py --help`
Expected: Shows usage with all options (--max-days, --max-videos, --from-checkpoint, --no-mermaid-thumbnails)
