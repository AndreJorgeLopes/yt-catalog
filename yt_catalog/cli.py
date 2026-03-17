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
    run_parser.add_argument("--source", choices=["chrome", "api"], default="chrome")
    run_parser.add_argument("--max-days", type=int)
    run_parser.add_argument("--max-videos", type=int)
    run_parser.add_argument("--from-checkpoint", type=str)
    run_parser.add_argument("--no-mermaid-thumbnails", action="store_true")

    # yt-catalog setup
    setup_parser = subparsers.add_parser("setup", help="Configure YouTube API OAuth and discover channels")
    setup_parser.add_argument("--api-key-only", action="store_true", help="Skip OAuth, just set API key")

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
    elif args.command == "discover":
        from .commands.discover import handle_discover
        handle_discover(args)
