"""Handler for `yt-catalog setup` — configure API key and OAuth credentials."""

from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

from ..oauth import (
    authorize,
    save_config,
    load_config,
    is_authenticated,
    get_access_token,
    CONFIG_DIR,
)


def _discover_subscriptions_oauth() -> dict[str, str]:
    """Use OAuth to list the user's YouTube subscriptions.

    Returns a dict of {channel_title: channel_id}.
    """
    access_token = get_access_token()
    channels: dict[str, str] = {}
    page_token = None

    while True:
        params: dict[str, str | int] = {
            "part": "snippet",
            "mine": "true",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        url = (
            "https://www.googleapis.com/youtube/v3/subscriptions?"
            + urllib.parse.urlencode(params)
        )
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {access_token}")

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
        except Exception as e:
            print(f"Warning: Failed to fetch subscriptions page: {e}", file=sys.stderr)
            break

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            rid = snippet.get("resourceId", {})
            channel_id = rid.get("channelId")
            title = snippet.get("title", "")
            if channel_id and title:
                channels[title] = channel_id

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return channels


def handle_setup(args: argparse.Namespace) -> None:
    print("=== YouTube Catalog Setup ===\n")

    # Step 1: API key
    existing_config = load_config()
    api_key = os.environ.get("YOUTUBE_API_KEY") or existing_config.get("api_key")

    if api_key:
        print(f"API key found: {api_key[:8]}...")
    else:
        print("No YOUTUBE_API_KEY found.")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create an API Key with YouTube Data API v3 enabled")
        api_key = input("\nAPI Key (or press Enter to skip): ").strip() or None

    if args.api_key_only:
        if api_key:
            save_config(
                client_id=existing_config.get("client_id", ""),
                client_secret=existing_config.get("client_secret", ""),
                api_key=api_key,
            )
            print(f"\nAPI key saved to {CONFIG_DIR}/config.json")
        print("Setup complete (API key only mode).")
        return

    # Step 2: OAuth
    print("\n--- OAuth Setup (unlocks automatic subscription discovery) ---")
    print("1. Go to https://console.cloud.google.com/apis/credentials")
    print("2. Create OAuth 2.0 Client ID (type: Desktop app)")
    print("3. Enter the client ID and secret below\n")

    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Skipping OAuth (no credentials provided).")
        if api_key:
            save_config(client_id="", client_secret="", api_key=api_key)
        print("Setup complete!")
        return

    # Save config before OAuth flow (needed for token refresh later)
    save_config(client_id, client_secret, api_key)

    # Run OAuth flow
    authorize(client_id, client_secret)

    # Step 3: Auto-discover channels via subscriptions API
    if is_authenticated():
        print("\n--- Discovering subscribed channels ---")
        channels = _discover_subscriptions_oauth()
        if channels:
            from pathlib import Path

            channels_file = Path.cwd() / "channels.json"
            existing: dict = {}
            if channels_file.exists():
                try:
                    existing = json.loads(channels_file.read_text())
                    if isinstance(existing, list):
                        existing = {}
                except Exception:
                    existing = {}
            existing.update(channels)
            channels_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            print(f"  Saved {len(existing)} channels to channels.json")
            print(f"  ({len(channels)} discovered via subscriptions)")
        else:
            print("  No subscriptions found (or API error).")

    print("\nSetup complete!")
