#!/usr/bin/env python3
"""
Rule-based categorization script for youtube-cataloger run 2026-03-16.
Assigns category, interest_score, tags, summary, and duration_group to each video.
Updates last_completed_phase to "categorization".
"""

import json
import os
from collections import Counter

DATA_PATH = "/Users/andrejorgelopes/dev/youtube-cataloger/vault/runs/2026-03-16/data.json"

# ── Channel → category lookup ─────────────────────────────────────────────────
CHANNEL_CATEGORY = {
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
    "Zachobuilds": "games",          # Minecraft ARG maker
    "Ricardo Esteves": "games",      # Hytale/Pokemon gaming channel (Portuguese)
    # comedy
    "Max Fosh": "comedy",
    "Andri Ragettli": "comedy",
    # hardware
    "GreatScott!": "hardware",
    "styropyro": "hardware",
    "Mike Lake": "hardware",
    "DIY Perks": "hardware",
    "Chris Doel": "hardware",
    # diy-makers
    "Evan and Katelyn": "diy-makers",
    "Evan and Katelyn 2": "diy-makers",
    # sleep
    "Chiropractic Medicine": "sleep",
    "Pain Relief Chiropractic - Dr. Binder Brent": "sleep",
    "Timur Doctorov Live 2": "sleep",
    "Slava Semeshko": "sleep",
    "Emma Womack": "sleep",
    "본크래커스 BoneCrackers": "sleep",
}

# Channels that are always "general"
GENERAL_CHANNELS = {
    "João Graça", "Diogo Bataguas", "Gastropiço", "Windoh",
    "Aperture", "Leo Xavier", "BetoDH", "Eva zu Beck",
    "Yes Theory", "Coffeezilla", "Finanças Do Bernardo",
    "Andamente", "Kurzgesagt – In a Nutshell", "Mark Rober",
    "Michelle Khare", "Alexander The Guest", "struthless",
    "Ren", "James Hype", "CHUPPL",
    "Frankie C", "Corey Eyring", "Chaos Causes", "Matt Ross",
    "Joe Grand", "Keep Everything Yours", "Piloto Diego Higa",
}

# Portuguese channels
PORTUGUESE_CHANNELS = {
    "Bernardo Almeida", "Finanças Do Bernardo", "João Graça",
    "Diogo Bataguas", "Gastropiço", "Leo Xavier", "BetoDH",
    "Windoh", "Ricardo Esteves", "Piloto Diego Higa",
    "viniccius13", "Andamente",
}

# Favourite channels
FAVOURITE_CHANNELS = {"Evan and Katelyn", "Mrwhosetheboss", "Bernardo Almeida"}

# Base interest scores by category
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

# ── Per-video data (category, tags, summary, score_modifier) ─────────────────
# score_modifier is ±15 based on title appeal (applied after base + channel modifiers)
# Entries not listed here will fall through to defaults.

