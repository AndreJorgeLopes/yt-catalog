"""Handler for `yt-catalog setup` — configure OAuth credentials for YouTube API."""

from __future__ import annotations
import argparse
import json
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
    print("This sets up OAuth 2.0 for the YouTube Data API.")
    print("(API key is loaded from .env — no setup needed for that)\n")

    print("--- OAuth Setup (unlocks automatic subscription discovery) ---")
    print("1. Go to https://console.cloud.google.com/apis/credentials")
    print("2. Create OAuth 2.0 Client ID (type: Desktop app)")
    print("3. Enter the client ID and secret below\n")

    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("No credentials provided. Setup cancelled.")
        return

    # Save OAuth client credentials
    save_config(client_id, client_secret)

    # Run OAuth flow
    authorize(client_id, client_secret)

    # Auto-discover channels via subscriptions API
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
