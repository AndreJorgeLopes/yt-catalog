"""Option C — own-browser login (Playwright, persistent profile).

This is the robust, device-rebind-proof cookie source. Unlike the yt-dlp
``--cookies-from-browser`` grab (which copies your *live, rotating* Chrome
session and goes stale in minutes), this drives a DEDICATED browser profile that
nothing else touches:

  * First run (headed): you log into YouTube once in the window it opens.
  * Thereafter the profile stays logged in. Launching it again — even headless —
    lets the browser engine refresh the rotating ``__Secure-*SIDTS`` from the
    long-lived root cookies, exactly like a normal browser resuming after days
    idle. So a week of not running the tool is fine; you only re-login if a root
    cookie truly dies (logout / password change / sign-out-all-devices).

We do NOT automate the Google *login* itself (Google blocks automated sign-in —
that's the whole reason cookie export exists). We automate everything after it.

The captured cookies are written to ``web_session.COOKIE_FILE`` in Netscape
format, so the rest of the tool (bell scraper, history, ``--source web``) reads
them through the exact same path as before.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import web_session

# Dedicated, isolated browser profile — never your day-to-day Chrome.
PROFILE_DIR = web_session.CONFIG_DIR / "browser-profile"
_KEEP = ("youtube.com", "google.com")


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def _to_netscape(cookies: list[dict]) -> str:
    """Serialize Playwright cookies to a Netscape jar (youtube/google only)."""
    out = ["# Netscape HTTP Cookie File\n"]
    for c in cookies:
        domain = c.get("domain", "")
        if not any(domain.lstrip(".").endswith(d) for d in _KEEP):
            continue
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        try:
            expiry = int(c.get("expires") or 0)
        except (TypeError, ValueError):
            expiry = 0
        if expiry < 0:
            expiry = 0
        out.append("\t".join([domain, flag, path, secure, str(expiry),
                              c.get("name", ""), c.get("value", "")]) + "\n")
    return "".join(out)


def _write_cookies(cookies: list[dict]) -> int:
    """Write captured cookies to COOKIE_FILE (chmod 600). Returns lines written."""
    web_session.COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = _to_netscape(cookies)
    web_session.COOKIE_FILE.write_text(text)
    try:
        web_session.COOKIE_FILE.chmod(0o600)
    except OSError:
        pass
    return text.count("\n") - 1  # minus the header line


def capture_cookies(headless: bool = False, timeout_s: int = 300) -> int:
    """Launch the dedicated profile, ensure logged in, write cookies.

    headed  : open a window; you log in (if needed), then press Enter.
    headless: silent refresh using the already-logged-in profile.

    Returns the number of cookies written. Raises ``web_session.SessionError``
    on failure (Playwright missing, not logged in, etc.).
    """
    if not _playwright_available():
        raise web_session.SessionError(
            "Playwright not installed. Install it:\n"
            "    pip install playwright\n"
            "    playwright install chromium"
        )
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Prefer the installed Chrome channel (no extra download); fall back to
        # the Playwright-managed Chromium.
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=headless, channel="chrome")
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.youtube.com", timeout=timeout_s * 1000)

            def _logged_in() -> bool:
                try:
                    return '"LOGGED_IN":true' in page.content()
                except Exception:
                    return False

            if not headless:
                print("\n  A browser window opened. Log into YouTube there if you")
                print("  aren't already, then come back here.")
                try:
                    input("  Press Enter once you see your YouTube home feed... ")
                except EOFError:
                    pass
                # give the SPA a moment, then re-read
                page.goto("https://www.youtube.com", timeout=timeout_s * 1000)

            if not _logged_in():
                raise web_session.SessionError(
                    "the dedicated profile isn't logged into YouTube. Re-run "
                    "`yt-catalog login` (without --headless) and sign in."
                )

            cookies = ctx.cookies()
        finally:
            ctx.close()

    n = _write_cookies(cookies)
    if n <= 0:
        raise web_session.SessionError("no youtube/google cookies captured")
    return n
