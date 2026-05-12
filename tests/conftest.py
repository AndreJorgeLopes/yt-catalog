"""Shared pytest fixtures.

Test isolation guard: a developer machine that has run `yt-catalog setup`
keeps real OAuth tokens in ~/.config/yt-catalog. Without isolation,
`_get_subscribed_channel_ids()` would call `get_subscriptions_oauth()`, which
hits the live YouTube Data API — breaking the channels.json-fallback tests and
hanging `scrape_via_api` while it fetches every real subscription. We stub the
OAuth subscription lookup to return nothing by default so tests always exercise
the deterministic channels.json path. Tests that want the OAuth path can
re-patch `yt_catalog.api_scraper.get_subscriptions_oauth` themselves.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_oauth_subscriptions(monkeypatch):
    # _get_subscribed_channel_ids reads subscriptions via _fetch_subscriptions_full;
    # return "no API" so tests deterministically use channels.json instead of the
    # network / a developer's real OAuth tokens.
    monkeypatch.setattr(
        "yt_catalog.api_scraper._fetch_subscriptions_full",
        lambda: ([], False),
        raising=True,
    )
    monkeypatch.setattr(
        "yt_catalog.api_scraper.get_subscriptions_oauth",
        lambda: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _no_real_web_session(monkeypatch):
    """Disable the cookie web session in tests.

    The web-first paths (bell channels, watch history, --source web) call
    web_session.get_initial_data, which would shell out to yt-dlp and make a real
    authenticated network request. Force it to SessionError so tests exercise the
    deterministic fallback (chrome/api) without touching the network or the
    developer's real cookies. Tests that want the web path re-patch it themselves.
    """
    import yt_catalog.web_session as ws

    def _boom(*a, **k):
        raise ws.SessionError("web session disabled in tests")

    monkeypatch.setattr(ws, "get_initial_data", _boom, raising=True)
