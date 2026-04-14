"""Tests for the bell-channel cache loader + weekly fetch cadence (no chrome)."""
import json
from pathlib import Path

import yt_catalog.channels_fetch as cf


def test_load_bell_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(cf.BELL_FILE).write_text(json.dumps(
        [{"id": "UC1", "title": "a"}, {"id": "UC2"}, {"id": "x"}, {"title": "noid"}]))
    assert cf.load_bell_ids() == ["UC1", "UC2"]   # only valid UC ids


def test_load_bell_ids_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cf.load_bell_ids() == []


def test_load_bell_ids_filters_by_bell_state(tmp_path, monkeypatch):
    """A full-dump cache (All/Personalized/None) yields only the All ids — the
    bug that previously turned 'bell-on' into 'all 996 subscriptions'."""
    monkeypatch.chdir(tmp_path)
    Path(cf.BELL_FILE).write_text(json.dumps([
        {"id": "UCa", "title": "a", "bell": "All"},
        {"id": "UCb", "title": "b", "bell": "Personalized"},
        {"id": "UCc", "title": "c", "bell": "None"},
        {"id": "UCd", "title": "d", "bell": "all"},   # lowercase too
    ]))
    assert cf.load_bell_ids() == ["UCa", "UCd"]


def test_should_fetch_first_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cf.should_fetch_bell({}, first_run=True, force=False) is True


def test_should_fetch_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(cf.BELL_FILE).write_text("[]")
    assert cf.should_fetch_bell({"last_bell_fetch": "2026-06-15"},
                                first_run=False, force=True, today="2026-06-15") is True


def test_should_fetch_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cf.should_fetch_bell({"last_bell_fetch": "2026-06-15"},
                                first_run=False, force=False, today="2026-06-15") is True


def test_should_skip_within_week(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(cf.BELL_FILE).write_text("[]")
    assert cf.should_fetch_bell({"last_bell_fetch": "2026-06-15"},
                                first_run=False, force=False, today="2026-06-18") is False


def test_should_fetch_after_a_week(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(cf.BELL_FILE).write_text("[]")
    assert cf.should_fetch_bell({"last_bell_fetch": "2026-06-15"},
                                first_run=False, force=False, today="2026-06-23") is True


def _chans(n):
    return [{"id": f"UC{i:08d}", "title": f"c{i}", "bell": "All"} for i in range(n)]


def test_save_first_time_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saved, old_n, new_n = cf.save_bell_channels(_chans(10))
    assert (saved, old_n, new_n) == (True, 0, 10)
    assert len(cf.load_bell_ids()) == 10


def test_save_guard_rejects_partial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cf.save_bell_channels(_chans(100))
    saved, old_n, new_n = cf.save_bell_channels(_chans(40))  # < 50% of 100
    assert (saved, old_n, new_n) == (False, 100, 40)
    assert len(cf.load_bell_ids()) == 100               # old kept
    assert Path(cf.BELL_FILE + ".new").exists()          # partial parked
    assert len(json.loads(Path(cf.BELL_FILE + ".new").read_text())) == 40


def test_save_accepts_growth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cf.save_bell_channels(_chans(50))
    saved, old_n, new_n = cf.save_bell_channels(_chans(95))
    assert (saved, old_n, new_n) == (True, 50, 95)
    assert len(cf.load_bell_ids()) == 95


def test_save_guard_disabled_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cf.save_bell_channels(_chans(100))
    saved, _, new_n = cf.save_bell_channels(_chans(10), guard=False)
    assert (saved, new_n) == (True, 10)
    assert len(cf.load_bell_ids()) == 10
