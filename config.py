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
    "super-small": (0, 300),
    "small": (300, 600),
    "long": (600, 3000),
    "super-big": (3000, float("inf")),
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

def get_duration_group(duration_seconds: int | None) -> str:
    if duration_seconds is None:
        return "long"
    for group, (low, high) in DURATION_THRESHOLDS.items():
        if low <= duration_seconds < high:
            return group
    return "long"