VIDEO_DATA = {
    # ── sleep ─────────────────────────────────────────────────────────────────
    "Z9EbbWa7rnQ": {
        "tags": ["asmr", "massage", "sleep", "full-body"],
        "summary": "ASMR full body massage session by masseuse Albina, covering back, neck, legs, and head.",
        "modifier": 5,
    },
    "a8d6jbWrP1I": {
        "tags": ["chiropractic", "neck", "sleep", "asmr"],
        "summary": "Advanced chiropractic adjustment for neck and groin pain, featuring dramatic cracking and visceral manipulation.",
        "modifier": 0,
    },
    "5M1O_44ejLI": {
        "tags": ["asmr", "chiropractic", "sleep", "cracking"],
        "summary": "ASMR chiropractic session targeting a bulging disc, with body tapping and relaxing cracking sounds.",
        "modifier": 5,
    },
    "HdFCYtAdT28": {
        "tags": ["manual-therapy", "sleep", "asmr", "massage"],
        "summary": "Intense manual therapy session demonstrating scary-sounding but effective techniques for body relaxation.",
        "modifier": 0,
    },
    "uWPCALnQnNw": {
        "tags": ["chiropractic", "sleep", "cracking", "visceral-manipulation"],
        "summary": "Advanced chiropractic pubic bone manipulation for scoliosis treatment, showcasing rare manual therapy techniques.",
        "modifier": -5,
    },
    "SGWmReRMBJY": {
        "tags": ["chiropractic", "asmr", "sleep", "korean"],
        "summary": "Korean chiropractic adjustment and massage ASMR session filmed in 4K.",
        "modifier": 0,
    },
    "Ef43HraLUZY": {
        "tags": ["asmr", "chiropractic", "sleep", "kyphosis"],
        "summary": "ASMR chiropractic session treating kyphosis and scoliosis with rare cracking techniques for relaxation.",
        "modifier": 10,
    },
    "CpvRguDgXv0": {
        "tags": ["asmr", "massage", "sleep", "myofascial"],
        "summary": "Intense 84-minute myofascial full body massage by Aigul, triggering deep tissue work across the entire body.",
        "modifier": 15,
    },
    "hT4yyZBkhOo": {
        "tags": ["asmr", "barbershop", "sleep", "massage"],
        "summary": "Extended barbershop experience with Munur Onkan including haircut, shave, head massage, facial, and back massage.",
        "modifier": 15,
    },
    "AhaDu03iPVY": {
        "tags": ["asmr", "massage", "sleep", "myopressure"],
        "summary": "One hour of intense myopressure therapy session with Galiya, covering the entire body.",
        "modifier": 10,
    },
    "P-7E3cuIwRs": {
        "tags": ["chiropractic", "sleep", "visceral-manipulation", "advanced"],
        "summary": "Advanced chiropractic visceral manipulation targeting throat, gut, and pelvis drainage.",
        "modifier": -5,
    },
    "tFv3-wQ5KJ4": {
        "tags": ["asmr", "chiropractic", "sleep", "cracking"],
        "summary": "ASMR chiropractic session quietly crunching the entire body with liquid massage and tapping sounds.",
        "modifier": 10,
    },
    "4eOe0UgkOvs": {
        "tags": ["massage", "sleep", "manual-therapy", "training"],
        "summary": "Manual therapy training session with masseuse Camilla demonstrating professional massage techniques.",
        "modifier": 0,
    },
    "K0H-LJtg5ms": {
        "tags": ["chiropractic", "sleep", "tmj", "cranial"],
        "summary": "Chiropractic cranial and visceral fluid technique targeting TMJ release and sinus clogging relief.",
        "modifier": 5,
    },
    "rM97cti80EE": {
        "tags": ["asmr", "chiropractic", "sleep", "jaw"],
        "summary": "ASMR chiropractic session targeting jaw bone cracking with full body crunching and therapeutic touch.",
        "modifier": 10,
    },
    "1E2YFYlG8uk": {
        "tags": ["asmr", "massage", "sleep", "head-massage"],
        "summary": "Collection of three head massage sessions including Pakistani, Ayurvedic Indian, and Turkish barbershop styles.",
        "modifier": 15,
    },
    "fmc3WGcrSIg": {
        "tags": ["chiropractic", "sleep", "cracking", "visceral-manipulation"],
        "summary": "Rare chiropractic pubic bone cracking with gut and sinus drainage and relaxing tapping.",
        "modifier": 0,
    },

    # ── programming ──────────────────────────────────────────────────────────
    "U3TXAdpmvVk": {
        "tags": ["claude-code", "ai-agents", "api", "email"],
        "summary": "Overview of AgentMail, an email API platform built specifically for AI agents as an alternative to Gmail for Claude Code users.",
        "modifier": 10,
    },
    "QUHrntlfPo4": {
        "tags": ["claude-code", "ai", "mcp", "context"],
        "summary": "Demonstration of Context Mode MCP server that saves up to 99% of Claude Code context by virtualizing data indexing.",
        "modifier": 15,
    },
    "nxH-BrsCPTo": {
        "tags": ["devops", "secrets", "env-vars", "security"],
        "summary": "Varlock tool eliminates plain text .env files by resolving secrets from 1Password, Bitwarden, and AWS at runtime.",
        "modifier": 10,
    },
    "Xxqu-kz00gw": {
        "tags": ["claude-code", "ai-agents", "automation", "loop"],
        "summary": "Explanation of Claude Code's loop skill for session-based recurring tasks and why it's not meant to replace permanent automation.",
        "modifier": 15,
    },
    "EKG9kX86u0s": {
        "tags": ["claude-code", "ai-agents", "google-workspace", "cli"],
        "summary": "Google's gwscli Rust CLI tool lets AI agents interact with Google Workspace services like email, slides, and calendar from the terminal.",
        "modifier": 10,
    },
    "6x7hh6Qzm9U": {
        "tags": ["claude-code", "ai-tools", "coding-agents", "t3-code"],
        "summary": "T3 Code GUI layer for coding agents reviewed, comparing it to Codex with multi-agent management and PR workflow features.",
        "modifier": 10,
    },
    "8oLP8oxqtOE": {
        "tags": ["claude-code", "terminal", "ai-agents", "cmux"],
        "summary": "CMUX terminal built for AI coding agents enables browser control, subagents in split panes, and workflow management.",
        "modifier": 15,
    },
    "FqD_hlQSQIk": {
        "tags": ["ai-agents", "design-tools", "llm", "podcast"],
        "summary": "Better Stack podcast interview with Pencil.dev creator about AI-powered design tools and multi-agent orchestration.",
        "modifier": 5,
    },
    "pSYEcJTt4t4": {
        "tags": ["ai", "local-llm", "rag", "open-source"],
        "summary": "AnythingLLM as an all-in-one replacement for Ollama, LangChain, and other local AI tools for private RAG workflows.",
        "modifier": 10,
    },
    "c8b-tyFWlg8": {
        "tags": ["ai", "openai", "gpt", "benchmark"],
        "summary": "GPT-5.4 review comparing its coding capabilities and web search against previous OpenAI models.",
        "modifier": 5,
    },
    "MCTTe8nZEgc": {
        "tags": ["ai-agents", "embedded", "esp32", "iot"],
        "summary": "zclaw 888kb AI firmware brings agentic capabilities to a $5 ESP32-C3 microcontroller with Telegram control interface.",
        "modifier": 10,
    },
    "gGKtoykrNYA": {
        "tags": ["productivity", "self-hosted", "open-source", "project-management"],
        "summary": "Huly self-hosted open-source tool demonstrated as a replacement for Notion, Linear, Slack, and GitHub project management.",
        "modifier": 5,
    },
    "lj_xZn-Yf18": {
        "tags": ["claude-code", "git", "worktrees", "ai-agents"],
        "summary": "Claude Code's native git worktree feature enables parallel feature development in isolated branches via --worktree flag.",
        "modifier": 15,
    },
    "_mrMidIwCzk": {
        "tags": ["claude-code", "ai-agents", "multi-agent", "orchestration"],
        "summary": "Gas Town open-source AI agent orchestrator tested by unleashing 20-30 agents simultaneously in a real codebase.",
        "modifier": 10,
    },
    "-DXkF2Q69Jw": {
        "tags": ["github-actions", "ci-cd", "ai-agents", "devops"],
        "summary": "GitHub Agentic Workflows demonstrated as a natural language-based replacement for traditional GitHub Actions CI/CD pipelines.",
        "modifier": 10,
    },
    "jI2mYU8-PqU": {
        "tags": ["browser-api", "mcp", "ai-agents", "webmcp"],
        "summary": "WebMCP browser API proposal backed by Google and Microsoft lets frontend developers expose site features as MCP tools for AI agents.",
        "modifier": 15,
    },
    "H7Xh-x_TVdQ": {
        "tags": ["claude-code", "security", "pentesting", "ai"],
        "summary": "Shanon open-source AI pentesting tool powered by Claude Code autonomously finds XSS, SQL injection, and SSRF vulnerabilities.",
        "modifier": 10,
    },
    "K7y8ZAHQYGY": {
        "tags": ["devops", "sre", "ai", "podcast"],
        "summary": "Better Stack podcast episode on how AI is transforming DevOps and SRE practices with an expert practitioner.",
        "modifier": 5,
    },
    "IAfrzel524s": {
        "tags": ["mcp", "react", "javascript", "browser"],
        "summary": "WebMCP for single page apps demonstrated with a Zustand store integration and Claude MCP-B server.",
        "modifier": 10,
    },
    "V2qjnBDZZ7A": {
        "tags": ["claude-code", "playwright", "mcp", "browser-automation"],
        "summary": "Comparison of Playwright CLI vs MCP Server for Claude Code browser automation tasks, revealing a third superior option.",
        "modifier": 10,
    },
    "yxZxGac5EoQ": {
        "tags": ["vibecoding", "ai-tools", "coding", "tutorial"],
        "summary": "Tutorial on how to vibecode using AI tools, demonstrating the workflow with practical examples.",
        "modifier": 10,
    },
    "YOa99Wpzd3o": {
        "tags": ["tanstack", "ai", "javascript", "image-generation"],
        "summary": "Quick demo of generating images using the TanStack AI package with a practical code walkthrough.",
        "modifier": 5,
    },
    "EnzKA0fQkBM": {
        "tags": ["tanstack", "ssr", "javascript", "react"],
        "summary": "Three reasons to love TanStack Start's SSR capabilities: easy setup, easy disable, and strong typing.",
        "modifier": 5,
    },
    "Jf9DGIyBkm4": {
        "tags": ["api", "open-source", "postman-alternative", "developer-tools"],
        "summary": "Hoppscotch open-source API client reviewed as a lightweight Postman alternative with offline support and free collaboration.",
        "modifier": 5,
    },
    "zAbQE6K0d1k": {
        "tags": ["javascript", "haptics", "mobile", "npm"],
        "summary": "Web Haptics tiny NPM package enables haptic feedback on Android and iOS websites with a single function call.",
        "modifier": 5,
    },
    "EdKTZ7WsaiY": {
        "tags": ["tanstack", "javascript", "hotkeys", "developer-tools"],
        "summary": "TanStack's new hotkey package reviewed: type-safe, framework-agnostic with key sequences and hotkey recording.",
        "modifier": 5,
    },
    "PK5B_xapfxg": {
        "tags": ["open-source", "notion-alternative", "productivity", "developer-tools"],
        "summary": "AFFiNE open-source workspace combines docs, whiteboards, and databases on an infinite canvas as a Notion/Miro alternative.",
        "modifier": 5,
    },
    "t6fbNGC_48c": {
        "tags": ["database", "rust", "sqlite", "benchmark"],
        "summary": "Stoolap Rust-powered database benchmarked against SQLite in Node.js, testing claims of 138x faster analytical queries.",
        "modifier": 5,
    },
    "y8JWZQpWbxQ": {
        "tags": ["ai", "llm", "qwen", "benchmark"],
        "summary": "Alibaba's Qwen 3.5 benchmarked against Claude Sonnet 4.5 on three real-world coding challenges.",
        "modifier": 10,
    },
    "Lw7mrsG58KY": {
        "tags": ["ai", "tts", "voice", "open-source"],
        "summary": "Qwen TTS open-source text-to-speech model demonstrated with emotion control, voice cloning, and real-time streaming.",
        "modifier": 5,
    },
    "cyNv7UzNaU4": {
        "tags": ["docker", "devops", "logs", "monitoring"],
        "summary": "Dozzle lightweight Docker log viewer consolidates all container logs into one browser UI with real-time streaming.",
        "modifier": 5,
    },
    "DzGwnTbQjjg": {
        "tags": ["vercel", "developer-tools", "localhost", "cli"],
        "summary": "Portless Vercel Labs CLI replaces port numbers with stable named addresses for cleaner local development and AI agent workflows.",
        "modifier": 5,
    },
    "cTSvN0YLMgw": {
        "tags": ["ai-tools", "aider", "coding", "refactoring"],
        "summary": "Aider AI terminal tool tested on a real project for multi-file refactors, authentication, tests, and clean Git history.",
        "modifier": 5,
    },
    "k3vyIIEZfU4": {
        "tags": ["react", "cli", "performance", "rust"],
        "summary": "React Doctor Rust-powered CLI scans codebases for React anti-patterns and performance issues.",
        "modifier": 10,
    },
    "244NS-3DkYk": {
        "tags": ["docker", "security", "devops", "vulnerability-scanning"],
        "summary": "Single Docker command using Trivy to scan images, source code, Kubernetes configs, and secrets for vulnerabilities.",
        "modifier": 5,
    },
    "-b1qrPFl04A": {
        "tags": ["developer-tools", "remote-dev", "vscode", "cloud"],
        "summary": "Code-server open-source project lets developers run VS Code on a remote server accessible from any browser.",
        "modifier": 5,
    },
    "lq3rzXP4_vs": {
        "tags": ["claude-code", "ai-tools", "workflow", "superpowers"],
        "summary": "Hands-on comparison of Claude Code's Plan Mode versus the Superpowers plugin with 14 structured workflow skills.",
        "modifier": 15,
    },
    "0xbMm-SWqqI": {
        "tags": ["ai-art", "generative-ai", "wholesome", "b2studios"],
        "summary": "b2studios explores whether generative AI can be wholesome through a creative AI artist character KĀYO.",
        "modifier": 5,
    },
    "0EVEzVz1iTY": {
        "tags": ["ai", "machine-learning", "game-ai", "neural-network"],
        "summary": "Code Bullet uses AI and neural networks to learn and master the chaotic physics game Happy Wheels.",
        "modifier": 15,
    },

    # ── tech-news ─────────────────────────────────────────────────────────────
    "6P3xMmPYElw": {
        "tags": ["macbook", "apple", "review", "portuguese"],
        "summary": "Bernardo Almeida reviews the new MacBook Neo at €600, breaking down Apple's latest laptop announcement.",
        "modifier": 10,
    },
    "YW-yxS6lUGk": {
        "tags": ["tech", "fitness", "wearables", "mrwhosetheboss"],
        "summary": "Mrwhosetheboss experiments with tech gadgets to transform his body in one month for the Sidemen Charity Match.",
        "modifier": 10,
    },
    "AmNVQQ-YOoE": {
        "tags": ["samsung", "smartphone", "review", "s26-ultra"],
        "summary": "Mrwhosetheboss delivers his honest Samsung S26 Ultra review with some things to get off his chest.",
        "modifier": 10,
    },
    "AZJRvpOtSys": {
        "tags": ["apple", "tech-review", "gadgets", "mrwhosetheboss"],
        "summary": "Mrwhosetheboss tests every new Apple product released in a comprehensive hands-on roundup.",
        "modifier": 10,
    },
    "RGGHyY2mN7o": {
        "tags": ["smartphones", "battery", "benchmark", "mrwhosetheboss"],
        "summary": "Ultimate 2026 battery life drain test comparing Samsung S26 Ultra, iPhone 17 Pro Max, Pixel 10 Pro XL, and more.",
        "modifier": 15,
    },
    "ObqHKHoSE5Y": {
        "tags": ["samsung", "s26-ultra", "hands-on", "mrwhosetheboss"],
        "summary": "Mrwhosetheboss hands-on first look at the Samsung Galaxy S26 Ultra detailing what's actually new.",
        "modifier": 10,
    },
    "8q_L727gtB0": {
        "tags": ["gadgets", "cheap-tech", "amazon", "portuguese"],
        "summary": "Bernardo Almeida's friend Rui tests cheap Amazon gadgets including Xiaomi lights, AI translator pens, and smart doorbells.",
        "modifier": 15,
    },
    "YCQLKhB2ywQ": {
        "tags": ["samsung", "battery", "hardware-mod", "strange-parts"],
        "summary": "Strange Parts upgrades the Samsung Trifold battery by 71% using HONOR's silicon-carbon battery technology.",
        "modifier": 10,
    },
    "IHzY-dJmvk8": {
        "tags": ["energy", "china", "turbine", "science"],
        "summary": "China launches the world's first commercial supercritical CO2 turbine, potentially replacing steam-based power generation.",
        "modifier": 10,
    },
    "Yht2joEcW50": {
        "tags": ["samsung", "s26-ultra", "review", "portuguese"],
        "summary": "Bernardo Almeida's detailed review of the Samsung Galaxy S26 Ultra asking if it's the best smartphone of 2026.",
        "modifier": 15,
    },
    "aa6YISbAJEA": {
        "tags": ["computers", "history", "tech-evolution", "education"],
        "summary": "Branch Education traces the incredible evolution of computers from room-sized mainframes to pocket smartphones over 80 years.",
        "modifier": 10,
    },
    "rbxcd9gaims": {
        "tags": ["quantum-computing", "photonics", "science", "psiquantum"],
        "summary": "Dr Ben Miles gets behind-the-scenes access to PsiQuantum, exploring their photonic quantum computing approach.",
        "modifier": 15,
    },

    # ── games ─────────────────────────────────────────────────────────────────
    "Av_SeiKWpnQ": {
        "tags": ["pokemon", "giveaway", "live-stream", "cards"],
        "summary": "Deep Pocket Monster Monday live stream giving away Pokemon card booster packs and graded cards to subscribers.",
        "modifier": 0,
    },
    "YhJY7kk6Zds": {
        "tags": ["cs2", "skins", "gloves", "dead-hand-terminal"],
        "summary": "Analysis of whether the new CS2 Dead Hand Terminal gloves are cheaper than buying from regular cases.",
        "modifier": 10,
    },
    "h6DXtRu4yJw": {
        "tags": ["cs2", "investing", "skins", "valve-update"],
        "summary": "MasterShiny discusses developments in the CS2 investing market around a potential major Valve update.",
        "modifier": 5,
    },
    "FQGUGji9hfo": {
        "tags": ["cs2", "skins", "china", "market-analysis"],
        "summary": "Investigation into suspicious Chinese market activity before the CS2 Dead Hand Terminal update, tracking green skin pumps.",
        "modifier": 10,
    },
    "_wztcaXsce0": {
        "tags": ["cs2", "skins", "legal", "marketplace"],
        "summary": "mikewater9 traces CS2's Original Owner Certificate badge to federal anti-money laundering regulations, revealing hidden features.",
        "modifier": 10,
    },
    "5_PhRilOJhE": {
        "tags": ["cs2", "investing", "valve-update", "skins"],
        "summary": "MasterShiny discusses last-chance CS2 skin investments before Valve's major update drops.",
        "modifier": 5,
    },
    "P3Q7tXk9iHk": {
        "tags": ["cs2", "skins", "gloves", "dead-hand-terminal"],
        "summary": "Tech-savvy opens nearly 100 Dead Hand Terminals, obtaining all gloves, coverts, classifieds, and everything in between.",
        "modifier": 10,
    },
    "VGk_hlOox14": {
        "tags": ["cs2", "skins", "gloves", "knife-combo"],
        "summary": "Showcase of the best CS2 knife and glove combinations for every new glove from the Dead Hand Terminal update.",
        "modifier": 5,
    },
    "7R4lXB3GUio": {
        "tags": ["cs2", "skins", "valve", "dead-hand-terminal"],
        "summary": "mikewater9 finds a graphical error in the Dead Hand Terminal revealing clues about Valve's future update plans.",
        "modifier": 10,
    },
    "LPn96jCJFyE": {
        "tags": ["cs2", "skins", "gloves", "dead-hand-terminal"],
        "summary": "Live reaction to the new Dead Hand Terminal featuring 17 new finishes and 22 new gloves in CS2.",
        "modifier": 5,
    },
    "AaYCKqsQQP0": {
        "tags": ["cs2", "skins", "investing", "collections"],
        "summary": "mikewater9 picks one best investment skin from every CS2 collection, covering 40+ collections with trade-up fundamentals.",
        "modifier": 10,
    },
    "Fcml_3p8dOc": {
        "tags": ["cs2", "cases", "knife", "trade-up"],
        "summary": "MasterShiny opens CS2 cases until getting a knife trade-up, documenting his best knife result.",
        "modifier": 5,
    },
    "-EpvNzTE1uA": {
        "tags": ["cs2", "skins", "investing", "train-collection"],
        "summary": "Analysis of why the Train 2025 Collection may be the best CS2 investment opportunity before the next Armory update.",
        "modifier": 10,
    },
    "j3GvSiaVyuk": {
        "tags": ["cs2", "skins", "valve-update", "market-analysis"],
        "summary": "Analysis of how Valve's small update allowing skin use while listed changes the CS2 steam market dynamic.",
        "modifier": 10,
    },
    "vUwNK_A8A64": {
        "tags": ["cs2", "skins", "gloves", "trade-up"],
        "summary": "Tech-savvy opens the new CS2 gloves terminal and performs multiple trade-ups with the new Driver and Sports Gloves.",
        "modifier": 10,
    },
    "DjJdnLaYXqk": {
        "tags": ["cs2", "investing", "cases", "gloves"],
        "summary": "MasterShiny covers Valve's massive new CS2 case update with new gloves and implications for skin investing.",
        "modifier": 5,
    },
    "kp8ldauHzm4": {
        "tags": ["cs2", "skins", "dead-hand-terminal", "showcase"],
        "summary": "Full showcase of all 39 new weapon skins and gloves added to CS2 in the Dead Hand Terminal Update.",
        "modifier": 5,
    },
    "yMv05DUq2Bs": {
        "tags": ["cs2", "skins", "beginner-guide", "rarity"],
        "summary": "Complete beginner guide to CS2 skins explaining rarity, floats, patterns, cases, and cheapest ways to get skins.",
        "modifier": 5,
    },
    "38QKnoQlIdU": {
        "tags": ["minecraft", "portuguese", "gaming", "automation"],
        "summary": "viniccius13 continues his Minecraft automated house quest, farming children and building automated systems in episode 396.",
        "modifier": 10,
    },
    "b19de2l24mk": {
        "tags": ["cs2", "investing", "skins", "valve"],
        "summary": "MasterShiny explores how Valve recently added more value to CS2 skins and implications for investors.",
        "modifier": 5,
    },
    "1xhUoeNFe5o": {
        "tags": ["pokemon", "cards", "live-stream", "giveaway"],
        "summary": "Deep Pocket Monster live stream opening Pokemon card booster packs and giving away cards to subscribers.",
        "modifier": 0,
    },
    "Yk6KixHNUqU": {
        "tags": ["cs2", "skins", "market-analysis", "china"],
        "summary": "Weekly de_news covering CS2 market cap hitting $5.78B, Germany's X-Ray system, and mysterious green skin pumps.",
        "modifier": 10,
    },
    "9iNpta2oILA": {
        "tags": ["minecraft", "gaming", "mojang", "ban"],
        "summary": "MCBYT reports on Minecraft server blacklists and UK age verification requirements threatening to ban players.",
        "modifier": 5,
    },
    "KkLrHJhnFxI": {
        "tags": ["cs2", "skins", "security", "scams"],
        "summary": "Full guide to protecting CS2 skins from scammers using fake sites, QR codes, API scams, and trade tricks.",
        "modifier": 5,
    },
    "nUGZcM-oGDI": {
        "tags": ["cs2", "skins", "trade-up", "knife"],
        "summary": "Tech-savvy buys 5000 Mil-Spec skins and trades up through the rarity tiers all the way to a knife.",
        "modifier": 10,
    },
    "eW5GDLhKDr0": {
        "tags": ["cs2", "investing", "skins", "timing"],
        "summary": "MasterShiny discusses optimal timing for CS2 skin purchases and which investments are worth buying now.",
        "modifier": 5,
    },
    "AUY0BTsQnGw": {
        "tags": ["cs2", "skins", "investing", "armory"],
        "summary": "mikewater9 reveals his 400-skin Armory positioning strategy with detailed cost basis and exit plan for each collection.",
        "modifier": 10,
    },
    "BTCjmL7fHxk": {
        "tags": ["cs2", "skins", "trade-up", "profit"],
        "summary": "elsu presents 5 CS2 trade-ups under $5 and $10 that can generate significant profit based on his $10,000+ experience.",
        "modifier": 5,
    },
    "9a3H1LzC2IA": {
        "tags": ["cs2", "skins", "inspect", "free-method"],
        "summary": "Free method to inspect any CS2 skin in-game using CS2 Inspect Servers before buying.",
        "modifier": 5,
    },
    "mYmVOnxLOuk": {
        "tags": ["cs2", "skins", "investing", "armory"],
        "summary": "mikewater9's complete armory investment guide covering every CS2 collection with specific skin plays and risk mitigation.",
        "modifier": 10,
    },
    "iWcTlKnUp-U": {
        "tags": ["minecraft", "arg", "mystery", "gaming"],
        "summary": "Zachobuilds investigates a Minecraft ARG where players discover mysterious numbers on their skins they didn't put there.",
        "modifier": 10,
    },
    "4J-BllnCqSU": {
        "tags": ["cs2", "skins", "trade-up", "profit"],
        "summary": "elsu reveals 5 profitable CS2 trade-ups generating 120% profit right now under $5.",
        "modifier": 5,
    },
    "Zfh3w89lVDE": {
        "tags": ["cs2", "skins", "trade-up", "guide"],
        "summary": "Tech-savvy's comprehensive 2026 guide to profitable CS2 trade-ups covering everything needed to start making profit.",
        "modifier": 10,
    },
    "UkgWU36MSqU": {
        "tags": ["cs2", "skins", "trade-up", "exploit"],
        "summary": "mikewater9 reverse-engineers a CS2 float mechanics exploit found in a Chinese inventory used for systematic trade-ups.",
        "modifier": 15,
    },
    "aXAiaSdq8mg": {
        "tags": ["pokemon", "cards", "pack-opening", "investing"],
        "summary": "juicy takes advantage of the new borrow feature for a secret pack opening strategy yielding wild pulls.",
        "modifier": 5,
    },
    "uHLd7sPpoNo": {
        "tags": ["pokemon", "cards", "giveaway", "japanese"],
        "summary": "Deep Pocket Monster gives away his entire collection of Japanese Gengar Pokemon cards after failing a collection challenge.",
        "modifier": 5,
    },
    "TT60qB16wwg": {
        "tags": ["pokemon", "cards", "live-stream", "giveaway"],
        "summary": "Deep Pocket Monster live stream opening Pokemon card booster packs and giving away cards over two hours.",
        "modifier": 0,
    },
    "TOYAHiPThK8": {
        "tags": ["cs2", "skins", "market-analysis", "stickers"],
        "summary": "mikewater9's February 2026 CS2 market recap covering stickers up 30%, armory deadline, and China's red envelopes.",
        "modifier": 10,
    },
    "9ngmUEQ1LZ8": {
        "tags": ["cs2", "investing", "skins", "market-update"],
        "summary": "MasterShiny surveys what's currently happening in the CS2 investing market with key developments.",
        "modifier": 5,
    },
    "YBEZ2j_iYpI": {
        "tags": ["cs2", "skins", "budget", "guide"],
        "summary": "Guide to 30 best cheap CS2 skins under $10 that look expensive, covering AK-47, M4A1-S, AWP, and more.",
        "modifier": 5,
    },
    "SdWazke4-M0": {
        "tags": ["cs2", "skins", "china", "armory"],
        "summary": "de_news CS2 market intelligence covering Chinese buying activity and armory positioning before key deadline.",
        "modifier": 10,
    },
    "A81u2MNUSCo": {
        "tags": ["cs2", "legal", "lawsuit", "valve"],
        "summary": "Detailed breakdown of NY Attorney General's 52-page lawsuit against Valve for operating CS2 loot boxes as illegal gambling.",
        "modifier": 15,
    },
    "VHoM7Y0sezQ": {
        "tags": ["cs2", "skins", "souvenir", "collections"],
        "summary": "mikewater9 analyzes which CS2 souvenir collections are next to be removed based on ROI patterns and supply data.",
        "modifier": 10,
    },
    "mYmVOnxLOuk": {
        "tags": ["cs2", "skins", "armory", "investing"],
        "summary": "Complete CS2 armory investment guide covering every collection, skin plays, and exit strategy before Armory rotation.",
        "modifier": 10,
    },
    "Uwnfs81NPNU": {
        "tags": ["cs2", "skins", "lawsuit", "legal"],
        "summary": "Tech-savvy covers the New York Attorney General lawsuit against Valve and potential impact on CS2 skin market.",
        "modifier": 10,
    },
    "Zf1SR5UC5ug": {
        "tags": ["cs2", "skins", "china", "market-analysis"],
        "summary": "de_news weekly analysis showing Chinese market targeting green-colored CS2 skins across 11 of the top 100 movers.",
        "modifier": 10,
    },
    "vYtm1QoBpG4": {
        "tags": ["cs2", "skins", "china", "pump-protocol"],
        "summary": "Breakdown of how Chinese pump groups test CS2 skin liquidity in two steps before committing capital.",
        "modifier": 10,
    },
    "eopNuy8B9Gk": {
        "tags": ["cs2", "skins", "case-shortage", "supply"],
        "summary": "de_news covering Trainwreck case opening impact on CS2 supply, snakebite feedback loop, and armory deadline plays.",
        "modifier": 5,
    },
    "YkYbNl6z6d0": {
        "tags": ["cs2", "skins", "armory", "float-mechanics"],
        "summary": "Analysis of why CS2 armory 0-1 float skins are rarer than expected and how Train 2025 is a manipulation target.",
        "modifier": 10,
    },
    "pDmrm1zpv88": {
        "tags": ["cs2", "skins", "knife", "trade-up"],
        "summary": "Four months after the knife trade-up update, analysis of how CS2 market reached new equilibrium and which pools to target.",
        "modifier": 10,
    },
    "P9c0FNmBV1o": {
        "tags": ["pokemon", "cards", "pack-opening", "arms-dealer"],
        "summary": "juicy dives into the new Arms Dealer update in Pokemon TCG Pocket, reacting to wild card swings and upgrades.",
        "modifier": 5,
    },
    "Zbta-Eyjvqg": {
        "tags": ["cs2", "skins", "loadout", "celebration"],
        "summary": "mikewater9 celebrates 10K subscribers by showcasing his dream CS2 loadout with best knives, M4A1-S, AK-47, and AWP.",
        "modifier": 5,
    },
    "WI0-dYwKWE4": {
        "tags": ["cs2", "skins", "trade-up", "rare"],
        "summary": "Tech-savvy reacts to incredible knife trade-up results including Karambit Blue Gem outcomes.",
        "modifier": 10,
    },
    "fyIFTIm1L1U": {
        "tags": ["cs2", "skins", "investing", "market-analysis"],
        "summary": "mikewater9 explains the thin market problem using CSGO Weapon Case 1's 30% spike after Trainwreck stream.",
        "modifier": 10,
    },
    "ctZqR4Wf1LA": {
        "tags": ["cs2", "skins", "investing", "website"],
        "summary": "mikewater9 launches CS2Liquid.com with paper trading, trade-up calculators, portfolio tracking, and leaderboards.",
        "modifier": 10,
    },
    "UT0uo-1fUhQ": {
        "tags": ["cs2", "skins", "operations", "history"],
        "summary": "Analysis of why Operation Riptide's Train Collection broke the supply curve, permanently distorting the CS2 rarity ecosystem.",
        "modifier": 10,
    },
    "y6ZN1bQhXmI": {
        "tags": ["cs2", "skins", "market-analysis", "china"],
        "summary": "de_news CS2 market gained 4.37% while traditional markets stumbled, with Chinese New Year liquidity returning.",
        "modifier": 5,
    },
    "07G321OZFsU": {
        "tags": ["cs2", "skins", "armory", "release-date"],
        "summary": "slyk predicts the release date of the next CS2 Armory update based on historical patterns and which collections rotate out.",
        "modifier": 5,
    },
    "hmIMZktvUic": {
        "tags": ["cs2", "skins", "armory", "strategy"],
        "summary": "Best strategies for spending CS2 Armory Stars for maximum profit, covering short-term resells and long-term holds.",
        "modifier": 5,
    },
    "NqM-jQ-wdCA": {
        "tags": ["cs2", "investing", "skins", "buying"],
        "summary": "MasterShiny reveals what CS2 skin investments he is actively buying right now and why.",
        "modifier": 5,
    },
    "KM7fEtmGUmk": {
        "tags": ["cs2", "investing", "skins", "upcoming"],
        "summary": "MasterShiny previews upcoming developments in the CS2 investing landscape and what to watch for.",
        "modifier": 5,
    },
    "pEvm3DvlV6g": {
        "tags": ["cs2", "investing", "skins", "market"],
        "summary": "MasterShiny discusses how the market has finally recognized a key CS2 investing opportunity.",
        "modifier": 5,
    },
    "xzcbl8_UgEU": {
        "tags": ["cs2", "investing", "skins", "timing"],
        "summary": "MasterShiny analyzes whether now is the right time to buy specific CS2 investments.",
        "modifier": 5,
    },
    "N52ACQhuomg": {
        "tags": ["cs2", "investing", "cases", "buying"],
        "summary": "MasterShiny's top 5 CS2 cases to buy right now for investing based on current market conditions.",
        "modifier": 5,
    },
    "JYHcJaH_0Wc": {
        "tags": ["cs2", "investing", "skins", "overview"],
        "summary": "MasterShiny's comprehensive overview of everything to know for CS2 investing right now.",
        "modifier": 5,
    },
    "7wEVXjDfZZM": {
        "tags": ["cs2", "investing", "skins", "timing"],
        "summary": "MasterShiny declares it's finally time for CS2 investing and explains why conditions are right.",
        "modifier": 5,
    },
    "ZgREKmCq0CM": {
        "tags": ["gta6", "gaming", "analysis", "portuguese"],
        "summary": "Ricardo Esteves analyzes all 70 official GTA 6 screenshots in detail, sharing his opinions on each.",
        "modifier": 5,
    },
    "anMiSaXqOTQ": {
        "tags": ["pokemon", "gaming", "review", "portuguese"],
        "summary": "Ricardo Esteves gives his honest review of Pokemon Winds & Waves revealed at Nintendo Direct Pokemon Day 2026.",
        "modifier": 5,
    },
    "CaXP7dHcO_4": {
        "tags": ["hytale", "gaming", "portuguese", "lets-play"],
        "summary": "Ricardo Esteves explores the frozen north zones in Hytale Adventure Episode 10, searching for Adamantite resources.",
        "modifier": 5,
    },
    "-sQh3Dram4Q": {
        "tags": ["hytale", "gaming", "portuguese", "lets-play"],
        "summary": "Ricardo Esteves continues his Hytale adventure in Episode 9, delving into the jungle biome for Adamantite.",
        "modifier": 5,
    },
    "x-1LrEAfJak": {
        "tags": ["pokemon", "cards", "live-stream", "giveaway"],
        "summary": "Deep Pocket Monster live stream opening Pokemon card booster packs with giveaways for subscribers.",
        "modifier": 0,
    },
    "R5GZqsqm6Yk": {
        "tags": ["pokemon", "cards", "live-stream", "giveaway"],
        "summary": "Deep Pocket Monster live stream opening booster packs and giving away graded Pokemon cards.",
        "modifier": 0,
    },

    # ── hardware ──────────────────────────────────────────────────────────────
    "Xda1chrQ4yQ": {
        "tags": ["electronics", "esp32", "radar", "led"],
        "summary": "GreatScott! uses an ESP32 with a radar board to control SK6812 LEDs for stair lights that activate on presence detection.",
        "modifier": 10,
    },
    "FOzF3fgcSzY": {
        "tags": ["3d-printing", "porsche", "f1", "live-stream"],
        "summary": "Mike Lake goes live with his 3D printed Porsche and F1 car builds to answer questions.",
        "modifier": 5,
    },
    "64x8mRzGStc": {
        "tags": ["3d-printing", "f1-car", "engineering", "automotive"],
        "summary": "Mike Lake attempts to 3D print an entire 2026 Formula 1 car aiming to make it run, drive, and drift.",
        "modifier": 15,
    },
    "PKXFP40N1t4": {
        "tags": ["battery", "electronics", "3d-printing", "diy"],
        "summary": "GreatScott! explores a weldless battery design as a potentially safer future battery building method.",
        "modifier": 10,
    },
    "HwoZg3BCigU": {
        "tags": ["battery", "electric", "recycling", "engineering"],
        "summary": "Chris Doel harvests batteries from 500 disposable vapes to build a 50V pack that powers a road-legal electric car.",
        "modifier": 15,
    },
    "rqCt61ZbU10": {
        "tags": ["led", "electronics", "diy", "high-power"],
        "summary": "DIY Perks builds a massive LED supernova using one of the world's brightest LEDs, exploring extreme power requirements.",
        "modifier": 15,
    },
    "fYbEfvGsNyg": {
        "tags": ["3d-printing", "porsche", "automotive", "engineering"],
        "summary": "Mike Lake takes risks installing genuine Porsche GT3 tail lights in his 3D printed Porsche GT3 replica.",
        "modifier": 10,
    },
    "OC7sNfNuTNU": {
        "tags": ["electronics", "battery", "car-batteries", "experiments"],
        "summary": "styropyro wires 400 car batteries together in a massive electronics experiment.",
        "modifier": 15,
    },
    "c2aR1aYPACE": {
        "tags": ["3d-printing", "porsche", "live-stream", "q-and-a"],
        "summary": "Mike Lake hosts a live Q&A session with his 3D printed Porsche GT3 RS to answer audience questions.",
        "modifier": 5,
    },
    "n5KC1TlKKwQ": {
        "tags": ["electronics", "shielding", "emi", "wifi"],
        "summary": "GreatScott! demonstrates how to stop WiFi jammers and other radiation using EMI shielding materials.",
        "modifier": 10,
    },
    "8WeyDGfK-jA": {
        "tags": ["3d-printing", "porsche", "cnc", "automotive"],
        "summary": "Mike Lake installs custom billet CNC machined Porsche GT3 wing risers on his 3D printed Porsche GT3 RS.",
        "modifier": 10,
    },

    # ── diy-makers ────────────────────────────────────────────────────────────
    "_y0XMhQ1-gc": {
        "tags": ["diy", "desk", "streaming-setup", "3d-printing"],
        "summary": "Evan and Katelyn build a sit/stand streaming desk with all their gear attached using a Bambu Lab H2S printer.",
        "modifier": 10,
    },
    "jRwBRjIrqXg": {
        "tags": ["diy", "keyboard", "maker", "crafting"],
        "summary": "Evan and Katelyn make sandpaper keycaps for a keyboard — a horrible but hilarious idea.",
        "modifier": 15,
    },

    # ── comedy ────────────────────────────────────────────────────────────────
    "QQ5mdh4ZNNo": {
        "tags": ["skiing", "freeski", "competition", "behind-the-scenes"],
        "summary": "Andri Ragettli mic'd up at the LAAX Open Slopestyle Finals for a behind-the-scenes view of a worldcup competition day.",
        "modifier": 5,
    },
    "U19xB9zEJCg": {
        "tags": ["comedy", "prank", "bald-men", "proposal"],
        "summary": "Max Fosh hires 20 bald men for a wedding proposal in a hilarious comedy video.",
        "modifier": 15,
    },
    "noOZH3hKjYk": {
        "tags": ["skiing", "motivation", "sports", "andri-ragettli"],
        "summary": "Andri Ragettli motivation video about overcoming setbacks in his freeskiing career with 'you vs you' theme.",
        "modifier": -5,
    },

    # ── general ───────────────────────────────────────────────────────────────
    "ZlT14gVR3ys": {
        "tags": ["dj", "music", "transitions", "practice"],
        "summary": "DJ James Hype practices new transitions for 1 hour straight using CDJ 3000X equipment.",
        "modifier": -10,
    },
    "_c4zwCErDJY": {
        "tags": ["portugal", "history", "podcast", "portuguese"],
        "summary": "Diogo Bataguas' podcast episode about Portugal in war, featuring comedian Sérgio Fernandes as guest.",
        "modifier": 10,
    },
    "VxNZSCGuY1M": {
        "tags": ["poker", "tournament", "comedy", "gaming"],
        "summary": "Frankie C lets his girlfriend play a poker tournament for him with amusing results.",
        "modifier": -5,
    },
    "MhJoJRqJ0Wc": {
        "tags": ["crypto", "hardware-wallet", "security", "hacking"],
        "summary": "Joe Grand attempts to crack $75 million worth of Trezor crypto wallets using refined hardware hacking methods.",
        "modifier": 5,
    },
    "kZn3TY9RDu4": {
        "tags": ["startup", "business", "shareholder", "weekly"],
        "summary": "Keep Everything Yours weekly shareholder meeting reviewing income and expenses for the past week.",
        "modifier": -15,
    },
    "LJVY7_v_c08": {
        "tags": ["civilization", "philosophy", "kardashev", "science"],
        "summary": "Aperture explores why humanity is stuck at the bottom of the Kardashev scale and what the highest levels of civilization look like.",
        "modifier": 5,
    },
    "I8zRh9Fv07Q": {
        "tags": ["bmw", "car-build", "project-car", "automotive"],
        "summary": "Matt Ross explains why he abandoned his S54 S30 M3 dream build as the project falls apart.",
        "modifier": -5,
    },
    "Tr7AM-dHGDQ": {
        "tags": ["philosophy", "ai", "society", "compilation"],
        "summary": "Aperture compilation of five urgent essays on forces reshaping modern society including AI sloppification and addiction.",
        "modifier": 5,
    },
    "Ry9z2IPQq_k": {
        "tags": ["finance", "investing", "portuguese", "portfolio"],
        "summary": "Finanças Do Bernardo reveals all his February 2026 investment portfolio changes in his monthly series.",
        "modifier": 10,
    },
    "72iQm9ZlfZU": {
        "tags": ["podcast", "portuguese", "interview", "sports"],
        "summary": "João Graça interviews Guilherme Domingos in the fourth episode of the Ângulo 2.0 podcast season 2.",
        "modifier": 5,
    },
    "SJxeohVL8Bc": {
        "tags": ["portuguese", "personal-development", "discipline", "vlog"],
        "summary": "BetoDH documents his attempt to improve personal discipline and daily routines.",
        "modifier": 5,
    },
    "7q6_7hduVus": {
        "tags": ["travel", "overlanding", "adventure", "border-crossing"],
        "summary": "Eva zu Beck breaks her number one overlanding rule when crossing into a new country during her expedition.",
        "modifier": 5,
    },
    "Bys-GLT6dMM": {
        "tags": ["portuguese", "self-improvement", "anger-management", "mindset"],
        "summary": "Leo Xavier explains a Japanese system for never getting angry or bothered by other people.",
        "modifier": 5,
    },
    "niGM8pIG2a4": {
        "tags": ["motorcycle", "honda", "review", "test-ride"],
        "summary": "Chaos Causes spends 127 hours with a cheap Honda CB1000 Hornet SP testing if it's a budget super naked.",
        "modifier": -5,
    },
    "beGWfPSMcA0": {
        "tags": ["podcast", "portuguese", "solo", "comedy"],
        "summary": "João Graça's solo podcast 'Inconsciente' episode 3 touching on weak weeks, uncertain ideas, and returns.",
        "modifier": 5,
    },
    "HBT2JZKrvQU": {
        "tags": ["music", "documentary", "ren", "starry-night"],
        "summary": "Documentary on Ren's 'Vincents Tale - Starry Night' musical work, exploring the creation behind the release.",
        "modifier": -5,
    },
    "srr0rRgF2Fw": {
        "tags": ["ai", "deepfakes", "scams", "investigative"],
        "summary": "Coffeezilla investigates AI deepfakes as the biggest threat powering scams, propaganda, and harassment.",
        "modifier": 10,
    },
    "PLbU-2hjgJc": {
        "tags": ["finance", "saving", "portuguese", "tips"],
        "summary": "Finanças Do Bernardo reveals 10 ways to save money at the end of each month in 2026.",
        "modifier": 10,
    },
    "tG6-GYhtB7M": {
        "tags": ["food", "portuguese", "chanfana", "culture"],
        "summary": "Gastropiço travels to Miranda do Corvo to discover the traditional origin of chanfana, a Portuguese slow-cooked goat dish.",
        "modifier": 10,
    },
    "yDAAlojz8NU": {
        "tags": ["space", "science", "cosmos", "voids"],
        "summary": "Kurzgesagt explores cosmic voids, the terrifying emptiness that makes up most of the universe.",
        "modifier": 5,
    },
    "IhabRwly_gA": {
        "tags": ["dj", "music", "tour", "vlog"],
        "summary": "James Hype takes his fiancée Tita Lau on the Australian tour, with her opening as support act at every show.",
        "modifier": -10,
    },
    "FPIdKjvjOMY": {
        "tags": ["finance", "salary", "portuguese", "portugal"],
        "summary": "Finanças Do Bernardo calculates the ideal salary needed to live well in Portugal based on real living costs.",
        "modifier": 10,
    },
    "dnLPtZofjGY": {
        "tags": ["portuguese", "focus", "productivity", "self-improvement"],
        "summary": "Leo Xavier teaches how to improve concentration before it's too late with five actionable steps.",
        "modifier": 5,
    },
    "WjVVBF4eRnI": {
        "tags": ["podcast", "portuguese", "solo", "commentary"],
        "summary": "João Graça's solo podcast 'Inconsciente' episode 2 covering weak weeks and uncertain ideas.",
        "modifier": 5,
    },
    "nqL7BX550ks": {
        "tags": ["music", "portuguese", "acoustic", "angulo"],
        "summary": "João Graça's Ângulo series features Afonso Dubraz performing acoustic version of 'Amanhã'.",
        "modifier": 5,
    },
    "IawmKGcCbCY": {
        "tags": ["poker", "tournament", "comeback", "asia"],
        "summary": "Frankie C documents the greatest poker comeback of his life at the first ever Asian Poker Tour Championship.",
        "modifier": -5,
    },
    "dUuMcBMkkQc": {
        "tags": ["startup", "business", "shareholder", "weekly"],
        "summary": "Keep Everything Yours weekly shareholder meeting reviewing income and expenses for the week.",
        "modifier": -15,
    },
    "mE_9smOVZ_4": {
        "tags": ["poker", "giveaway", "tournament", "taiwan"],
        "summary": "Frankie C gives away a poker bankroll to a finalist who competed for months for the chance.",
        "modifier": -5,
    },
    "NDZcmCa40ZY": {
        "tags": ["portuguese", "podcast", "comedy", "return"],
        "summary": "Diogo Bataguas returns with season 3 episode 1 of his Conteúdo do Batáguas podcast series.",
        "modifier": 10,
    },
    "8_wiuDd691s": {
        "tags": ["travel", "adventure", "india", "pakistan"],
        "summary": "Yes Theory spends 24 hours in both India and Pakistan, two countries with deep historical tensions.",
        "modifier": 5,
    },
    "tswqCgoflQk": {
        "tags": ["philosophy", "religion", "belief", "aperture"],
        "summary": "Aperture explores hidden structures of belief and levels of religious faith that most people never question.",
        "modifier": 5,
    },
    "hvPwEWxQ_kQ": {
        "tags": ["politics", "propaganda", "media", "analysis"],
        "summary": "struthless analyzes how the Epstein Files release is a masterclass in propaganda and media manipulation.",
        "modifier": 5,
    },
    "Ub-JrGE289s": {
        "tags": ["dj", "music", "edm", "live-set"],
        "summary": "James Hype performs live at Kinetic Field EDC Mexico 2026.",
        "modifier": -10,
    },
    "4AgLUjFZaC8": {
        "tags": ["podcast", "portuguese", "interview", "music"],
        "summary": "João Graça's Ângulo 2.0 podcast episode 3 featuring musician Afonso Dubraz discussing being a fan, concerts, and surprises.",
        "modifier": 5,
    },
    "Zu6FECEYwks": {
        "tags": ["philosophy", "death", "existential", "compilation"],
        "summary": "Aperture compilation sitting with the question of death — what it is, what it costs, and whether escaping it is worth it.",
        "modifier": 5,
    },
    "B0dmlUBelvg": {
        "tags": ["portuguese", "ferrari", "car", "lifestyle"],
        "summary": "Windoh documents how he bought his dream Ferrari 812 GTS and shows his friends' reactions.",
        "modifier": 10,
    },
    "H0hzG_Kc_6k": {
        "tags": ["food", "portuguese", "alentejo", "tradition"],
        "summary": "Gastropiço visits the Day of Slaughter event in Alentejo celebrating the traditional Portuguese pig butchering tradition.",
        "modifier": 10,
    },
    "xAjPsfWNilI": {
        "tags": ["finance", "ai", "portuguese", "income"],
        "summary": "Finanças Do Bernardo shows how he used AI tools to earn extra money in Portugal.",
        "modifier": 10,
    },
    "FVmhORTYm1w": {
        "tags": ["drift", "automotive", "portuguese", "mexico"],
        "summary": "Piloto Diego Higa's first time drifting in Mexico, traveling from Santos to São Paulo and then to the track.",
        "modifier": 5,
    },
    "GQ_vdeDEE5c": {
        "tags": ["portuguese", "urbex", "abandoned", "palace"],
        "summary": "Andamente explores a ruined €5 million Portuguese palace with secret tunnels.",
        "modifier": 10,
    },
    "OTdE_ncNPNg": {
        "tags": ["travel", "adventure", "sahara", "minefield"],
        "summary": "Eva zu Beck drives alone through the world's longest minefield in Morocco-occupied Western Sahara.",
        "modifier": 10,
    },
    "wfXaOGZuH4s": {
        "tags": ["car", "bmw", "project-car", "vlog"],
        "summary": "Matt Ross makes the biggest move of his car building life, betting everything on an ambitious project.",
        "modifier": -5,
    },
    "fwkNPON96ao": {
        "tags": ["podcast", "portuguese", "solo", "benfica"],
        "summary": "João Graça's first 'Inconsciente' solo podcast episode discussing Benfica solutions and personal returns.",
        "modifier": 5,
    },
    "jvRnnbtU6C0": {
        "tags": ["podcast", "portuguese", "solo", "truth"],
        "summary": "João Graça's 'Inconsciente' episode 0 starting the solo podcast series with 'the truth sets you free'.",
        "modifier": 5,
    },
    "3x6hiS0E_7w": {
        "tags": ["philosophy", "consciousness", "self-awareness", "aperture"],
        "summary": "Aperture explores the terrifying paradox of self-awareness and what it means for a species to know itself.",
        "modifier": 5,
    },
    "5HgxcEEjQoA": {
        "tags": ["quantum-mechanics", "consciousness", "physics", "aperture"],
        "summary": "Aperture dives into quantum consciousness theory, exploring the observer problem in quantum physics.",
        "modifier": 10,
    },
    "vSz_VHoIeVc": {
        "tags": ["philosophy", "knowledge", "science", "aperture"],
        "summary": "Aperture explores the knowledge paradox — how human knowledge that elevated civilization may also be our downfall.",
        "modifier": 5,
    },
    "Ai03Kt-PMIM": {
        "tags": ["food", "peru", "travel", "documentary"],
        "summary": "Alexander The Guest travels to Peru to discover one of the world's most unique high-altitude restaurants by chef Virgilio Martinez.",
        "modifier": 5,
    },
    "ttmMJyiIz6E": {
        "tags": ["food", "monaco", "luxury", "restaurant"],
        "summary": "Alexander The Guest dines at Le Louis XV by Alain Ducasse in Monaco, one of the world's most luxurious restaurants.",
        "modifier": 5,
    },
    "Xg1ro-zG7AM": {
        "tags": ["engineering", "rc-car", "junkyard", "mark-rober"],
        "summary": "Mark Rober organizes an engineers vs junkyard RC car death match challenge for kids to learn through failure.",
        "modifier": 5,
    },
    "gDWTKhlkfpI": {
        "tags": ["food", "restaurant", "comparison", "challenge"],
        "summary": "Michelle Khare works both a $1 and $1000 restaurant to experience the full spectrum of the food service industry.",
        "modifier": 5,
    },
    "9t5m33ccUYA": {
        "tags": ["health", "ozempic", "weight-loss", "science"],
        "summary": "Kurzgesagt examines the uncomfortable truth about Ozempic and what it reveals about obesity science.",
        "modifier": 5,
    },
    "pARu6Th18C4": {
        "tags": ["poker", "tournament", "high-stakes", "win"],
        "summary": "Corey Eyring documents the biggest win of his poker career with $50,000 on the line.",
        "modifier": -5,
    },
    "9Yz4Eyj0Aa4": {
        "tags": ["poker", "high-stakes", "risk", "tournament"],
        "summary": "Corey Eyring risks $52,000 in one night at the biggest poker game of his year.",
        "modifier": -5,
    },
    "orOuL7cHYKc": {
        "tags": ["poker", "tournament", "profit", "week"],
        "summary": "Corey Eyring has the most profitable week of his life in poker.",
        "modifier": -5,
    },
    "35IMvo4GnCc": {
        "tags": ["poker", "bankroll", "controversy", "2026"],
        "summary": "Corey Eyring's second episode of From Broke to Millionaire in 1 Year series with controversial moments.",
        "modifier": -5,
    },
    "Y4Qw5s3mfWY": {
        "tags": ["poker", "win", "bankroll", "2026"],
        "summary": "Corey Eyring starts 2026 with the biggest win of his life in a high-stakes poker game.",
        "modifier": -5,
    },
    "0jbHFhKcQS4": {
        "tags": ["poker", "high-stakes", "bankroll", "week"],
        "summary": "Frankie C documents gambling a yearly salary in one week at the highest stakes of his life.",
        "modifier": -5,
    },
    "pARu6Th18C4": {
        "tags": ["poker", "tournament", "high-stakes", "win"],
        "summary": "Corey Eyring documents the biggest win of his poker career with $50,000 on the line.",
        "modifier": -5,
    },
    "DEHqKhnjSsI": {
        "tags": ["motorcycle", "ktm", "rebuild", "project"],
        "summary": "Chaos Causes begins rebuilding a destroyed KTM 1290 Super Duke from scratch with missing parts.",
        "modifier": -5,
    },
    "lfWSBJS-R88": {
        "tags": ["car", "corvette", "salvage", "rebuild"],
        "summary": "Matt Ross rebuilds a salvage auction C7 Z06 with 650hp for a surprisingly cheap cost.",
        "modifier": -5,
    },
    "nXrY3eduoNg": {
        "tags": ["car", "corvette", "insurance-total", "repair"],
        "summary": "Matt Ross buys an insurance-totaled 650HP C7 Z06 and fixes it for only $38.",
        "modifier": -5,
    },
    "I8zRh9Fv07Q": {
        "tags": ["bmw", "car-build", "abandoned", "project"],
        "summary": "Matt Ross explains why he abandoned his S54 S30 M3 dream build as the project falls apart.",
        "modifier": -5,
    },
    "C_2cE21MM7s": {
        "tags": ["travel", "adventure", "pakistan", "yes-theory"],
        "summary": "Yes Theory goes inside Pakistan's most dangerous city for a surreal travel experience.",
        "modifier": 5,
    },
    "KhT5l6gP-Ts": {
        "tags": ["travel", "sahara", "adventure", "eva-zu-beck"],
        "summary": "Eva zu Beck spends 5 days alone in the Sahara desert, getting stuck and surviving a sandstorm.",
        "modifier": 10,
    },
    "s0b9TbV-vyo": {
        "tags": ["finance", "investing", "portuguese", "beginners"],
        "summary": "Finanças Do Bernardo explains step-by-step how to start investing in 2026 for complete beginners.",
        "modifier": 10,
    },
    "FPIdKjvjOMY": {
        "tags": ["finance", "salary", "portuguese", "portugal"],
        "summary": "Finanças Do Bernardo calculates the ideal salary needed to live well in Portugal.",
        "modifier": 10,
    },
    "4pXQtgw3N3g": {
        "tags": ["portuguese", "habits", "self-improvement", "japanese"],
        "summary": "Leo Xavier teaches the Japanese system for eliminating bad habits using philosophy of change.",
        "modifier": 5,
    },
    "7vqsX6gha9A": {
        "tags": ["portuguese", "mindset", "self-improvement", "danger"],
        "summary": "Leo Xavier discusses the most dangerous thought pattern and how to overcome the comfort zone trap.",
        "modifier": 5,
    },
    "QRqeIOpiwpk": {
        "tags": ["portuguese", "cars", "abandoned", "exploration"],
        "summary": "Andamente visits the largest classic car cemetery in Portugal, discovering dozens of forgotten vehicles.",
        "modifier": 10,
    },
    "pMLbLkAjeaU": {
        "tags": ["portuguese", "recovery", "personal", "vlog"],
        "summary": "BetoDH discusses the unspoken parts of recovery that nobody talks about.",
        "modifier": 5,
    },
    "AY4Eu-YMToA": {
        "tags": ["portuguese", "ferrari", "car", "vlog"],
        "summary": "Windoh reveals his new Ferrari 812 GTS dream car in a short vlog.",
        "modifier": 10,
    },
    "lhOGl817bVc": {
        "tags": ["food", "portuguese", "traditional", "recipe"],
        "summary": "Gastropiço shares his favorite obscure traditional Portuguese dish that few people know about.",
        "modifier": 10,
    },
    "jGeE63gQluU": {
        "tags": ["portuguese", "drift", "lexus", "automotive"],
        "summary": "Piloto Diego Higa rebuilds a 1000hp Lexus 2JZ for the Fueltech Velopark opening caravan in Rio Grande do Sul.",
        "modifier": 5,
    },
    "nLuhA3ccYno": {
        "tags": ["gaming", "stardew-valley", "live-stream", "chill"],
        "summary": "CHUPPL plays Stardew Valley live with collaborator KatAbughazaleh for a relaxed farming game session.",
        "modifier": -10,
    },
    "8uOk4MEf2UQ": {
        "tags": ["startup", "business", "makerworld", "3d-printing"],
        "summary": "Keep Everything Yours first shareholder meeting covering startup expenses and Etsy shop operations.",
        "modifier": -15,
    },
    "1w0LgdsEdXc": {
        "tags": ["startup", "business", "weekly", "recap"],
        "summary": "Keep Everything Yours weekly shareholder meeting covering first two months of business operations.",
        "modifier": -15,
    },
}

