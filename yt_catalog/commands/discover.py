"""Handler for `yt-catalog discover` — find channel IDs from YouTube or existing data."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from ..models import load_checkpoint


def _load_channels_json() -> dict[str, str]:
    channels_file = Path.cwd() / "channels.json"
    if not channels_file.exists():
        return {}
    try:
        data = json.loads(channels_file.read_text())
    except Exception:
        return {}
    if isinstance(data, list):
        return {}
    return data if isinstance(data, dict) else {}


def _save_channels_json(channels_map: dict[str, str]) -> dict[str, str]:
    """Merge channels into channels.json. Returns the updated mapping."""
    channels_file = Path.cwd() / "channels.json"
    existing = _load_channels_json()
    existing.update(channels_map)
    channels_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    return existing


def _discover_from_youtube_subscriptions() -> dict[str, str]:
    """Query YouTube for the authenticated user's subscriptions.

    Returns {channel_title: channel_id}. Empty dict if OAuth not configured.
    """
    from ..oauth import is_authenticated, get_access_token
    import urllib.parse
    import urllib.request
    import sys

    if not is_authenticated():
        return {}

    access_token = get_access_token()
    channels: dict[str, str] = {}
    page_token = None

    while True:
        params: dict = {
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
            cid = snippet.get("resourceId", {}).get("channelId")
            title = snippet.get("title", "")
            if cid and title:
                channels[title] = cid

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return channels


def _discover_from_checkpoint(checkpoint_path: str | None) -> dict[str, str]:
    """Resolve channel IDs from a scrape checkpoint via InnerTube."""
    from ..enricher import enrich_videos_innertube

    if checkpoint_path:
        cp_path = checkpoint_path
    else:
        runs_dir = Path("vault/runs")
        if not runs_dir.exists():
            return {}
        cp_path = None
        for d in sorted(runs_dir.iterdir(), reverse=True):
            candidate = d / "data.json"
            if candidate.exists():
                cp_path = str(candidate)
                break
        if not cp_path:
            return {}

    print(f"  Loading checkpoint: {cp_path}")
    checkpoint = load_checkpoint(cp_path)
    videos = checkpoint.videos
    print(f"  {len(videos)} videos loaded")

    missing_id = [v for v in videos if not v.channel_id]
    has_id = [v for v in videos if v.channel_id]
    print(f"  {len(has_id)} already have channel_id, {len(missing_id)} need resolution")

    if missing_id:
        print(f"  Resolving {len(missing_id)} channel IDs via InnerTube API...")
        enrich_videos_innertube(missing_id)

    return {v.channel: v.channel_id for v in videos if v.channel and v.channel_id}


def handle_discover(args: argparse.Namespace) -> None:
    """Discover channels — prefers the live YouTube subscriptions list (OAuth),
    falls back to resolving channel IDs from a scrape checkpoint.

    If OAuth client credentials exist but tokens are missing/invalid, runs the
    reauth flow automatically. If no credentials are saved, instructs the user
    to run `yt-catalog setup` first.
    """
    from ..oauth import is_authenticated, load_config, authorize
    from ..utils import get_data_dir

    # Resolve an explicit checkpoint path before chdir (it may be relative to
    # the invocation dir), then work from the data directory so channels.json
    # is read/written in the same place `run` uses.
    if getattr(args, "checkpoint", None):
        args.checkpoint = str(Path(args.checkpoint).expanduser().resolve())
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(data_dir)
    print(f"Data dir: {data_dir}")

    existing = _load_channels_json()
    before = len(existing)

    if not is_authenticated():
        cfg = load_config()
        client_id = cfg.get("client_id", "")
        client_secret = cfg.get("client_secret", "")
        if client_id and client_secret:
            print("OAuth tokens missing or expired — running reauth...")
            authorize(client_id, client_secret)
        else:
            print("Not authenticated with OAuth and no saved credentials found.")
            print("Run 'yt-catalog setup' first to enable live subscription discovery.")
            print("Falling back to checkpoint discovery.")

    if is_authenticated():
        print("Fetching your YouTube subscriptions via OAuth...")
        yt_channels = _discover_from_youtube_subscriptions()
        if yt_channels:
            new_names = [n for n in yt_channels if n not in existing]
            print(f"  Found {len(yt_channels)} subscriptions ({len(new_names)} new)")
            updated = _save_channels_json(yt_channels)
            print(f"  channels.json: {before} -> {len(updated)}")
            if new_names:
                print("\nNew channels:")
                for name in sorted(new_names):
                    print(f"  + {name}: {yt_channels[name]}")
            return
        print("  No subscriptions returned. Falling back to checkpoint discovery.")

    cp_channels = _discover_from_checkpoint(args.checkpoint)
    if not cp_channels:
        print("  No channel IDs could be resolved.")
        return

    new_names = [n for n in cp_channels if n not in existing]
    updated = _save_channels_json(cp_channels)
    print(f"\nDiscovered {len(cp_channels)} channels from checkpoint ({len(new_names)} new)")
    print(f"  channels.json: {before} -> {len(updated)}")
    if new_names:
        for name in sorted(new_names):
            print(f"  + {name}: {cp_channels[name]}")
