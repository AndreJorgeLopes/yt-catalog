# yt-catalog

Scrape your YouTube notifications, categorize them with AI, and generate a beautiful Obsidian vault to find what to watch next.

## Features

- Scrapes YouTube notifications (Chrome automation or YouTube Data API)
- Auto-categorizes into 8 groups (Programming, Tech News, Games, Comedy, Hardware, DIY/Makers, General, Sleep)
- Interest scoring (0–100) based on your preferences and channel favorites
- Obsidian vault with callout-card layout and mermaid graph connections
- Standalone HTML visual index with thumbnail grids
- Separate sleep content tier (ASMR, chiropractic, massage)
- Checkpoint-based resume — never lose progress on a long run

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/andrejorgelopes/yt-catalog/main/install.sh | bash
```

## Manual Install

```bash
git clone <repo> && cd yt-catalog
pip install -e .
cp .env.example .env  # Add your YOUTUBE_API_KEY (optional for Chrome source)
```

## Usage

```bash
# First time setup
yt-catalog setup        # Configure OAuth and API key
yt-catalog discover     # Find your subscribed channel IDs

# Run the cataloger
yt-catalog run                     # Chrome source (default, no API key needed)
yt-catalog run --source api        # YouTube Data API source
yt-catalog run --max-days 7        # Last 7 days only
yt-catalog run --max-videos 100    # Cap at 100 videos

# Resume from checkpoint after a failed run
yt-catalog run --from-checkpoint vault/runs/2026-03-17/data.json

# Open vault in Obsidian (macOS)
open vault/
```

## How It Works

```
Scrape  →  Enrich  →  Categorize  →  Generate Vault
```

1. **Scrape** — Chrome automation reads your `/feed/notifications` page, or the YouTube Data API polls your subscribed channels.
2. **Enrich** — Fetches duration, upload date, view count, and thumbnail URL for each video.
3. **Categorize** — Claude AI assigns a category, interest score (0–100), topic tags, and a 1-sentence summary to every video.
4. **Generate vault** — Writes Obsidian-ready markdown with callout cards, a mermaid connection graph, and a standalone `index.html` for browser viewing.

Each run is saved to `vault/runs/YYYY-MM-DD/` and never overwrites previous runs.

## Configuration

### `.env`

```env
YOUTUBE_API_KEY=AIza...          # Required for --source api
ANTHROPIC_API_KEY=sk-ant-...     # Required for categorization
```

### `channels.json`

Populated automatically by `yt-catalog discover`. Used by `--source api`.

```json
{
  "Fireship": "UCsBjURrPoezykLs9EqgamOA",
  "Linus Tech Tips": "UCXuqSBlHAE6Xw-yeJA0Tunw"
}
```

### OAuth (optional)

`yt-catalog setup` walks you through Google OAuth so the API scraper can read private subscription data without needing a public API key per channel.

## Development

```bash
pip install -e ".[dev]"
pytest
pytest tests/test_vault_generator.py -v   # vault generation only
```

Tests live in `tests/`. The suite has 134 tests covering scraping, enrichment, categorization, vault generation, and the CLI commands.
