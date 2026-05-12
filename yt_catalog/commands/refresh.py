"""`yt-catalog refresh` — apply watched/skipped marks from watchlist.md and
regenerate the vault. Reads from the run's data.json checkpoint, so it never
re-downloads or spends API quota."""
from __future__ import annotations
import argparse
import os

from .. import curate, ui
from ..utils import get_data_dir
from ..vault_generator import generate_vault


def handle_refresh(args: argparse.Namespace) -> None:
    os.chdir(get_data_dir())
    run = curate.resolve_run(getattr(args, "run", None))
    if not run or not (run / "data.json").exists():
        ui.err("No run found to refresh. Run `yt-catalog run` first.")
        return

    state = curate.load_state()
    applied, cp = curate.apply_run_marks(run, state)
    curate.save_state(state)

    ui.ok(f"Applied {applied['watched']} watched, {applied['skipped']} skipped, "
          f"{applied.get('reverted', 0)} reverted (from {run.name})")
    with ui.spinner("Regenerating vault (no re-download)"):
        generate_vault(cp.videos, str(run), state=state)
    visible = curate.filter_videos(cp.videos, state)
    hidden = len(cp.videos) - len(visible)
    ui.ok(f"{len(visible)} showing, {hidden} hidden")
    ui.info("Run `yt-catalog insights " + run.name + "` for per-channel skip stats.")
