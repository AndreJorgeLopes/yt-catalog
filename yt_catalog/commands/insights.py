"""`yt-catalog insights [run]` — (re)build a run's insights.md from your
watched/skipped marks.

Applies the run's watchlist checkbox marks to the GLOBAL curation state (the
skip signal accumulates across runs), then writes ONLY that run's `insights.md`
with the per-channel / per-category skip stats. It does NOT regenerate the rest
of the vault or hide videos — that's `yt-catalog refresh`'s job.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

from .. import curate, ui
from ..utils import get_data_dir
from ..vault_generator import generate_insights


def handle_insights(args: argparse.Namespace) -> None:
    os.chdir(get_data_dir())
    run = curate.resolve_run(getattr(args, "run", None))
    if not run or not (run / "data.json").exists():
        ui.err("No run found. Pass a run dir, or run `yt-catalog run` first.")
        return

    ui.header("yt-catalog insights", f"curating insights for {run.name}")
    state = curate.load_state()
    applied, cp = curate.apply_run_marks(run, state)
    curate.save_state(state)
    run_videos = {v.video_id: v for v in cp.videos}
    ui.ok(f"Applied {applied['watched']} watched, {applied['skipped']} skipped, "
          f"{applied.get('reverted', 0)} reverted from {run.name}")

    nmarks = len(state.get("watched", {})) + len(state.get("skipped", {}))
    if nmarks == 0:
        ui.info("Nothing marked yet (here or in any prior run). Tick `[x]`/`[-]` "
                "in watchlist.md, then re-run this. insights.md left as the prompt.")

    (run / "insights.md").write_text(generate_insights(state, run.name, run_videos))
    ui.ok(f"wrote {run.name}/insights.md "
          f"(global totals: {len(state.get('watched', {}))} watched, "
          f"{len(state.get('skipped', {}))} skipped)")
