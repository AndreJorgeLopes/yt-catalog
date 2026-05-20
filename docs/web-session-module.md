# `web_session` + `bell_scraper` — headless authenticated YouTube access

Status: **WIRED into the CLI (2026-06-15).** Foundation built 2026-06-15.
Files: `yt_catalog/web_session.py`, `yt_catalog/bell_scraper.py`,
`yt_catalog/web_videos.py`.

Integration (this session):
- **Bell channels** — `channels_fetch.fetch_bell_channels` is now web-first
  (`bell_scraper.get_bell_on`) with automatic Chrome fallback on any failure.
  Weekly cadence + partial-result guard preserved.
- **Watch history** — `history.fetch_watched_ids` tries the web session first
  (`/feed/history`), now **PAGINATED**: first page from `ytInitialData`, then the
  lazy-load continuations via the InnerTube `browse` POST signed with
  `web_session.sapisidhash` (`SHA1("<ts> <SAPISID> <origin>")`). The SAPISIDHASH
  was the missing piece that made the POST look like a dead end — with it the
  full history is reachable headlessly. Capped at `max_pages`; a mid-walk
  re-challenge keeps the partial result. Falls back to the Chrome scrape only
  when the FIRST GET is unavailable.
- **Video source** — `--source web` (`web_videos.scrape_via_web`,
  `/feed/subscriptions`) with a web → api → chrome fallback chain (api before
  chrome: it's fast/quota-cheap; chrome is the slow last resort).
- **`auto` now prefers web** when it's set up (yt-dlp present + a cookie jar
  exists, i.e. after `setup`/`login`), then api, then chrome. Safe because web is
  ONE cheap GET/run and degrades automatically. Pure-API users (no cookie jar)
  still get `auto` = api.
- **Option C — `yt-catalog login` (device-rebind-proof cookies).** New command
  (`browser_login.py`): drives a DEDICATED Playwright browser profile
  (`~/.config/yt-catalog/browser-profile/`). First run is headed — you log in
  once; the profile then stays logged in and `login --headless` refreshes the
  rotating SIDTS from the long-lived root cookies (a week idle is fine; re-login
  only on a true root-cookie death). Captured cookies are written to
  `COOKIE_FILE` in Netscape format, read by everything else unchanged. Playwright
  is an OPTIONAL dep (`pip install 'yt-catalog[login]' && playwright install
  chromium`). We do NOT automate the Google login itself (Google blocks it).
- **`run` uses ONLY the captured token.** The three web call sites in the run
  path (`bell_scraper.get_bell_all`, `web_session.get_page` for history,
  `web_videos.scrape_via_web`) pass `reextract=False`, so a run never shells out
  to `yt-dlp --cookies-from-browser` (the rotating-session anti-pattern). If the
  token reads logged-out, the run falls back (web→api→chrome) and tells you to
  re-run `yt-catalog login`.
- **Bell-cache filter fix.** `channels_fetch.load_bell_ids()` filters the cache
  by bell state (`_NOTIFY_ON` = All-only). The cache file may hold the FULL
  subscription dump (All/Personalized/None) — without the filter, the run
  silently catalogued ALL ~996 subscriptions instead of the ~96 bell-on ones.
  Entries with no `bell` field (legacy All-only caches) are kept.
- **No-bell-list prompt.** When a fetch fails and no cache exists, the run asks
  (arrow-key `ui.select`, not y/N) whether to catalog ALL subscriptions
  (showing the channel count + expected video estimate) or cancel. Cancel aborts
  the run; non-interactive contexts proceed with a loud warning.
- **Setup/install** — `yt-dlp` is now a `pyproject` runtime dependency;
  `install.sh` prefers pipx/brew; `yt-catalog setup` checks yt-dlp + does a real
  cookie export to surface the macOS Keychain prompt early.

NOTE (verify-first gap): the `/feed/history` percent parser
(`percentDurationWatched`), the SAPISIDHASH continuation walk, and the
`/feed/subscriptions` video parse could NOT be confirmed against a live blob —
the cookie session was device-rebound / logged-out headless (the reliability
limit below), so every web read returned `SessionError`. All three are built on
long-stable `ytInitialData` shapes + the standard SAPISIDHASH algorithm and are
unit-tested against fixtures; on any live-shape mismatch they yield zero results
and self-heal to the Chrome/API fallback. The SAPISIDHASH POST is subject to the
SAME device-binding as the GET — if the GET re-challenges, the continuation will
too, and the walk just stops with whatever it had. Same
unverified-live caveat applies to `web_videos._byline` / `parse_subscriptions_feed`
(`/feed/subscriptions` shape) — fine because `--source web` is opt-in and falls
back to chrome/api on an empty parse.

