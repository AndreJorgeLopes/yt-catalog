"""Tests for the Option C cookie writer (no real browser launched)."""
import json
from pathlib import Path

from yt_catalog import browser_login as bl


def test_to_netscape_filters_and_formats():
    cookies = [
        {"name": "SID", "value": "v1", "domain": ".youtube.com", "path": "/",
         "secure": True, "expires": 1800000000},
        {"name": "SAPISID", "value": "v2", "domain": ".google.com", "path": "/",
         "secure": True, "expires": -1},                     # session -> 0
        {"name": "junk", "value": "x", "domain": ".example.com", "path": "/",
         "secure": False, "expires": 1},                     # dropped (not yt/google)
    ]
    text = bl._to_netscape(cookies)
    assert text.startswith("# Netscape HTTP Cookie File")
    assert "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1800000000", "SID", "v1"]) in text
    assert "SAPISID\tv2" in text
    assert "\t0\tSAPISID" in text          # negative expiry clamped to 0
    assert "example.com" not in text       # non-yt/google dropped


def test_write_cookies_roundtrips_through_load(tmp_path, monkeypatch):
    monkeypatch.setattr(bl.web_session, "COOKIE_FILE", tmp_path / "jar.txt")
    n = bl._write_cookies([
        {"name": "SAPISID", "value": "s", "domain": ".youtube.com", "path": "/",
         "secure": True, "expires": 1800000000},
        {"name": "SID", "value": "i", "domain": ".youtube.com", "path": "/",
         "secure": True, "expires": 1800000000},
    ])
    assert n == 2
    cookies = bl.web_session.load_cookies(tmp_path / "jar.txt")
    assert cookies["SAPISID"] == "s" and cookies["SID"] == "i"
    assert bl.web_session.has_auth_cookies(cookies)
    # locked down
    assert oct((tmp_path / "jar.txt").stat().st_mode)[-3:] == "600"
