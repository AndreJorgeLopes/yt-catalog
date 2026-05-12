"""Handler for `yt-catalog setup` — configure OAuth credentials for YouTube API."""

from __future__ import annotations
import argparse
import json
import shutil
import sys
import urllib.parse
import urllib.request

from .. import browser_login
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


def _check_web_session() -> None:
    """Verify the headless web-session prerequisites (bell channels + history).

    The web session powers bell channels + watch history. Two ways to get
    cookies; this reports what's available and points at the robust one.
    """
    from .. import web_session

    print("\n--- Web session (bell channels + watch history) ---")
    have_cookies = web_session.COOKIE_FILE.exists() and \
        web_session.has_auth_cookies(web_session.load_cookies())
    if have_cookies:
        print(f"  [ok] A cookie session already exists at {web_session.COOKIE_FILE}.")
    else:
        print("  [ ] No cookie session yet.")

    # Option C (recommended): dedicated-browser login — survives the device-bound
    # re-challenge that invalidates yt-dlp-exported cookies.
    print("\n  Recommended — capture a durable session in a dedicated browser:")
    print("        yt-catalog login")
    if browser_login._playwright_available():
        print("    [ok] Playwright is installed.")
    else:
        print("    [!] Needs Playwright (one-time):")
        print("          pip install 'yt-catalog[login]'")
        print("          playwright install chromium")
    print("    First run opens a window to log in once; afterwards")
    print("    `yt-catalog login --headless` refreshes it silently. A week idle")
    print("    is fine — you only re-login on logout / password change.")

    # Lighter fallback: yt-dlp export. Works, but Google re-challenges it on
    # macOS via SIDTS rotation, so it goes stale faster.
    print("\n  Lighter fallback — export cookies from your browser via yt-dlp:")
    if shutil.which("yt-dlp") is None:
        print("    [!] yt-dlp NOT found. Install: pipx install yt-dlp (or brew).")
    else:
        print("    [ok] yt-dlp found. The tool can export on demand (the one-time")
        print("         macOS Keychain prompt approves Chrome's Safe Storage key).")
    print("    Note: yt-dlp-exported cookies are best-effort — Google rotates the")
    print("    session and they can read logged-out. `yt-catalog login` avoids that.")


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

    _check_web_session()
    _install_obsidian()

    print("\nSetup complete!")


def _install_obsidian() -> None:
    """Install the Obsidian plugin + CSS snippet (shift-click skip + refresh button)."""
    from ..obsidian_setup import install_obsidian_assets
    from ..utils import get_data_dir

    print("\n--- Obsidian helpers (skip-checkbox plugin + refresh button + CSS) ---")
    vault_root = get_data_dir() / "vault"
    try:
        vault_root.mkdir(parents=True, exist_ok=True)
        out = install_obsidian_assets(vault_root)
        print(f"  [ok] Installed plugin -> {out['plugin']}")
        print(f"  [ok] Installed CSS snippet -> {out['snippet']}")
        print("  In Obsidian: Settings -> Community plugins -> turn OFF Restricted")
        print("  mode, then enable 'YT Catalog Skip Checkbox'. Settings ->")
        print("  Appearance -> CSS snippets -> reload + enable 'yt-catalog-checkboxes'.")
        print("  Button requirements: desktop Obsidian, and `yt-catalog` on your")
        print("  login-shell PATH (the button runs it via $SHELL -lc).")
    except Exception as e:
        print(f"  [!] Could not install Obsidian assets ({type(e).__name__}: {e}).")
