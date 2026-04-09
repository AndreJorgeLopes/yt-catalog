"""Pure-parse + fallback tests for the headless cookie-web-session consumers:
bell channels, watch history, and the subscriptions-feed video source. No network
(the autouse conftest fixture forces web_session.get_initial_data -> SessionError).
"""
import json
from pathlib import Path

import pytest

from yt_catalog import bell_scraper, channels_fetch, history, web_videos


# --------------------------------------------------------------------------- #
# bell_scraper.parse_subscriptions — currentStateId 2/3/0 -> all/personalized/none
# --------------------------------------------------------------------------- #
def _channel(cid, title, state):
    btn = {}
    if state is not None:
        btn = {"notificationPreferenceButton": {
            "subscriptionNotificationToggleButtonRenderer": {"currentStateId": state}}}
    return {"channelRenderer": {
        "channelId": cid,
        "title": {"simpleText": title},
        "subscribeButton": {"subscribeButtonRenderer": btn}}}


def _bell_blob():
    return {"contents": [
        _channel("UC_all", "All Chan", 2),
        _channel("UC_pers", "Personalized Chan", 3),
        _channel("UC_none", "None Chan", 0),
        _channel("UC_all", "Dup", 2),  # de-duped
    ]}


def test_parse_subscriptions_bell_states():
    rows = bell_scraper.parse_subscriptions(_bell_blob())
    by = {r["id"]: r["bell"] for r in rows}
    assert by == {"UC_all": "all", "UC_pers": "personalized", "UC_none": "none"}
    assert len(rows) == 3  # de-duped by id


def test_get_bell_on_filters(monkeypatch):
    monkeypatch.setattr(bell_scraper.web_session, "get_initial_data",
                        lambda *a, **k: _bell_blob())
    on = {r["id"] for r in bell_scraper.get_bell_on()}
    assert on == {"UC_all", "UC_pers"}            # none excluded
    assert bell_scraper.get_bell_all_ids() == ["UC_all"]


# --------------------------------------------------------------------------- #
# channels_fetch web-first mapping + fallback
# --------------------------------------------------------------------------- #
def test_fetch_bell_web_maps_and_filters(monkeypatch):
    monkeypatch.setattr(bell_scraper.web_session, "get_initial_data",
                        lambda *a, **k: _bell_blob())
    out = channels_fetch._fetch_bell_web()
    ids = {c["id"] for c in out}
    assert ids == {"UC_all"}                      # bell=All only (not Personalized)
    assert all(c["bell"] == "all" for c in out)


def test_fetch_bell_web_empty_returns_none(monkeypatch):
    # logged-in single-GET full render => empty means parse miss, not "no bells"
    monkeypatch.setattr(bell_scraper.web_session, "get_initial_data",
                        lambda *a, **k: {"contents": []})
    assert channels_fetch._fetch_bell_web() is None


def test_fetch_bell_channels_falls_back_to_chrome(monkeypatch):
    # web raises (conftest already does, but be explicit) -> chrome path used
    monkeypatch.setattr(channels_fetch, "_fetch_bell_web", lambda: None)
    monkeypatch.setattr(channels_fetch, "_fetch_bell_chrome",
                        lambda timeout=600: [{"id": "UCx", "title": "t", "bell": "All"}])
    out = channels_fetch.fetch_bell_channels()
    assert out == [{"id": "UCx", "title": "t", "bell": "All"}]


def test_fetch_bell_channels_prefers_web(monkeypatch):
    monkeypatch.setattr(channels_fetch, "_fetch_bell_web",
                        lambda: [{"id": "UCweb", "title": "w", "bell": "all"}])
    monkeypatch.setattr(channels_fetch, "_fetch_bell_chrome",
                        lambda timeout=600: pytest.fail("chrome should not run"))
    assert channels_fetch.fetch_bell_channels() == [{"id": "UCweb", "title": "w", "bell": "all"}]


# --------------------------------------------------------------------------- #
# history.parse_history_initial_data — videoRenderer + lockupViewModel
# --------------------------------------------------------------------------- #
def _resume(pct):
    return {"thumbnailOverlays": [
        {"thumbnailOverlayResumePlaybackRenderer": {"percentDurationWatched": pct}}]}


def _history_blob():
    return {"contents": {"items": [
        {"videoRenderer": dict({"videoId": "vid_full01_"}, **_resume(90))},
        {"videoRenderer": dict({"videoId": "vid_part002_"}, **_resume(20))},
        {"videoRenderer": {"videoId": "vid_zero003_"}},   # no resume bar -> 0
        {"lockupViewModel": dict({"contentId": "lockup11chr"}, **_resume(75))},
    ]}}


def test_parse_history_threshold():
    watched = history.parse_history_initial_data(_history_blob(), min_percent=50)
    assert watched == {"vid_full01_", "lockup11chr"}     # 90 and 75 pass; 20/0 drop


def test_parse_history_dedupe_keeps_max():
    blob = {"x": [
        {"videoRenderer": dict({"videoId": "dup00000001"}, **_resume(10))},
        {"videoRenderer": dict({"videoId": "dup00000001"}, **_resume(80))},
    ]}
    assert history.parse_history_initial_data(blob, min_percent=50) == {"dup00000001"}


def test_fetch_watched_ids_web_uses_blob(monkeypatch):
    import yt_catalog.web_session as ws
    # first page only (no continuation token -> no POST)
    monkeypatch.setattr(ws, "get_page", lambda *a, **k: (_history_blob(), "<html>", {"SAPISID": "s"}))
    assert history.fetch_watched_ids_web(min_percent=50) == {"vid_full01_", "lockup11chr"}