Bell semantics: **"bell on" = All only** (`channels_fetch._NOTIFY_ON = {"all"}`,
`bell_scraper.get_bell_all`), confirmed with the user. Personalized is YouTube's
default for most subs (~843) and is NOT treated as bell-on — including it would
10x the catalog source and clobber the verified ~95-channel `bell_all_channels.json`.

## What it is

A headless replacement for the `claude --print --chrome` (Claude-in-Chrome MCP)
scrapes. It borrows the user's existing Chrome login by exporting cookies once
via `yt-dlp`, then makes plain authenticated HTTP GETs of logged-in pages and
parses the `ytInitialData` blob the page server-renders. **No browser is driven
at runtime.**

```python
from yt_catalog import bell_scraper
bell_scraper.get_bell_all()      # [{id,title,bell}] for bell == "all"
bell_scraper.get_bell_all_ids()  # ["UC..."]
bell_scraper.get_subscriptions() # every sub + bell state (all/personalized/none)
```

`web_session` is the reusable foundation (cookie mgmt + authed GET + ytInitialData
extraction). `bell_scraper` is the first consumer. The same foundation serves the
other use cases below.

## Why it exists (the bell problem, proven)

The notification-bell setting is NOT in the Data API. Verified on the live
account: `subscriptions.list` `contentDetails.activityType` returned `"all"` for
**995/995** subs — it's a legacy "all-activity vs uploads-only" flag, hardwired
to `all`, carrying zero bell signal. The bell lives only in the web page's
`ytInitialData`:

```
channelRenderer.subscribeButton.subscribeButtonRenderer
  .notificationPreferenceButton.subscriptionNotificationToggleButtonRenderer.currentStateId
# 2 = All, 3 = Personalized, 0 = None
```

The whole subscription list is server-rendered in ONE GET — no scrolling, no
continuation tokens. Headless run produced 96 bell=All / 843 Personalized / 57
None across 996 subs, matching a parallel Chrome-MCP scrape 100%.

## Other use cases (same module, same cookie session)

The Chrome integration is currently used for four things; the cookie/web-session
path can serve all the ones that need a login:

1. **Bell channels** (`/feed/channels`) — done here.
2. **Watch history + watch-progress %** (`/feed/history`) — PRIVATE, auth-only,
   no API exists. Powers the existing "filter watched" and "watched > X%" features
   (`history.py` / `HISTORY_PROMPT`, today driven by Chrome). Parse
   `yt-lockup-view-model` → `video_id`, `percent_watched`
   (`[class*="WatchedProgressBar"] > div` width %), `watched_on` date header.
   History lazy-loads, so this one DOES need continuation handling (unlike the
   bell page) — either parse `ytInitialData` for the first page + follow
   `continuationItemRenderer` via InnerTube `browse`, or accept first-page only.
3. **Video source under Data API quota** (`/feed/subscriptions`) — the
   authenticated subscriptions feed renders recent uploads in `ytInitialData`,
   quota-free. A richer alternative to the existing RSS path
   (`scrape_recent_via_rss`) and to the Chrome notification-dropdown scrape
   (`SCRAPER_PROMPT`). Good rate-limit fallback.
4. **Personalized / private data** generally — Watch Later, liked videos,
   playlists, members-only metadata. All login-gated, all reachable the same way.

Enrichment (`ENRICHER_PROMPT`) already runs on stateless InnerTube
(`enrich_videos_innertube`) and needs NO auth — leave it alone.

## Cookie lifespan & handling

- **Core auth cookies** (`SID`, `SAPISID`, `HSID`, `SSID`, `APISID`,
  `__Secure-1PSID/3PSID`, `__Secure-1PAPISID/3PAPISID`, `LOGIN_INFO`):
  long-lived / persistent (multi-year expiry). Not session cookies.
