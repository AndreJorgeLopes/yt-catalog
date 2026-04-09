"""Authenticated YouTube web session — headless, cookie-based access to the
logged-in pages (subscriptions/bell, watch history, personal feeds) WITHOUT a
live browser or the Claude-in-Chrome integration.

Why this exists
---------------
A handful of things the catalog needs live ONLY behind YouTube's authenticated
web session and are not exposed by the Data API:

* the notification **bell** setting per subscription (All / Personalized / None)
* personal **watch history** + per-video **watch-progress %**
* personalized feeds (subscriptions feed, Watch Later, liked, members-only)

The old approach drove a real browser through ``claude --print --chrome`` (the
Claude-in-Chrome MCP). This module replaces that: it borrows the user's existing
Chrome login by exporting cookies once via ``yt-dlp``, then makes plain
authenticated HTTP GETs and parses the ``ytInitialData`` blob the page
server-renders. No browser is driven at runtime.

Design notes (hard-won — see the module docstrings and the handoff doc):

* **Do not persist cookies long-term / re-extract on demand.** The core Google
  auth cookies are multi-year, but ``__Secure-*SIDTS`` sub-tokens rotate. The
  robust pattern is ``ensure``/``get_initial_data`` below: use the cached jar,
  and only re-export from the browser if a request comes back logged-out. While
  the user stays signed into Chrome this never needs a manual re-auth.
* **The Netscape jar hides the auth cookies.** ``yt-dlp`` writes httpOnly
  cookies with a ``#HttpOnly_`` line prefix; ``http.cookiejar.MozillaCookieJar``
  treats those as comments and silently drops SID / SAPISID / __Secure-*. We
  parse by hand.
* **Cookie names collide across domains.** ``SID`` (and friends) exist for
  ``.youtube.com``, ``.google.com``, ``.google.es`` … with DIFFERENT values.
  Mixing them logs you out — keep ONE domain.
* **The InnerTube POST path was a dead end for authed calls.** Posting to
  ``youtubei/v1/browse`` with cookies returned ``loggedOut: true`` unless a
  correct ``SAPISIDHASH`` Authorization header is computed; getting that right
  was fragile. The page-GET + ytInitialData parse needs no SAPISIDHASH and
  returns the *complete* list in one request (no continuation tokens), so we use
  that instead.
* **The active channel follows the browser.** The GET returns whatever channel
  is active in Chrome (incl. a brand/delegated channel) — the cookies carry that
  context, so no ``X-Goog-PageId`` header is required.

KNOWN RELIABILITY LIMIT — Google device-bound sessions
------------------------------------------------------
Cookie reuse is **best-effort, not guaranteed.** Modern Chrome (v127+) + Google
bind the signed-in session to the device (rotating ``__Secure-*SIDTS`` and, on
supported setups, Device Bound Session Credentials / DBSC). Exported cookies
authenticate from the originating Chrome but can be **re-challenged** when
replayed from a plain HTTP client: the response either reads logged-out or
302-redirects to ``accounts.google.com/v3/signin`` — *while the live browser
stays logged in*. Empirically (2026-06-15) a fresh export worked for one batch,
then began bouncing to signin after ~20 rapid headless requests in a few minutes;
the browser session was never affected.

Practical implications for callers:
* Treat ``SessionError`` as expected and **fall back to the Chrome-MCP scrape**
  (``channels_fetch.py`` etc.) rather than hard-failing the run.
* Keep request frequency LOW (this data changes slowly — cache for days; one GET
  per run, not per item). Hammering is what trips the re-challenge.
* Re-extraction self-heals an *expired* jar but NOT a device-rebound one.
* If it proves unreliable on a given machine, options to investigate: a Firefox
  profile (historically less aggressively bound), or a dedicated Chrome profile
  that isn't driven concurrently. None are guaranteed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "yt-catalog"
COOKIE_FILE = CONFIG_DIR / "yt_cookies.txt"

_BASE = "https://www.youtube.com"
_INNERTUBE_BROWSE = "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false"
_CLIENT_VER_RE = re.compile(r'"INNERTUBE_CLIENT_VERSION":"([\d.]+)"')
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# Any YouTube URL makes yt-dlp dump the cookie jar; a single video is fastest.
_PRIME_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

_YTID_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>")
_YTID_RE_ALT = re.compile(r'ytInitialData"\]\s*=\s*(\{.*?\});')


class SessionError(RuntimeError):
    """Raised when the session is not usable (logged out, no cookies, etc.)."""


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def extract_cookies(
    browser: str = "chrome",
    cookie_file: Path = COOKIE_FILE,
    timeout: int = 120,
) -> bool:
    """Export ``browser``'s YouTube cookies into a Netscape jar via ``yt-dlp``.

    Returns ``True`` on success. Requires ``yt-dlp`` on PATH and the user signed
    into YouTube in ``browser``. ``yt-dlp`` reads a COPY of the cookie DB, so a
    running browser is fine; macOS may surface a one-time Keychain prompt to
    decrypt Chrome's "Safe Storage" key.
    """
    if shutil.which("yt-dlp") is None:
        raise SessionError("yt-dlp not found on PATH — install it (see setup).")
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "yt-dlp",
                "--cookies-from-browser", browser,
                "--cookies", str(cookie_file),
                "--skip-download",
                "--no-warnings",
                _PRIME_URL,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    if not (cookie_file.exists() and cookie_file.stat().st_size > 0):
        return False
    _sanitize_cookie_file(cookie_file)
    return cookie_file.stat().st_size > 0


# Only these domains are needed; everything else (banking, work, etc.) is dropped.
_KEEP_DOMAINS = ("youtube.com", "google.com")


def _sanitize_cookie_file(cookie_file: Path) -> None:
    """Trim the exported jar to YouTube/Google cookies only and lock it down.

    SECURITY: ``yt-dlp --cookies`` dumps the ENTIRE browser cookie store
    (payment, banking, work SSO — everything), not just YouTube. We immediately
    rewrite the file keeping only the domains we use, and chmod it to 0600 so the
    remaining session cookies aren't world/group readable.
    """
    kept = []
    for line in cookie_file.read_text().splitlines(keepends=True):
        probe = line[len("#HttpOnly_"):] if line.startswith("#HttpOnly_") else line
        if probe.startswith("#") or not probe.strip():
            kept.append(line)  # keep the Netscape header/comments
            continue
        domain = probe.split("\t", 1)[0].lstrip(".")
        if any(domain.endswith(d) for d in _KEEP_DOMAINS):
            kept.append(line)
    cookie_file.write_text("".join(kept))
    try:
        cookie_file.chmod(0o600)
    except OSError:
        pass


def load_cookies(
    cookie_file: Path = COOKIE_FILE,
    domain_suffix: str = "youtube.com",
) -> dict[str, str]:
    """Parse a Netscape cookie jar into ``{name: value}`` for one domain.

    Handles the ``#HttpOnly_`` prefix (auth cookies) and filters to a single
    domain — see the module docstring for why both matter.
    """
    out: dict[str, str] = {}
    socs_fallback: str | None = None
    if not cookie_file.exists():
        return out
    for line in cookie_file.read_text().splitlines():
        raw = line
        if raw.startswith("#HttpOnly_"):
            raw = raw[len("#HttpOnly_"):]
        elif raw.startswith("#") or not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) != 7:
            continue
        domain, name, value = parts[0], parts[5], parts[6]
        if domain.lstrip(".").endswith(domain_suffix):
            out[name] = value
        elif name == "SOCS" and domain.lstrip(".").endswith("google.com"):
            # EU consent cookie. After consent it's set on .youtube.com too, but a
            # degraded export can miss it there while .google.com still has it.
            # Without SOCS, EU/UK sessions get bounced to consent.youtube.com and
            # read as logged-out. YouTube honors the value regardless of source
            # domain, so carry it over.
            socs_fallback = value
    if "SOCS" not in out and socs_fallback:
        out["SOCS"] = socs_fallback
    return out


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def has_auth_cookies(cookies: dict[str, str]) -> bool:
    """Cheap, offline check that the jar at least *looks* logged in."""
    return "SAPISID" in cookies and ("SID" in cookies or "__Secure-3PSID" in cookies)


# --------------------------------------------------------------------------- #
# Authenticated fetch + ytInitialData
# --------------------------------------------------------------------------- #
def fetch_page(path_or_url: str, cookies: dict[str, str], timeout: int = 30) -> str:
    """Authenticated GET of a YouTube page; returns HTML.

    Raises ``SessionError`` if the response comes back logged-out (stale jar).
    """
    url = path_or_url if path_or_url.startswith("http") else _BASE + path_or_url
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie_header(cookies))
    req.add_header("User-Agent", _UA)
    req.add_header("Accept-Language", "en-US,en;q=0.9")
    html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf8", "ignore")
    if '"LOGGED_IN":true' not in html:
        raise SessionError("not logged in (cookies stale or missing)")
    return html


def extract_initial_data(html: str) -> dict:
    """Pull the ``ytInitialData`` JSON the page server-renders."""
    m = _YTID_RE.search(html) or _YTID_RE_ALT.search(html)
    if not m:
        raise SessionError("ytInitialData not found in page")
    return json.loads(m.group(1))


def _live_fetch(
    path: str,
    browser: str,
    cookie_file: Path,
    reextract: bool,
    timeout: int,
) -> tuple[str, dict[str, str]]:
    """Authenticated GET with self-heal. Returns ``(html, cookies)``.

    Tries the cached jar; on a logged-out response re-exports from ``browser``
    once and retries. ``reextract=False`` fails fast (tests / no browser).
    """
    cookies = load_cookies(cookie_file)
    if cookies:
        try:
            return fetch_page(path, cookies, timeout=timeout), cookies
        except SessionError:
            pass  # fall through to re-extract
    if not reextract:
        raise SessionError("no valid cached cookies (reextract disabled)")
    if not extract_cookies(browser, cookie_file):
        raise SessionError(
            "cookie extraction failed — is the browser signed into YouTube and "
            "yt-dlp installed?"
        )
    cookies = load_cookies(cookie_file)
    return fetch_page(path, cookies, timeout=timeout), cookies


def get_initial_data(
    path: str,
    browser: str = "chrome",
    cookie_file: Path = COOKIE_FILE,
    reextract: bool = True,
    timeout: int = 30,
) -> dict:
    """Authenticated GET of ``path`` → parsed ``ytInitialData``.

    The robust entry point most callers should use. Tries the cached cookie jar
    first; if it is missing or the response is logged-out, re-exports cookies
    from ``browser`` exactly once and retries. Set ``reextract=False`` to fail
    fast instead (e.g. in tests, or when the browser is unavailable).
    """
    html, _ = _live_fetch(path, browser, cookie_file, reextract, timeout)
    return extract_initial_data(html)


def get_page(
    path: str,
    browser: str = "chrome",
    cookie_file: Path = COOKIE_FILE,
    reextract: bool = True,
    timeout: int = 30,
) -> tuple[dict, str, dict[str, str]]:
    """Like ``get_initial_data`` but also returns ``(html, cookies)``.

    Needed by callers that then paginate via the InnerTube ``browse``
    continuation (they need the client version from the HTML and the cookies to
    sign the POST).
    """
    html, cookies = _live_fetch(path, browser, cookie_file, reextract, timeout)
    return extract_initial_data(html), html, cookies


# --------------------------------------------------------------------------- #
# InnerTube continuation (lazy-loaded feeds: history, etc.)
# --------------------------------------------------------------------------- #
def innertube_client_version(html: str) -> str:
    """The WEB client version the page advertises (for the InnerTube context)."""
    m = _CLIENT_VER_RE.search(html or "")
    return m.group(1) if m else "2.20240101.00.00"


def sapisidhash(cookies: dict[str, str], origin: str = _BASE) -> str:
    """Compute the ``SAPISIDHASH`` Authorization value YouTube's web client uses.

    ``SHA1("<unix-ts> <SAPISID> <origin>")`` → ``"SAPISIDHASH <ts>_<hexdigest>"``.
    This is what lets a plain cookie client call the authed InnerTube endpoints
    (the missing piece that made the POST path look like a dead end). Falls back
    to ``__Secure-3PAPISID`` when ``SAPISID`` is absent.
    """
    sap = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
    if not sap:
        raise SessionError("no SAPISID cookie — cannot sign InnerTube request")
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sap} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def find_continuation_token(node) -> str | None:
    """First ``continuationItemRenderer`` token found in a blob (None if none)."""
    if isinstance(node, dict):
        cir = node.get("continuationItemRenderer")
        if isinstance(cir, dict):
            tok = (
                cir.get("continuationEndpoint", {})
                .get("continuationCommand", {})
                .get("token")
            )
            if tok:
                return tok
        for v in node.values():
            t = find_continuation_token(v)
            if t:
                return t
    elif isinstance(node, list):
        for x in node:
            t = find_continuation_token(x)
            if t:
                return t
    return None


def innertube_continuation(
    token: str,
    cookies: dict[str, str],
    client_version: str,
    timeout: int = 30,
) -> dict:
    """POST one continuation page to the authed InnerTube ``browse`` endpoint.

    Raises ``SessionError`` if the response is an error / logged-out (the
    device-bound re-challenge hits this path too — caller stops and keeps the
    partial result).
    """
    body = json.dumps({
        "context": {"client": {"clientName": "WEB", "clientVersion": client_version}},
        "continuation": token,
    }).encode()
    req = urllib.request.Request(_INNERTUBE_BROWSE, data=body, method="POST")
    req.add_header("Cookie", cookie_header(cookies))
    req.add_header("User-Agent", _UA)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", sapisidhash(cookies))
    req.add_header("X-Origin", _BASE)
    req.add_header("Origin", _BASE)
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf8", "ignore")
    data = json.loads(raw)
    if "error" in data or data.get("responseContext", {}).get("mainAppWebResponseContext", {}).get("loggedOut"):
        raise SessionError("InnerTube continuation came back logged-out")
    return data


def ensure(browser: str = "chrome", cookie_file: Path = COOKIE_FILE) -> dict[str, str]:
    """Return a cookie jar, re-exporting from the browser if none is cached.

    Lightweight: does NOT make a network call (offline check only). Use
    ``get_initial_data`` when you need a guaranteed-live session.
    """
    cookies = load_cookies(cookie_file)
    if has_auth_cookies(cookies):
        return cookies
    if not extract_cookies(browser, cookie_file):
        raise SessionError("cookie extraction failed (browser signed in? yt-dlp installed?)")
    return load_cookies(cookie_file)
