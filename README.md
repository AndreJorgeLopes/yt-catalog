<p align="center">
  <h1 align="center">yt-catalog</h1>
  <p align="center">
    <strong>Intelligent YouTube notification cataloger with deterministic scoring, multi-provider AI, and Obsidian vault generation.</strong>
  </p>
  <p align="center">
    <code>pip install -e .</code>&nbsp;&nbsp;|&nbsp;&nbsp;<code>yt-catalog run</code>&nbsp;&nbsp;|&nbsp;&nbsp;<a href="#quick-start">Quick Start</a>
  </p>
</p>

---

## The Problem

YouTube's notification bell is a stream of consciousness — hundreds of uploads from dozens of channels, mixed together with no structure, no priority, and no way to decide *what's actually worth watching next*. You either scroll endlessly or miss content you care about.

## The Solution

`yt-catalog` transforms that chaotic notification stream into a **structured, scored, and visualized knowledge base**. It scrapes your notifications, enriches each video with metadata, categorizes them using a deterministic scoring engine, and generates an Obsidian vault where videos are connected by topic tags — so finishing one video naturally leads you to the next.

### What makes it different

- **Deterministic scoring** — Unlike LLM-based categorization that varies between runs, `yt-catalog` uses a pure-function scoring engine. The same video *always* gets the same score, regardless of batch context or run order. We [prove this mathematically](#scoring-determinism) in our eval suite.
- **Multi-provider AI** — Categorize with Claude, OpenAI, Anthropic API, OpenCode, or Codex CLI. Or skip AI entirely with the rule-based engine. Your choice, your keys, your cost.
- **Two scraping modes** — Chrome automation (reads the bell dropdown directly) or YouTube Data API (polls subscribed channels). Both produce the same output format.
- **Checkpoint resume** — Every phase saves progress. Network failure at video #187? Resume from exactly where you stopped.
- **Sleep content isolation** — ASMR, chiropractic, and massage videos are scored on a separate scale and rendered in their own section. They don't compete with your programming tutorials.

## Architecture

```
                ┌─────────────────────────────────────────────────┐
                │              yt-catalog pipeline                │
                │                                                 │
  Notifications │  Scrape ─→ Enrich ─→ Categorize ─→ Vault Gen   │  Obsidian
  (YouTube)     │    │          │          │             │         │  Vault
                │  Chrome    InnerTube   Rules /       Markdown   │
                │  or API    Player API  AI Provider   + HTML     │
                └─────────────────────────────────────────────────┘
                     │                    │
                 ┌───┴───┐         ┌─────┴──────┐
                 │Chrome │         │Claude CLI  │
                 │YouTube│         │Anthropic   │
                 │Data   │         │OpenAI      │
                 │API v3 │         │OpenCode    │
                 └───────┘         │Codex       │
                                   │Rule engine │
                                   └────────────┘
```

### Four-phase pipeline

| Phase | What it does | Speed |
|-------|-------------|-------|
| **Scrape** | Extracts video IDs + titles from YouTube notifications | ~0s (checkpoint) or ~8s (API) |
| **Enrich** | Fetches duration, views, upload date, thumbnails via InnerTube | **7.6s for 232 videos** (10 concurrent threads) |
| **Categorize** | Assigns category, score, tags, summary to each video | **2ms for 232 videos** (rule engine) |
| **Vault Gen** | Writes Obsidian markdown, mermaid graph, HTML index | <0.01s |

Total pipeline: **~8 seconds** for 200+ videos. See [benchmarks](#benchmarks) for methodology.

### Scoring engine

Every video is scored 0–100 using a deterministic formula:

```
score = base_score(category) + portuguese_boost + favorite_boost + title_signals
```

| Component | Points | Condition |
|-----------|--------|-----------|
| Base score | 30–70 | Varies by category (Programming=70, General=30) |
| Portuguese content | +15 | Channel is Portuguese-language |
| Favorite channel | +20 | Evan and Katelyn, MrWhoseTheBoss, Bernardo Almeida |
| Live/stream penalty | -10 | Title contains "live", "stream", "giveaway" |
| AI/Claude boost | +10 | Title contains "claude", "ai agent", "mcp" |

Sleep content uses a separate formula optimized for relaxation quality (longer = better, ASMR keywords = bonus).

## Quick Start

### One-liner install

```bash
curl -fsSL https://raw.githubusercontent.com/andrejorgelopes/yt-catalog/main/install.sh | bash
```

### Manual install

```bash
git clone https://github.com/andrejorgelopes/yt-catalog.git
cd yt-catalog
pip install -e .
cp .env.example .env    # Configure your API keys
```

### First run

```bash
# Option A: Chrome source (scrapes bell dropdown, no API key needed)
yt-catalog run

# Option B: YouTube API source (faster, needs API key)
yt-catalog run --source api

# Discover your subscribed channels for API mode
yt-catalog discover

# Full OAuth setup (auto-discovers all subscriptions)
yt-catalog setup
```

### View results

```bash
open vault/                                    # Obsidian vault
open vault/runs/2026-03-17/index.html          # HTML visual index
```

## CLI Reference

```
yt-catalog run [OPTIONS]
  --source {chrome,api}          Scraping source (default: chrome)
  --ai-provider {claude-cli,anthropic,openai,opencode-cli,codex-cli,rules}
                                 AI provider for categorization
  --max-days N                   Only process last N days
  --max-videos N                 Cap total videos
  --from-checkpoint PATH         Resume from a checkpoint file
  --no-mermaid-thumbnails        Text-only mermaid nodes

yt-catalog setup                 Configure OAuth + discover channels
yt-catalog discover [PATH]       Extract channel IDs from existing data
yt-catalog --version             Show version
```

## Configuration

### `.env`

```bash
# YouTube Data API (required for --source api)
YOUTUBE_API_KEY=your_key_here

# AI Provider (pick one, default: claude-cli)
AI_PROVIDER=claude-cli           # Claude CLI (supports Chrome integration)
# AI_PROVIDER=anthropic          # Direct Anthropic API
# AI_PROVIDER=openai             # Direct OpenAI API
# AI_PROVIDER=opencode-cli       # OpenCode CLI
# AI_PROVIDER=codex-cli          # Codex CLI
# AI_PROVIDER=rules              # No AI, pure rule engine

# API keys (only needed for the provider you choose)
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
```

> **Note:** Chrome integration (bell dropdown scraping) only works with `claude-cli` as it requires the `claude-in-chrome` MCP extension. Other providers work with `--source api` or `--from-checkpoint`.

### `channels.json`

Auto-populated by `yt-catalog discover`. Maps channel names to YouTube channel IDs for API mode.

### OAuth (optional)

`yt-catalog setup` configures Google OAuth 2.0 with PKCE for automatic subscription discovery. Tokens are stored at `~/.config/yt-catalog/` and auto-refresh.

## Benchmarks

Measured on a real dataset of 321 YouTube notifications (232 non-short videos, 62 channels).

### End-to-end pipeline timing

| Flow | Videos | Enrich | Categorize | Total |
|------|--------|--------|------------|-------|
| **Chrome + InnerTube** | 216 | 7.6s | 2.0ms | **7.6s** |
| **YouTube API** | 142 | included | 0.6ms | **8.3s** |

### Optimization history

| Version | Chrome flow | Improvement |
|---------|-------------|-------------|
| v1 (sequential) | 77.5s | baseline |
| v2 (10-thread parallel) | **7.6s** | **10.2x faster** |

### Scoring determinism

The rule-based categorization engine is a **pure function** — verified by our eval suite:

- Same video scored 10 consecutive times: **0 variance**
- 216 videos re-categorized from golden dataset: **100% match**
- Score independent of batch composition: **verified**
- Full 216-video categorization: **<3ms** (0.01ms/video)

## Eval Suite

149 tests across 12 test files, organized into three evaluation tiers:

### Tier 1: Output Quality (15 tests)
Validates any completed run — no hardcoded counts, works on fresh data:
- No shorts or livestreams leak through filtering
- All videos have category, score (0–100), upload date, thumbnail
- Multiple categories represented, 99%+ have duration data

### Tier 2: Scoring Determinism (6 tests)
Proves the scoring engine is a pure function:
- Identical scores across independent runs
- Portuguese/favorite channel boosts applied consistently
- Sleep channels always categorized correctly
- Full golden dataset regression (216 videos, 0 mismatches)

### Tier 3: Performance (7 tests)
Real API calls with timing budgets:
- Single video enrichment: **< 5 seconds**
- 10-video batch: **< 15 seconds**
- Invalid video graceful failure: **< 30 seconds**
- Full categorization: **< 100 milliseconds**
- Retry mechanism bounded: **< 2 seconds**

### Run evals

```bash
pytest tests/test_eval.py -v              # All eval tiers
pytest tests/test_eval.py -k Performance  # Performance only
pytest tests/test_eval.py -k Determinism  # Scoring only
python benchmark.py                       # Full E2E benchmark
```

## Output Format

### Obsidian vault

Each run generates `vault/runs/YYYY-MM-DD/`:
- `index.md` — Dashboard with mermaid connection graph and video cards
- `by-category/*.md` — Per-category files with duration sub-groups
- `index.html` — Standalone visual grid (YouTube CDN thumbnails)
- `thumbnails/` — Downloaded video thumbnails
- `data.json` — Full checkpoint (resumable)

Videos are rendered as Obsidian callout cards, color-coded by score:
- **Green** (tip): Score >= 80
- **Blue** (info): Score >= 60
- **Gray** (note): Score >= 40
- **Muted** (quote): Score < 40

### Mermaid connection graph

Top 20 videos connected through shared topic tags, colored by category. Click any node to open the YouTube video.

## Project Structure

```
yt_catalog/
  cli.py              # Subcommand routing (run, setup, discover)
  commands/            # Command handlers
  ai_provider.py       # Multi-provider abstraction
  rule_categorizer.py  # Deterministic scoring engine
  enricher.py          # InnerTube parallel enrichment
  api_scraper.py       # YouTube Data API v3 scraper
  scraper.py           # Chrome automation scraper
  vault_generator.py   # Obsidian + HTML output
  oauth.py             # OAuth 2.0 with PKCE + auto-refresh
  models.py            # Video/CatalogRun dataclasses
  config.py            # Constants, prompts, thresholds
  utils.py             # Retry, dotenv loader
```

## Development

```bash
pip install -e ".[dev]"
pytest                        # Full suite (149 tests)
pytest tests/test_eval.py -v  # Eval suite only
python benchmark.py           # E2E benchmark
```

## License

MIT
