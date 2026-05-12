"""Handler for `yt-catalog reauth` — re-run OAuth authorization with saved credentials."""

from __future__ import annotations
import argparse
import sys

from ..oauth import authorize, load_config


def handle_reauth(args: argparse.Namespace) -> None:
    """Re-run the OAuth authorization flow using previously saved client credentials.

    Unlike `setup`, this does NOT prompt for client_id/secret — it reuses the
    values saved by a prior `setup` run. Use this when OAuth tokens have expired
    or been revoked and you need to refresh them without re-entering credentials.
    """
    config = load_config()
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not client_id or not client_secret:
        print("No saved OAuth credentials found.", file=sys.stderr)
        print("Run 'yt-catalog setup' first to configure them.", file=sys.stderr)
        sys.exit(1)

    print("Re-running OAuth authorization with saved credentials...")
    authorize(client_id, client_secret)
