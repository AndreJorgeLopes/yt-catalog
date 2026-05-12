"""Tests for run resume/checkpoint detection (_maybe_resume)."""
import argparse
import json
from datetime import date
from pathlib import Path

import yt_catalog.commands.run as r


def _mk_run(root: Path, date_str: str, phase: str, n: int = 3) -> Path:
    d = root / "vault" / "runs" / date_str
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(json.dumps({
        "scrape_date": date_str + "T00:00:00Z",
        "last_completed_phase": phase,
        "total_scraped": n,
        "shorts_filtered": 0,
        "videos": [
            {"video_id": f"v{i}", "title": "t", "channel": "c", "url": "u", "relative_time": ""}
            for i in range(n)
        ],
    }))
    return d


def _args(**kw) -> argparse.Namespace:
    base = {"from_checkpoint": None, "fresh": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_resume_auto_continues_unfinished_today(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    today = date.today().isoformat()
    _mk_run(tmp_path, today, "enrichment")
    a = _args()
    run_dir, exit_now = r._maybe_resume(a, today, str(tmp_path / "vault" / "runs" / today))
    assert exit_now is False
    assert a.from_checkpoint and a.from_checkpoint.endswith(f"{today}/data.json")


def test_resume_completed_today_noninteractive_views(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    today = date.today().isoformat()
    _mk_run(tmp_path, today, "complete")
    a = _args()
    _, exit_now = r._maybe_resume(a, today, str(tmp_path / "vault" / "runs" / today))
    assert exit_now is True            # non-interactive default = don't re-run -> view
    assert a.from_checkpoint is None


def test_resume_offers_past_unfinished(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    today = date.today().isoformat()
    _mk_run(tmp_path, "2026-05-01", "scraping")
    a = _args()
    run_dir, exit_now = r._maybe_resume(a, today, str(tmp_path / "vault" / "runs" / today))
    assert exit_now is False
    assert a.from_checkpoint and "2026-05-01" in a.from_checkpoint
    assert run_dir.endswith("2026-05-01")          # resumes into the old run's dir


def test_fresh_flag_ignores_checkpoints(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    today = date.today().isoformat()
    _mk_run(tmp_path, today, "enrichment")
    a = _args(fresh=True)
    _, exit_now = r._maybe_resume(a, today, str(tmp_path / "vault" / "runs" / today))
    assert a.from_checkpoint is None and exit_now is False


def test_no_prior_runs_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    today = date.today().isoformat()
    a = _args()
    run_dir, exit_now = r._maybe_resume(a, today, str(tmp_path / "vault" / "runs" / today))
    assert a.from_checkpoint is None and exit_now is False
