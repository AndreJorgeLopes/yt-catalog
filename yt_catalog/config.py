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

# Single source of truth for video-length grouping (seconds). Five standardized
# buckets, shared by the by-category folder, the index sub-sections, and the
# Excalidraw board. Order = shortest -> longest.
DURATION_THRESHOLDS = {
    "super-small": (0, 300),       # < 5 min
    "small": (300, 600),           # 5-10 min
    "medium": (600, 1200),         # 10-20 min
    "long": (1200, 3000),          # 20-50 min
    "super-big": (3000, float("inf")),  # 50 min+
}

DURATION_GROUP_ORDER = ["super-small", "small", "medium", "long", "super-big"]

DURATION_GROUP_LABELS = {
    "super-small": "Super Small (<5 min)",
    "small": "Small (5-10 min)",
    "medium": "Medium (10-20 min)",
    "long": "Long (20-50 min)",
    "super-big": "Super Big (>50 min)",
}

# Compact labels for tight spaces (Excalidraw headers).
DURATION_GROUP_SHORT = {
    "super-small": "<5 min",
    "small": "5-10 min",
    "medium": "10-20 min",
    "long": "20-50 min",
    "super-big": "50 min+",
}

PHASE_ORDER = {"scraping": 1, "enrichment": 2, "categorization": 3, "complete": 4}

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

SCRAPER_PROMPT = """Go to https://www.youtube.com

IMPORTANT: Do NOT open https://www.youtube.com/feed/notifications — that page
renders blank. Read the notifications from the bell DROPDOWN instead.

Open the notifications panel by clicking the bell button in the top-right
header (the button with aria-label "Notifications" — a `button#button` inside
`ytd-notification-topbar-button-renderer`). Wait for the dropdown panel
(`ytd-multi-page-menu-renderer`) to appear.

Then extract every notification entry from the OPEN panel:
1. Use javascript_tool to query all `ytd-notification-renderer` elements inside
   the open panel.
2. For each, read:
   - title: the video title text
   - channel: the channel name
   - url: the video link (the anchor whose href contains "watch?v=")
   - time: the relative timestamp (e.g., "3 days ago")
3. Scroll INSIDE the panel (it has its own scroll container, not the page) to
   load more, re-extracting until no new entries appear (3 stable scrolls).
{limits_clause}

Skip any entries that:
- Have no "watch?v=" video link (community posts, channel-only notices)
- Have a URL containing "/shorts/"

Return ONLY a JSON array, no other text.
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

CHANNELS_PROMPT = """Navigate to https://www.youtube.com/feed/channels

This page lists every channel you are subscribed to, each with a notification
bell button that shows your setting: "All", "Personalized", or "None".

Extract EVERY channel on the page:
1. Use javascript_tool to query the subscription rows (each is a
   `ytd-channel-renderer`).
2. For each row read:
   - id: the channel ID (a `UC...` value). Prefer an `a[href*="/channel/UC"]`
     href; if the visible link is a `/@handle`, look for the channelId elsewhere
     in the renderer (data attributes / nested links) and use it. Skip rows
     where no `UC...` id can be found.
   - title: the channel name text
   - bell: the notification setting from the bell button — its `aria-label`
     or visible text — normalized to one of: "All", "Personalized", "None".
3. The page lazy-loads: scroll down and re-extract until the row count stops
   growing (3 stable scrolls).

Return ONLY a JSON array, no prose or markdown fences:
[{{"id": "UC...", "title": "Channel Name", "bell": "All"}}]
"""

HISTORY_PROMPT = """Navigate to https://www.youtube.com/feed/history

IMPORTANT: Do NOT click any item. Just read the DOM.

Extract the user's watch history, stopping once you reach entries older than {since_date}.

Approach:
1. Use javascript_tool to query all `yt-lockup-view-model` elements inside
   `ytd-item-section-renderer`. (NOTE: `ytd-video-renderer` on this page is
   used ONLY for shorts — skip it.)
2. For each `yt-lockup-view-model`, extract:
   - video_id: parsed from `a[href*="watch?v="]` (the `v=` query param). Skip
     entries without a `watch?v=` link.
   - percent_watched: integer 0-100. Read from
     `[class*="WatchedProgressBar"] > div` — the inline `style="width: N%"`
     (sometimes `N.N%`). Round to int. If the element is missing, use 0.
   - watched_on: the nearest preceding date header (`#title` text inside the
     ancestor `ytd-item-section-renderer`) — values like "Today", "Yesterday",
     weekday names ("Sunday"), short dates ("Apr 12"), or "Apr 12, 2026".
     Skip any section whose header is literally "Shorts".
3. To load more entries, do NOT rely on window.scrollTo — YouTube's history
   page has a custom scroll container. Instead, locate the
   `ytd-continuation-item-renderer` and call `scrollIntoView({block: 'end'})`
   on it, then wait ~1.5s. Repeat.
4. Stop scrolling when ANY of these is true:
   - The most recently added date header parses to a date older than {since_date}.
     ("Today"=today, "Yesterday"=today-1, weekday names = within the last 7
     days, short dates like "Apr 12" default to the most recent matching year,
     full dates like "Apr 12, 2026" parse directly.)
   - 5 consecutive scrolls produce zero new entries.
   - You've collected 500 entries (hard cap).

Return ONLY a JSON array of entries in the format:
[{{"video_id": "abc123", "percent_watched": 73, "watched_on": "Apr 15, 2026"}}]
No prose, no markdown fences — just the array.
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
