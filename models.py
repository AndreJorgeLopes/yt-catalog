from __future__ import annotations
from dataclasses import dataclass, field
import dataclasses
import json
import re
from pathlib import Path
from datetime import datetime, timezone

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
    is_live: bool = False
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