- **`__Secure-1PSIDTS` / `__Secure-3PSIDTS`**: short-lived, rotate ~daily,
  refreshed automatically in the browser.
- **`SOCS`**: EU/UK consent cookie. Without it, EU sessions bounce to
  `consent.youtube.com` and read as logged-out. `load_cookies` injects it from
  `.google.com` if the `.youtube.com` copy is missing.
- Cookies die on: explicit logout, password change, "sign out all devices", or a
  Google security event.

**DO NOT persist a static cookie file long-term. Re-extract on demand.**
`web_session.get_initial_data(...)` implements the robust pattern: try the cached
jar, and only re-export from the browser if the request comes back logged-out.
While the user stays signed into Chrome this needs no manual re-auth and survives
SIDTS rotation.

Extraction command (what `extract_cookies` runs):
```
yt-dlp --cookies-from-browser chrome --cookies <file> --skip-download <any-video-url>
```
Reads a COPY of Chrome's cookie DB, so a running browser is fine. macOS may show a
one-time Keychain prompt for the "Chrome Safe Storage" key.

## ⚠️ Known reliability limit — Google device-bound sessions

**Cookie reuse is best-effort, NOT guaranteed.** Chrome v127+/Google bind the
session to the device (rotating SIDTS + Device Bound Session Credentials / DBSC).
Exported cookies authenticate from the originating Chrome but can be
**re-challenged** when replayed from a plain HTTP client: response reads
logged-out or 302s to `accounts.google.com/v3/signin` — *while the live browser
stays logged in*.

Observed 2026-06-15: a fresh export worked for one batch (the 96-channel result),
then began bouncing to signin after ~20 rapid headless requests in minutes. The
browser session was never affected.

Consequences for the integrator:
- Treat `SessionError` as expected; **fall back to the Chrome-MCP scrape** rather
  than hard-failing the run. Keep both paths.
- Keep frequency LOW. This data changes slowly — cache for days, one GET per run,
  never per-item. Hammering is what trips the re-challenge.
- Re-extraction self-heals an *expired* jar, NOT a device-rebound one.
- If unreliable on a machine, worth trying: a Firefox profile (historically less
  bound), or a dedicated Chrome profile not driven concurrently. No guarantees.

## Things tried that did NOT work (don't repeat)

1. **Data API for the bell** — `activityType` is constant `"all"` (995/995). Dead.
2. **InnerTube POST** (`youtubei/v1/browse?browseId=FEchannels`) with cookies —
   returned `loggedOut: true` unless a correct `SAPISIDHASH` Authorization header
   is computed; fragile. The page-GET + `ytInitialData` parse needs no
   SAPISIDHASH and returns the complete list in one request. Use the GET.
3. **`http.cookiejar.MozillaCookieJar`** — silently drops the auth cookies:
   `yt-dlp` writes httpOnly cookies with a `#HttpOnly_` line prefix, which it
   treats as comments. Parse the Netscape file by hand (see `load_cookies`).
4. **Mixing cookie domains** — `SID`/`SAPISID` exist for `.youtube.com`,
   `.google.com`, `.google.es`, `.google.pt` with DIFFERENT values. A request to
   `www.youtube.com` must use the `.youtube.com` set (plus injected `SOCS`).
   Mixing logs you out.
5. **Google Takeout** — subscriptions export is id/title/url only, no bell field.
6. **base64 piping through tools** — irrelevant to prod, but note: some tool
   layers block base64 blobs; move data via files, not encoded stdout.

## Setup / install requirements (MUST add before shipping)

The tool will be installed by many users. The setup/install flow MUST ensure
`yt-dlp` is present (it's the cookie-extraction dependency; the project was
otherwise stdlib-only). Decide one:
- Add `yt-dlp` to `pyproject.toml` `[project] dependencies` (pip brings the
  `yt-dlp` console script onto PATH) — simplest, cross-platform. This breaks the
  current "zero runtime deps" stance; call it out.
- Or document/auto-install via `pipx install yt-dlp` / `brew install yt-dlp` in
  `install.sh` + a `yt-catalog setup` check.

Also verify at setup: a Chromium browser is present and the user is logged into
YouTube; surface the macOS Keychain-prompt expectation. Re-audit `install.sh` and
the `setup` command for anything else added since (e.g. the bell cache file path
`~/.config/yt-catalog/`).
```
