"""CLI entry point with subcommands: run, setup, discover."""

from __future__ import annotations
import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="yt-catalog",
        description="YouTube Notification Cataloger",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # yt-catalog run
    run_parser = subparsers.add_parser("run", help="Scrape, categorize, and generate vault")
    run_parser.add_argument(
        "--source", choices=["web", "chrome", "api", "auto"], default="auto",
        help="Where to fetch videos. 'auto' (default) uses the YouTube Data API "
             "when credentials are configured, else Chrome scraping. 'web' uses "
             "the headless cookie session (your subscriptions feed) and falls "
             "back web -> chrome -> api. (Bell channels and watch history always "
             "try the cookie session first regardless of this flag.)",
    )
    run_parser.add_argument(
        "--data-dir", type=str, metavar="PATH", default=None,
        help="Directory holding the catalog data (vault/, runs/, channels.json). "
             "When given, it's saved to settings and reused on future runs. "
             "Default: the current folder if it's already a catalog dir, else "
             "the saved location, else ~/.local/share/yt-catalog.",
    )
    run_parser.add_argument(
        "--fetch-channels", action="store_true",
        help="Force a re-scrape of your notification (bell) channels from "
             "youtube.com/feed/channels via Chrome. Otherwise this runs "
             "automatically on the first run and about once a week.",
    )
    run_parser.add_argument(
        "--channels", type=str, metavar="PATH",
        help="Use channel IDs from this JSON file as the scrape source instead "
             "of your subscriptions (e.g. bell_all_channels.json = your "
             "bell-on channels). Accepts a list of IDs, a {name: id} map, or a "
             "list of {id,title} objects.",
    )
    run_parser.add_argument(
        "--max-days", type=int, metavar="N",
        help="Only fetch videos uploaded in the last N days. Default: unset "
             "(full lookback on the first run; since the previous run's "
             "watermark on incremental runs).",
    )
    run_parser.add_argument(
        "--max-videos", type=int, metavar="N",
        help="Cap the total number of videos fetched. Default: unset (no cap).",
    )
    run_parser.add_argument(
        "--from-checkpoint", type=str, metavar="PATH",
        help="Resume from a previous run's data.json checkpoint, skipping "
             "already-completed phases. Default: unset (auto-detect).",
    )
    run_parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore any saved checkpoint and start a brand-new run from "
             "scratch (skips resume auto-detection). Default: off.",
    )
    run_parser.add_argument(
        "--no-mermaid-thumbnails", action="store_true",
        help="Render mermaid graph nodes as text only, without thumbnail "
             "images. Default: off (thumbnails are shown).",
    )
    run_parser.add_argument(
        "--ai-provider",
        choices=["claude-cli", "opencode-cli", "codex-cli", "anthropic", "openai", "rules"],
        default=None,
        help="AI provider for categorization. Overrides the AI_PROVIDER env "
             "var. 'rules' = no AI (pure rule-based scoring). Default: "
             "claude-cli (or AI_PROVIDER if set); falls back to rules if the "
             "provider fails.",
    )
    run_parser.add_argument(
        "--filter-watched", action="store_true",
        help="Drop videos you've already watched at least --watched-threshold%%. "
             "Default: off. Watch history is read via Chrome (the YouTube Data "
             "API cannot expose it), so this is slower; after an API scrape "
             "you'll be asked to confirm the Chrome pass first.",
    )
    run_parser.add_argument(
        "--bell", action="store_true",
        help="Read notifications from the YouTube bell dropdown via Chrome "
             "instead of fetching recent uploads via RSS. Default: off. Implies "
             "the chrome path; slower and depends on the browser integration.",
    )
    run_parser.add_argument(
        "--watched-threshold", type=int, default=50, metavar="PCT",
        help="Percent of a video you must have watched for it to count as "
             "'seen' and be dropped by --filter-watched. Default: 50. No effect "
             "unless --filter-watched is passed.",
    )

    # yt-catalog setup
    setup_parser = subparsers.add_parser("setup", help="Configure YouTube API OAuth and discover channels")

    # yt-catalog reauth
    reauth_parser = subparsers.add_parser("reauth", help="Re-run OAuth authorization with saved credentials")

    # yt-catalog login (Option C — dedicated-browser cookie capture)
    login_parser = subparsers.add_parser(
        "login",
        help="Log into YouTube in a dedicated browser profile and capture "
             "cookies for the headless web session (bell, history, --source web)")
    login_parser.add_argument(
        "--headless", action="store_true",
        help="Refresh cookies silently from the already-logged-in profile "
             "(no window). First-time login must be run WITHOUT this flag.")

    # yt-catalog subscriptions
    subs_parser = subparsers.add_parser(
        "subscriptions",
        help="Dump the API's subscription list (avatar + name) to vault/subscriptions.md")

    # yt-catalog refresh
    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Apply watched/skipped checkbox marks from the vault and regenerate (no re-download)")
    refresh_parser.add_argument(
        "run", nargs="?", default=None,
        help="Run directory or its data.json (default: the latest run)")

    # yt-catalog insights
    insights_parser = subparsers.add_parser(
        "insights",
        help="Build a run's insights.md from your watched/skipped marks (per-channel "
             "/ per-category skip stats). Does not hide videos — that's `refresh`.")
    insights_parser.add_argument(
        "run", nargs="?", default=None,
        help="Run directory or its data.json (default: the latest run)")

    # yt-catalog discover
    discover_parser = subparsers.add_parser("discover", help="Discover channel IDs from existing data")
    discover_parser.add_argument("checkpoint", nargs="?", default=None, help="Path to data.json checkpoint")

    args = parser.parse_args(argv)

    from .utils import load_dotenv
    load_dotenv()

    if args.command == "run":
        from .commands.run import handle_run
        handle_run(args)
    elif args.command == "setup":
        from .commands.setup import handle_setup
        handle_setup(args)
    elif args.command == "reauth":
        from .commands.reauth import handle_reauth
        handle_reauth(args)
    elif args.command == "login":
        from .commands.login import handle_login
        handle_login(args)
    elif args.command == "subscriptions":
        from .commands.subscriptions import handle_subscriptions
        handle_subscriptions(args)
    elif args.command == "refresh":
        from .commands.refresh import handle_refresh
        handle_refresh(args)
    elif args.command == "insights":
        from .commands.insights import handle_insights
        handle_insights(args)
    elif args.command == "discover":
        from .commands.discover import handle_discover
        handle_discover(args)
