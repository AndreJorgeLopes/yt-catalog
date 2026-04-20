"""Handler for `yt-catalog login` — Option C dedicated-browser cookie capture."""
from __future__ import annotations
import argparse

from .. import browser_login, ui, web_session


def handle_login(args: argparse.Namespace) -> None:
    headless = getattr(args, "headless", False)
    ui.header("yt-catalog login", "dedicated-browser YouTube session")
    if headless:
        ui.step("refreshing cookies from the saved profile (headless)")
    else:
        ui.step("opening a dedicated browser profile for a one-time login")
    try:
        if headless:
            # no interactive input — safe to show a spinner
            with ui.spinner("Refreshing session from the saved profile"):
                n = browser_login.capture_cookies(headless=True)
        else:
            # headed: capture_cookies blocks on input() + prints its own guidance
            n = browser_login.capture_cookies(headless=False)
    except web_session.SessionError as e:
        ui.err(str(e))
        return
    ui.ok(f"saved {n} cookies to {web_session.COOKIE_FILE}")
    ui.info("`yt-catalog run` will now use the web session (bell, history, "
            "--source web). Re-run this if it ever reads logged-out.")
