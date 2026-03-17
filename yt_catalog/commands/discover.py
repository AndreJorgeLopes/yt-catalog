"""Handler for `yt-catalog discover` — find channel IDs from existing data."""

from __future__ import annotations
import argparse
import json
from pathlib import Path

from ..models import load_checkpoint


def _save_channels_json(channels_map: dict[str, str]) -> None:
    """Save channel name->ID mapping to channels.json for future API runs."""
    channels_file = Path.cwd() / "channels.json"
    existing: dict = {}
    if channels_file.exists():
        try:
            existing = json.loads(channels_file.read_text())
            if isinstance(existing, list):
                existing = {}
        except Exception:
            existing = {}
    existing.update(channels_map)
    channels_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"  Saved {len(existing)} channels to channels.json")


def handle_discover(args: argparse.Namespace) -> None:
    """Discover channel IDs from existing data or via InnerTube API.

    1. Loads videos from a checkpoint (or finds the latest run)
    2. For videos missing channel_id, calls InnerTube player API to resolve it
    3. Saves {channel_name: channel_id} to channels.json
    """
    from ..enricher import enrich_videos_innertube

    checkpoint_path = args.checkpoint

    # Find checkpoint
    if checkpoint_path:
        cp_path = checkpoint_path
    else:
        # Find the latest run
        runs_dir = Path("vault/runs")
        if not runs_dir.exists():
            print("No runs found. Run a scrape first with: yt-catalog run")
            return
        run_dirs = sorted(runs_dir.iterdir(), reverse=True)
        cp_path = None
        for d in run_dirs:
            candidate = d / "data.json"
            if candidate.exists():
                cp_path = str(candidate)
                break
        if not cp_path:
            print("No checkpoint found in vault/runs/. Run a scrape first.")
            return

    print(f"Loading checkpoint: {cp_path}")
    checkpoint = load_checkpoint(cp_path)
    videos = checkpoint.videos
    print(f"  {len(videos)} videos loaded")

    # Check which videos already have channel_id
    missing_id = [v for v in videos if not v.channel_id]
    has_id = [v for v in videos if v.channel_id]
    print(f"  {len(has_id)} already have channel_id, {len(missing_id)} need resolution")

    if missing_id:
        print(f"  Resolving {len(missing_id)} channel IDs via InnerTube API...")
        enrich_videos_innertube(missing_id)

    # Build channel map
    channels_map: dict[str, str] = {}
    for v in videos:
        if v.channel and v.channel_id and v.channel not in channels_map:
            channels_map[v.channel] = v.channel_id

    if not channels_map:
        print("  No channel IDs could be resolved.")
        return

    _save_channels_json(channels_map)
    print(f"\nDiscovered {len(channels_map)} unique channels:")
    for name, cid in sorted(channels_map.items()):
        print(f"  {name}: {cid}")
