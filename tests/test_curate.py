"""Tests for curation state (watched/skipped) + the refresh round-trip."""
import argparse

import yt_catalog.curate as curate
from yt_catalog.models import Video, save_checkpoint
from yt_catalog.commands.refresh import handle_refresh


def _vid(i, ch="C", cat="general", score=50):
    return Video(video_id=f"v{i}", title=f"T{i}", channel=ch,
                 url=f"https://youtube.com/watch?v=v{i}", relative_time="",
                 duration_seconds=600, category=cat, interest_score=score,
                 duration_group="long")


def test_mark_filters_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("yt_catalog.curate.get_data_dir", lambda: tmp_path)
    state = curate.load_state()
    curate.mark(state, {"video_id": "v0", "channel": "C", "category": "general"}, "watched")
    curate.mark(state, {"video_id": "v1", "channel": "C", "category": "general"}, "skipped")

    visible = curate.filter_videos([_vid(0), _vid(1), _vid(2)], state)
    assert {v.video_id for v in visible} == {"v2"}

    stats = curate.channel_skip_stats(state)
    assert stats[0]["channel"] == "C"
    assert stats[0]["skipped"] == 1 and stats[0]["watched"] == 1


def test_mark_moves_between_states(tmp_path, monkeypatch):
    monkeypatch.setattr("yt_catalog.curate.get_data_dir", lambda: tmp_path)
    state = curate.load_state()
    curate.mark(state, {"video_id": "v0"}, "skipped")
    curate.mark(state, {"video_id": "v0"}, "watched")  # re-mark
    assert "v0" in state["watched"] and "v0" not in state["skipped"]


def test_refresh_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_catalog.curate.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("yt_catalog.commands.refresh.get_data_dir", lambda: tmp_path)
    run = tmp_path / "vault" / "runs" / "2026-06-15"
    run.mkdir(parents=True)
    save_checkpoint([_vid(0), _vid(1), _vid(2)], str(run), phase="complete")
    run.joinpath("watchlist.md").write_text(
        "- [x] [T0](https://youtube.com/watch?v=v0)\n"
        "      ⭐50 · 10:00\n"
        "- [-] [T1](https://youtube.com/watch?v=v1)\n"
        "- [ ] [T2](https://youtube.com/watch?v=v2)\n"
    )
    handle_refresh(argparse.Namespace(run=str(run)))

    state = curate.load_state()
    assert "v0" in state["watched"]
    assert "v1" in state["skipped"]
    assert "v2" not in state["watched"] and "v2" not in state["skipped"]
    assert (run / "insights.md").exists()
    # v2 is the only visible video after refresh
    assert curate.filter_videos([_vid(0), _vid(1), _vid(2)], state) == \
        [v for v in [_vid(0), _vid(1), _vid(2)] if v.video_id == "v2"]


def test_apply_run_marks_reverts_unchecked(tmp_path, monkeypatch):
    """An explicit [ ] for a currently-marked video un-marks it (revert)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_catalog.curate.get_data_dir", lambda: tmp_path)
    run = tmp_path / "vault" / "runs" / "2026-06-16"
    run.mkdir(parents=True)
    from yt_catalog.models import save_checkpoint
    save_checkpoint([_vid(0), _vid(1)], str(run), phase="complete")

    state = curate.load_state()
    curate.mark(state, {"video_id": "v0", "channel": "C"}, "skipped")
    curate.mark(state, {"video_id": "v1", "channel": "C"}, "watched")
    assert "v0" in state["skipped"] and "v1" in state["watched"]

    # insights.md re-affirms v1 watched, but v0 is unchecked -> revert
    (run / "insights.md").write_text(
        "- [x] [T1](https://youtube.com/watch?v=v1) — C\n"
        "- [ ] [T0](https://youtube.com/watch?v=v0) — C\n"
    )
    applied, _ = curate.apply_run_marks(run, state)
    assert applied["reverted"] == 1
    assert "v0" not in state["skipped"] and "v0" not in state["watched"]  # reverted
    assert "v1" in state["watched"]                                       # kept


def test_explicit_mark_wins_over_blank(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_catalog.curate.get_data_dir", lambda: tmp_path)
    run = tmp_path / "vault" / "runs" / "2026-06-16"
    run.mkdir(parents=True)
    from yt_catalog.models import save_checkpoint
    save_checkpoint([_vid(0)], str(run), phase="complete")
    # same vid appears blank in one file and skipped in another -> skipped wins
    (run / "watchlist.md").write_text("- [ ] [T0](https://youtube.com/watch?v=v0)\n")
    (run / "insights.md").write_text("- [-] [T0](https://youtube.com/watch?v=v0) — C\n")
    state = curate.load_state()
    applied, _ = curate.apply_run_marks(run, state)
    assert "v0" in state["skipped"]
    assert applied["reverted"] == 0