def test_fetch_watched_ids_web_none_on_sessionerror():
    # conftest forces SessionError -> None (caller falls back to chrome)
    assert history.fetch_watched_ids_web(min_percent=50) is None


# --------------------------------------------------------------------------- #
# web_videos.parse_subscriptions_feed
# --------------------------------------------------------------------------- #
def _vr(vid, title, ch, cid):
    return {"videoRenderer": {
        "videoId": vid,
        "title": {"runs": [{"text": title}]},
        "publishedTimeText": {"simpleText": "2 days ago"},
        "longBylineText": {"runs": [{
            "text": ch,
            "navigationEndpoint": {"browseEndpoint": {"browseId": cid}}}]}}}


def _feed_blob():
    return {"contents": [
        {"richItemRenderer": {"content": _vr("aaaaaaaaaaa", "First", "Chan A", "UCaaa")}},
        {"richItemRenderer": {"content": _vr("bbbbbbbbbbb", "Second", "Chan B", "UCbbb")}},
        {"richItemRenderer": {"content": _vr("aaaaaaaaaaa", "Dup", "Chan A", "UCaaa")}},
    ]}


def test_parse_subscriptions_feed():
    vids = web_videos.parse_subscriptions_feed(_feed_blob())
    assert [v.video_id for v in vids] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]   # de-duped, ordered
    v = vids[0]
    assert v.title == "First" and v.channel == "Chan A" and v.channel_id == "UCaaa"
    assert v.url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert v.relative_time == "2 days ago"


def test_parse_subscriptions_feed_max_videos():
    vids = web_videos.parse_subscriptions_feed(_feed_blob(), max_videos=1)
    assert len(vids) == 1


def test_scrape_via_web_raises_sessionerror():
    # conftest forces get_initial_data -> SessionError; scrape_via_web propagates
    from yt_catalog.web_session import SessionError
    with pytest.raises(SessionError):
        web_videos.scrape_via_web()


# --------------------------------------------------------------------------- #
# web_session InnerTube continuation (SAPISIDHASH + token walk)
# --------------------------------------------------------------------------- #
def test_sapisidhash_deterministic(monkeypatch):
    import hashlib
    import yt_catalog.web_session as ws
    monkeypatch.setattr(ws.time, "time", lambda: 1700000000)
    out = ws.sapisidhash({"SAPISID": "MYSAP"}, origin="https://www.youtube.com")
    expect = hashlib.sha1(b"1700000000 MYSAP https://www.youtube.com").hexdigest()
    assert out == f"SAPISIDHASH 1700000000_{expect}"


def test_sapisidhash_falls_back_to_3papisid(monkeypatch):
    import yt_catalog.web_session as ws
    monkeypatch.setattr(ws.time, "time", lambda: 1)
    assert ws.sapisidhash({"__Secure-3PAPISID": "X"}).startswith("SAPISIDHASH 1_")


def test_sapisidhash_no_cookie_raises():
    import yt_catalog.web_session as ws
    with pytest.raises(ws.SessionError):
        ws.sapisidhash({})


def test_find_continuation_token():
    import yt_catalog.web_session as ws
    blob = {"a": [{"continuationItemRenderer": {
        "continuationEndpoint": {"continuationCommand": {"token": "TOK123"}}}}]}
    assert ws.find_continuation_token(blob) == "TOK123"
    assert ws.find_continuation_token({"none": 1}) is None


def test_innertube_client_version():
    import yt_catalog.web_session as ws
    assert ws.innertube_client_version('x"INNERTUBE_CLIENT_VERSION":"2.20260101.01.00"y') == "2.20260101.01.00"
    assert ws.innertube_client_version("nope") == "2.20240101.00.00"


def test_fetch_watched_ids_web_paginates(monkeypatch):
    """First page + one signed continuation page are both harvested."""
    import yt_catalog.web_session as ws

    page1 = {"items": [
        {"videoRenderer": dict({"videoId": "p1vid000001"}, **_resume(90))},
    ], "x": {"continuationItemRenderer": {
        "continuationEndpoint": {"continuationCommand": {"token": "NEXT"}}}}}
    page2 = {"items": [
        {"videoRenderer": dict({"videoId": "p2vid000002"}, **_resume(80))},
    ]}  # no further token -> walk stops

    monkeypatch.setattr(ws, "get_page", lambda *a, **k: (page1, "<html>", {"SAPISID": "s"}))
    calls = {"n": 0}

    def _cont(token, cookies, cv, timeout=30):
        calls["n"] += 1
        assert token == "NEXT"
        return page2

    monkeypatch.setattr(ws, "innertube_continuation", _cont)
    out = history.fetch_watched_ids_web(min_percent=50)
    assert out == {"p1vid000001", "p2vid000002"}
    assert calls["n"] == 1   # one continuation POST, then token exhausted


def test_fetch_watched_ids_web_partial_on_continuation_error(monkeypatch):
    """A mid-walk re-challenge keeps the first-page result instead of failing."""
    import yt_catalog.web_session as ws
    page1 = {"items": [{"videoRenderer": dict({"videoId": "keep0000001"}, **_resume(95))}],
             "x": {"continuationItemRenderer": {
                 "continuationEndpoint": {"continuationCommand": {"token": "NEXT"}}}}}
    monkeypatch.setattr(ws, "get_page", lambda *a, **k: (page1, "<html>", {"SAPISID": "s"}))

    def _boom(*a, **k):
        raise ws.SessionError("device rebound mid-walk")

    monkeypatch.setattr(ws, "innertube_continuation", _boom)
    assert history.fetch_watched_ids_web(min_percent=50) == {"keep0000001"}