def get_duration_group(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 300:
        return "super-small"
    elif seconds < 600:
        return "small"
    elif seconds < 3000:
        return "long"
    else:
        return "super-big"


def compute_sleep_score(video):
    """Separate scoring for sleep category."""
    base = 50
    dur = video.get("duration_seconds") or 0
    title_lower = (video.get("title") or "").lower()
    mod = 0
    if dur > 3600:
        mod += 25
    elif dur > 1800:
        mod += 15
    if "sleep" in title_lower:
        mod += 10
    # Extra appeal for ASMR / massage
    if "asmr" in title_lower or "massage" in title_lower:
        mod += 5
    vd = VIDEO_DATA.get(video["video_id"], {})
    mod += vd.get("modifier", 0)
    return max(0, min(100, base + mod))


def compute_interest_score(video, category):
    if category == "sleep":
        return compute_sleep_score(video)

    channel = video.get("channel", "")
    base = BASE_SCORES.get(category, 30)
    mod = 0

    # Portuguese bonus
    if channel in PORTUGUESE_CHANNELS:
        mod += 15
    # Title contains portuguese indicators
    title = (video.get("title") or "")
    # Favourite channel bonus
    if channel in FAVOURITE_CHANNELS:
        mod += 20

    # Per-video modifier
    vd = VIDEO_DATA.get(video["video_id"], {})
    mod += vd.get("modifier", 0)

    return max(0, min(100, base + mod))


def categorize(video):
    channel = video["channel"]
    vid = video["video_id"]

    # Determine category
    if channel in CHANNEL_CATEGORY:
        category = CHANNEL_CATEGORY[channel]
    elif channel in GENERAL_CHANNELS:
        category = "general"
    else:
        # Fallback: unknown channels go to general
        category = "general"

    # Get per-video data
    vd = VIDEO_DATA.get(vid, {})
    tags = vd.get("tags", ["uncategorized"])
    summary = vd.get("summary", f"{channel} video: {video.get('title', '')[:80]}")

    interest_score = compute_interest_score(video, category)
    duration_group = get_duration_group(video.get("duration_seconds"))

    return {
        "category": category,
        "interest_score": interest_score,
        "tags": tags,
        "summary": summary,
        "duration_group": duration_group,
    }


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    videos = data["videos"]
    print(f"Processing {len(videos)} videos...")

    category_counts = Counter()
    for video in videos:
        result = categorize(video)
        video["category"] = result["category"]
        video["interest_score"] = result["interest_score"]
        video["tags"] = result["tags"]
        video["summary"] = result["summary"]
        video["duration_group"] = result["duration_group"]
        category_counts[result["category"]] += 1

    data["last_completed_phase"] = "categorization"

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n=== Categorization Complete ===")
    print(f"Total videos: {len(videos)}")
    print("\nCategory breakdown:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:15s}: {count:3d}")

    print("\nTop 10 videos by interest score:")
    non_sleep = sorted(
        [v for v in videos if v["category"] != "sleep"],
        key=lambda v: v["interest_score"],
        reverse=True,
    )[:10]
    for v in non_sleep:
        print(f"  [{v['interest_score']:3d}] [{v['category']:12s}] {v['title'][:60]}")

    print("\nTop 5 sleep videos by score:")
    sleep_vids = sorted(
        [v for v in videos if v["category"] == "sleep"],
        key=lambda v: v["interest_score"],
        reverse=True,
    )[:5]
    for v in sleep_vids:
        print(f"  [{v['interest_score']:3d}] {v['title'][:70]}")

    print(f"\nFile written to: {DATA_PATH}")


if __name__ == "__main__":
    main()
