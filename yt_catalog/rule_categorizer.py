"""Deterministic rule-based video categorization and scoring.

This module is the source of truth for category assignment and interest
scoring. It uses only the video's own metadata (title, channel, duration)
and produces the same output every time for the same input — no AI, no
randomness, no batch-context dependency.
"""
from __future__ import annotations

from .config import CATEGORIES, BASE_SCORES, DURATION_THRESHOLDS, get_duration_group

# ── Channel → category mapping ──────────────────────────────────────────────

CHANNEL_CATEGORY: dict[str, str] = {
    # programming
    "Better Stack": "programming",
    "Jack Herrington": "programming",
    "Code Bullet": "programming",
    "cazz": "programming",
    "b2studios": "programming",
    # tech-news
    "Mrwhosetheboss": "tech-news",
    "Bernardo Almeida": "tech-news",
    "Branch Education": "tech-news",
    "Strange Parts": "tech-news",
    "Cleo Abram": "tech-news",
    "Dr Ben Miles": "tech-news",
    # games
    "mikewater9": "games",
    "slyk": "games",
    "MasterShiny CSGO": "games",
    "Tech-savvy": "games",
    "elsu": "games",
    "juicy": "games",
    "Deep Pocket Monster": "games",
    "viniccius13": "games",
    "MCBYT": "games",
    "Zachobuilds": "games",
    "Ricardo Esteves": "games",
    "Blackjack Advisors": "games",
    # comedy
    "Max Fosh": "comedy",
    "Andri Ragettli": "comedy",
    # hardware
    "GreatScott!": "hardware",
    "styropyro": "hardware",
    "Mike Lake": "hardware",
    "DIY Perks": "hardware",
    "Chris Doel": "hardware",
    "Joe Grand": "hardware",
    # diy-makers
    "Evan and Katelyn": "diy-makers",
    "Evan and Katelyn 2": "diy-makers",
    # sleep
    "Chiropractic Medicine": "sleep",
    "Pain Relief Chiropractic - Dr. Binder Brent": "sleep",
    "Timur Doctorov Live 2": "sleep",
    "Slava Semeshko": "sleep",
    "Emma Womack": "sleep",
    "\uBCF8\uD06C\uB798\uCEE4\uC2A4 BoneCrackers": "sleep",
}

PORTUGUESE_CHANNELS: set[str] = {
    "Bernardo Almeida", "Finan\u00e7as Do Bernardo", "Jo\u00e3o Gra\u00e7a",
    "Diogo Bataguas", "Gastropi\u00e7o", "Leo Xavier", "BetoDH", "Windoh",
    "Ricardo Esteves", "Piloto Diego Higa", "viniccius13", "Andamente",
}

FAVORITE_CHANNELS: set[str] = {
    "Evan and Katelyn", "Evan and Katelyn 2", "Mrwhosetheboss", "Bernardo Almeida",
}


# ── Scoring ──────────────────────────────────────────────────────────────────

def _compute_sleep_score(title: str, duration: int | None) -> int:
    base = 50
    dur = duration or 0
    title_lower = title.lower()
    mod = 0
    if dur > 3600:
        mod += 25
    elif dur > 1800:
        mod += 15
    if any(kw in title_lower for kw in ("sleep", "relax", "nap", "no talking")):
        mod += 10
    if "asmr" in title_lower or "massage" in title_lower:
        mod += 5
    return max(0, min(100, base + mod))


def _compute_interest_score(title: str, channel: str, category: str,
                            duration: int | None) -> int:
    if category == "sleep":
        return _compute_sleep_score(title, duration)

    base = BASE_SCORES.get(category, 30)
    mod = 0

    if channel in PORTUGUESE_CHANNELS:
        mod += 15
    if channel in FAVORITE_CHANNELS:
        mod += 20

    title_lower = title.lower()
    if any(kw in title_lower for kw in ("live", "stream", "giveaway")):
        mod -= 10
    if any(kw in title_lower for kw in ("claude", "ai agent", "mcp")):
        mod += 10

    return max(0, min(100, base + mod))


# ── Tags ─────────────────────────────────────────────────────────────────────

def _generate_tags(title: str, channel: str, category: str) -> list[str]:
    tags: list[str] = []
    tl = title.lower()

    if category == "games":
        if "cs2" in tl or "csgo" in tl:
            tags.append("cs2")
        if "invest" in tl or "market" in tl:
            tags.append("investing")
        if "skin" in tl or "glove" in tl or "knife" in tl:
            tags.append("skins")
        if "pokemon" in tl or "card" in tl:
            tags.append("pokemon")
        if "minecraft" in tl:
            tags.append("minecraft")
        if not tags:
            tags.append("gaming")
    elif category == "programming":
        if "claude" in tl:
            tags.append("claude-code")
        if "ai" in tl or "agent" in tl or "llm" in tl or "gpt" in tl:
            tags.append("ai")
        if "react" in tl or "tanstack" in tl:
            tags.append("react")
        if "docker" in tl or "devops" in tl:
            tags.append("devops")
        if "mcp" in tl:
            tags.append("mcp")
        if not tags:
            tags.append("dev-tools")
    elif category == "tech-news":
        if "samsung" in tl:
            tags.append("samsung")
        if "apple" in tl or "macbook" in tl or "iphone" in tl:
            tags.append("apple")
        if "battery" in tl:
            tags.append("battery")
        if not tags:
            tags.append("tech")
    elif category == "sleep":
        if "asmr" in tl:
            tags.append("asmr")
        if "chiropractic" in tl or "crack" in tl:
            tags.append("chiropractic")
        if "massage" in tl:
            tags.append("massage")
        if not tags:
            tags.append("bodywork")
    elif category == "hardware":
        if "3d print" in tl:
            tags.append("3d-printing")
        if "battery" in tl:
            tags.append("battery")
        if not tags:
            tags.append("electronics")
    elif category == "diy-makers":
        tags.append("diy")
    elif category == "comedy":
        tags.append("entertainment")
    elif category == "general":
        if channel in PORTUGUESE_CHANNELS:
            tags.append("portuguese")
        if not tags:
            tags.append("lifestyle")

    return tags[:5]


# ── Public API ───────────────────────────────────────────────────────────────

def categorize_video(video: dict) -> dict:
    """Categorize a single video dict. Returns a new dict with added fields.

    Input must have: video_id, title, channel, duration_seconds (optional).
    Output adds: category, interest_score, tags, summary, duration_group.

    This function is PURE — same input always produces same output.
    """
    channel = video.get("channel", "")
    title = video.get("title", "")
    duration = video.get("duration_seconds")

    category = CHANNEL_CATEGORY.get(channel, "general")
    score = _compute_interest_score(title, channel, category, duration)
    tags = _generate_tags(title, channel, category)
    summary = f"{channel}: {title[:80]}"
    duration_group = get_duration_group(duration)

    result = dict(video)
    result["category"] = category
    result["interest_score"] = score
    result["tags"] = tags
    result["summary"] = summary
    result["duration_group"] = duration_group
    return result
