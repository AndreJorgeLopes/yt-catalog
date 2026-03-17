"""Handler for `yt-catalog setup` — configure API key and OAuth credentials."""

from __future__ import annotations
import argparse
import os


def handle_setup(args: argparse.Namespace) -> None:
    print("=== YouTube Catalog Setup ===\n")

    # Step 1: API key
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        print(f"API key already set (YOUTUBE_API_KEY={api_key[:8]}...)")
    else:
        print("No YOUTUBE_API_KEY found in environment.")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create an API Key with YouTube Data API v3 enabled")
        print("3. Add YOUTUBE_API_KEY=<your-key> to your .env file\n")

    if args.api_key_only:
        print("Setup complete (API key only mode).")
        return

    # Step 2: OAuth (placeholder)
    print("\n--- OAuth Setup (unlocks automatic subscription discovery) ---")
    print("1. Go to https://console.cloud.google.com/apis/credentials")
    print("2. Create OAuth 2.0 Client ID (type: Desktop app)")
    print("3. Note the Client ID and Client Secret")
    print("\nOAuth flow not yet implemented. Coming soon!")
    print("For now, use 'yt-catalog discover' to find channels from existing data.")

    print("\nSetup complete!")
