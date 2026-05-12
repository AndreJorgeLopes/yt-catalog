"""Handler for `yt-catalog run` — the main scrape/categorize/vault pipeline."""

from __future__ import annotations
import argparse
import json
import os
from datetime import date
from pathlib import Path

from .. import ui
from ..config import PHASE_ORDER
from ..models import Video, save_checkpoint, load_checkpoint, video_to_dict
from ..scraper import scrape_notifications
from ..enricher import enrich_videos_innertube, download_thumbnails
from ..categorizer import categorize_and_rank
from ..vault_generator import generate_vault
from ..api_scraper import scrape_via_api, scrape_recent_via_rss
from ..run_state import (
    is_first_run, get_last_video_date, get_last_run_video_ids,
    get_estimated_new_videos, get_daily_median, update_after_run,
)
from ..history import fetch_watched_ids


def _confirm_chrome_watch_filter() -> bool:
    """Confirm running the (slower) Chrome watch-history pass after an API scrape.

    Watch history is not available through the YouTube Data API, so
    --filter-watched always reads it via the Chrome integration. When the main
    scrape ran via the API (fast), switching to Chrome now adds time — let the
    user opt out. Non-interactive contexts honor the flag as given (returns True).
    """
    import sys
    if not sys.stdin.isatty():
        return True
    ui.info("Watch-history filtering needs Chrome — the Data API can't read it.")
    ui.detail("The scrape ran via the API; this Chrome pass adds ~1-2 minutes.")
    return ui.confirm("Run the Chrome watch-history filter now?", default=False)


def _first_run_prompt(args: argparse.Namespace) -> tuple[str, int | None, int | None]:
    """Interactive prompt for first-run bootstrap strategy.

    Returns (source, max_days, max_videos).
    Only prompts if the user didn't already specify --source, --max-days, or --max-videos.
    """
    import sys
    # Skip prompt if user passed explicit flags or if not interactive (tests, CI)
    if args.max_days is not None or args.max_videos is not None:
        return args.source, args.max_days, args.max_videos
    if not sys.stdin.isatty():
        return args.source, args.max_days, args.max_videos

    ui.header("Welcome to yt-catalog", "first run — choose how to bootstrap")
    choice_idx = ui.select(
        "How would you like to fetch your YouTube notifications?",
        [
            "YouTube API — look back N days (quickest to get started)",
            "YouTube API — fetch by notification count (your bell badge number)",
            "Chrome integration — read the bell dropdown (most accurate, slowest)",
        ],
        default=0,
    )
    choice = str(choice_idx + 1)

    if choice == "1":
        while True:
            days_str = input("How many days back? (default: 30): ").strip() or "30"
            try:
                days = int(days_str)
                if days > 0:
                    break
            except ValueError:
                pass
            print("  Please enter a positive number.")
        return "api", days, None

    elif choice == "2":
        print()
        print("  Go to youtube.com and check the number on your")
        print("  notification bell icon (e.g., '246').")
        print()
        while True:
            count_str = input("Number of notifications to fetch: ").strip()
            try:
                count = int(count_str)
                if count > 0:
                    break
            except ValueError:
                pass
            print("  Please enter a positive number.")
        return "api", None, count

    else:  # choice == "3"
        print()
        print("  Make sure Chrome is open with the claude-in-chrome")
        print("  extension active and you're logged into YouTube.")
        print()
        input("  Press Enter when ready...")
        return "chrome", None, None


def _save_channels_json(channels_map: dict[str, str]) -> None:
    """Save channel name->ID mapping to channels.json for future API runs."""
    channels_file = Path.cwd() / "channels.json"
    existing: dict = {}
    if channels_file.exists():
        try:
            existing = json.loads(channels_file.read_text())
            if isinstance(existing, list):
                existing = {}
        except Exception:
            existing = {}
    existing.update(channels_map)
    channels_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"  Saved {len(existing)} channels to channels.json")


def _api_available() -> bool:
    """True if the YouTube Data API path is usable (OAuth, or key+channels.json)."""
    try:
        from ..oauth import is_authenticated, load_config
        if is_authenticated():
            return True
        has_key = bool(os.environ.get("YOUTUBE_API_KEY") or load_config().get("api_key"))
        channels_file = Path.cwd() / "channels.json"
        has_channels = channels_file.exists() and channels_file.stat().st_size > 2
        return has_key and has_channels
    except Exception:
        return False


def _resolve_source() -> str:
    """Pick a scrape source when --source=auto.

    Order: web -> api -> chrome.
      - 'web' when the headless cookie session is set up (yt-dlp present AND a
        cookie jar exists, i.e. the user ran setup). It's ONE cheap GET per run
        and falls back automatically (web -> api -> chrome) at runtime, so
        preferring it is safe even though it's best-effort.
      - 'api' when OAuth tokens, or a YOUTUBE_API_KEY + channels.json, exist.
      - 'chrome' otherwise.
    """
    import shutil
    try:
        from .. import web_session
        if shutil.which("yt-dlp") and web_session.COOKIE_FILE.exists():
            return "web"
    except Exception:
        pass
    if _api_available():
        return "api"
    return "chrome"


def _choose_notification_source(args: argparse.Namespace, *, estimate: int) -> tuple[str, int | None]:
    """Decide how to gather notifications for the no-API-quota path.

    Returns (strategy, count):
      - ('rss', N)   -> fetch the N most-recent uploads across subscriptions via
                        free RSS feeds (no browser, no Data API quota).
      - ('bell', N)  -> read the bell dropdown via Chrome (N caps the entries).

    The /feed/notifications page renders blank, so we never open it directly;
    option 3 clicks the bell instead.
    """
    import sys
    # Explicit flags skip the prompt.
    if getattr(args, "bell", False):
        return ("bell", args.max_videos)
    if args.max_videos is not None:
        return ("rss", args.max_videos)
    if not sys.stdin.isatty():
        return ("rss", estimate)  # non-interactive: use the history-based estimate

    idx = ui.select(
        "How should I gather your latest videos?",
        [
            f"Use the estimate from my history (~{estimate} videos)",
            "I'll type the number from my notification bell badge",
            "Read the bell dropdown directly (Chrome; slower, can be flaky)",
        ],
        default=0,
    )
    if idx == 0:
        return ("rss", estimate)
    if idx == 2:
        return ("bell", args.max_videos)
    # idx == 1: type a count
    while True:
        raw = input("  How many recent videos? ").strip()
        try:
            n = int(raw)
            if n > 0:
                return ("rss", n)
        except ValueError:
            pass
        print("  Please enter a positive number.")


def _enter_data_dir(args: argparse.Namespace) -> Path:
    """Resolve the data directory, persist it when given explicitly, and chdir.

    After this, every relative path (vault/, runs/, channels.json,
    run_state.json) resolves under the chosen directory, so the CLI works from
    any folder — not only one that already contains a vault/.
    """
    from ..utils import get_data_dir, load_dotenv
    explicit = getattr(args, "data_dir", None)
    if explicit:
        data_dir = Path(explicit).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            from ..oauth import update_config
            update_config(data_dir=str(data_dir))  # remember for future runs
        except Exception:
            pass
    else:
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(data_dir)
    # Pick up a .env living next to the data (won't override real env vars).
    load_dotenv()
    return data_dir


_ABORT = object()  # sentinel: user declined to continue without a bell list


def _count_all_subscriptions() -> int:
    """Best-effort count of all subscriptions (channels.json), 0 if unknown."""
    cf = Path("channels.json")
    if not cf.exists():
        return 0
    try:
        data = json.loads(cf.read_text())
    except Exception:
        return 0
    if isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    return 0


def _resolve_channel_source(args: argparse.Namespace, first_run: bool,
                            run_date: str, estimate: int):
    """Channel IDs to scrape uploads from. Precedence:
      1. --channels FILE (explicit).
      2. bell-on channels (web cookie session, chrome fallback), refreshed on
         first run, on --fetch-channels/--fresh, or weekly; cached in
         bell_all_channels.json.
      3. cached bell list, if a fetch failed but a cache exists.
      4. no bell list -> ASK the user (arrow-key) to continue with ALL
         subscriptions, or cancel. Returns ``_ABORT`` if they cancel.
    """
    ui.section("Preparing — channel source")
    from ..api_scraper import load_channel_ids_from_file
    if getattr(args, "channels", None):
        ids = load_channel_ids_from_file(args.channels)
        ui.ok(f"{len(ids)} channels from {args.channels}")
        return ids

    from .. import channels_fetch
    from ..curate import load_state, save_state
    state = load_state()
    force = bool(getattr(args, "fetch_channels", False) or getattr(args, "fresh", False))
    if channels_fetch.should_fetch_bell(state, first_run=first_run, force=force):
        with ui.loading_bar("Fetching your notification (bell) channels"):
            ch = channels_fetch.fetch_bell_channels()
        if ch:
            saved, old_n, new_n = channels_fetch.save_bell_channels(ch)
            if saved:
                state["last_bell_fetch"] = run_date
                save_state(state)
                ui.ok(f"fetched {new_n} bell-on channels")
            else:
                ui.warn(f"new scrape ({new_n}) < half the cached list ({old_n}); "
                        f"likely partial. Kept old list; wrote {channels_fetch.BELL_FILE}.new")
        else:
            ui.warn("bell fetch failed; using the cached bell list if present")

    ids = channels_fetch.load_bell_ids()
    if ids:
        ui.ok(f"{len(ids)} bell-on channels")
        return ids

    # No bell list at all — let the user decide, don't silently scrape everything.
    import sys
    total = _count_all_subscriptions()
    exp = str(estimate) if estimate else "unknown (no history yet)"
    ui.warn("No bell list available (fetch failed and no cache).")
    n_label = f"{total}" if total else "all"
    if not sys.stdin.isatty():
        # Can't ask (cron / pipe): proceed with all subs, but say so loudly.
        ui.warn(f"non-interactive: proceeding with all {n_label} subscriptions "
                f"(≈ {exp} videos). Run `yt-catalog login` for bell-only.")
        return None
    choice = ui.select(
        f"Catalog ALL {n_label} subscriptions instead of just bell-on channels?",
        [
            f"Continue — catalog all {n_label} subscriptions  (≈ {exp} videos)",
            "Cancel this run (re-run `yt-catalog login`, then try again)",
        ],
        default=1,
    )
    if choice == 0:
        ui.step(f"continuing with all {n_label} subscriptions")
        return None
    ui.step("cancelled")
    return _ABORT


def _ask_yes_no(question: str, default: bool) -> bool:
    # Arrow-select Yes/No (ui.confirm falls back to the default off-TTY).
    return ui.confirm(question, default=default)


def _find_runs() -> list[tuple[str, "object", str]]:
    """All runs under vault/runs that have a data.json checkpoint, newest first.

    Returns (date_str, CatalogRun, data_json_path).
    """
    runs_root = Path("vault") / "runs"
    out: list[tuple[str, object, str]] = []
    if not runs_root.is_dir():
        return out
    for d in sorted((p for p in runs_root.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        dj = d / "data.json"
        if dj.exists():
            try:
                out.append((d.name, load_checkpoint(str(dj)), str(dj)))
            except Exception:
                pass
    return out


def _describe_checkpoint(cp) -> str:
    """One-line human summary of a checkpoint's progress + API implication."""
    stage = {
        "scraping": "scraped (no metadata yet)",
        "enrichment": "scraped + metadata + thumbnails done",
        "categorization": "scraped, enriched, and categorized",
        "complete": "finished",
    }.get(cp.last_completed_phase, cp.last_completed_phase)
    if PHASE_ORDER.get(cp.last_completed_phase, 0) >= PHASE_ORDER["enrichment"]:
        api = "resuming will NOT re-spend YouTube API quota (details already fetched)"
    else:
        api = "resuming re-fetches video details (uses some YouTube API quota)"
    return f"{len(cp.videos)} videos, stage: {stage}; {api}"


def _maybe_resume(args: argparse.Namespace, run_date: str, run_dir: str) -> tuple[str, bool]:
    """Decide whether to resume a prior run. Returns (run_dir, exit_now).

    Sets args.from_checkpoint when resuming. Rules:
      - finished run TODAY  -> ask: re-run from scratch, or just view the data.
      - unfinished TODAY    -> auto-continue (no prompt).
      - unfinished PAST run -> ask (with progress info) whether to continue it.
    Honors explicit --from-checkpoint and --fresh (both skip auto-detection).
    """
    if args.from_checkpoint or getattr(args, "fresh", False):
        return run_dir, False
    runs = _find_runs()
    if not runs:
        return run_dir, False

    done = PHASE_ORDER["complete"]
    today = next(((dt, cp, p) for dt, cp, p in runs if dt == run_date), None)
    if today:
        dt, cp, p = today
        if PHASE_ORDER.get(cp.last_completed_phase, 0) >= done:
            print(f"\nA run already completed today — {len(cp.videos)} videos at {run_dir}/.")
            if _ask_yes_no("Re-run from scratch? (no = keep & view the existing run)", default=False):
                return run_dir, False
            print(f"Open {run_dir}/index.md to view the existing catalog.")
            return run_dir, True
        print(f"\nResuming today's unfinished run ({_describe_checkpoint(cp)}).")
        args.from_checkpoint = p
        return str(Path(p).parent), False

    past = next(((dt, cp, p) for dt, cp, p in runs
                 if PHASE_ORDER.get(cp.last_completed_phase, 0) < done), None)
    if past:
        dt, cp, p = past
        print(f"\nFound an unfinished run from {dt}: {_describe_checkpoint(cp)}.")
        if _ask_yes_no("Continue that run from where it stopped?", default=True):
            args.from_checkpoint = p
            return str(Path(p).parent), False
        print("Starting a fresh run.")
    return run_dir, False


def handle_run(args: argparse.Namespace) -> None:
    if args.ai_provider:
        os.environ["AI_PROVIDER"] = args.ai_provider

    ui.header("yt-catalog", "scrape · categorize · vault")
    data_dir = _enter_data_dir(args)
    ui.kv("Data dir", str(data_dir))

    run_date = date.today().isoformat()
    run_dir = str(Path("vault") / "runs" / run_date)

    # Resume detection — if a prior run is incomplete (or finished today), decide
    # whether to continue it, view it, or start fresh. May set args.from_checkpoint.
    run_dir, _exit_now = _maybe_resume(args, run_date, run_dir)
    if _exit_now:
        return

    checkpoint = None
    completed_phase = 0
    if args.from_checkpoint:
        checkpoint = load_checkpoint(args.from_checkpoint)
        completed_phase = PHASE_ORDER.get(checkpoint.last_completed_phase, 0)
        videos = checkpoint.videos
    else:
        videos = []

    # Incremental run detection
    first_run = is_first_run()
    last_date = get_last_video_date()
    prev_ids = get_last_run_video_ids()

    if first_run and not args.from_checkpoint:
        # Interactive first-run setup — let the user choose how to bootstrap
        source, max_days, max_videos = _first_run_prompt(args)
        args.source = source
        if max_days is not None:
            args.max_days = max_days
        if max_videos is not None:
            args.max_videos = max_videos

    # Resolve --source=auto: prefer the YouTube Data API when credentials exist,
    # else fall back to Chrome scraping. (Incremental runs never hit the
    # first-run prompt above, so without this they'd silently use Chrome.)
    # --bell only makes sense on the chrome path; honor it over auto-detect.
    if getattr(args, "bell", False) and args.source == "auto":
        args.source = "chrome"

    if args.source == "auto":
        args.source = _resolve_source()
        _why = {
            "web": "cookie web session detected",
            "api": "YouTube API credentials detected",
            "chrome": "no web/API setup found; using browser scraping",
        }.get(args.source, "")
        ui.kv("Source", f"{args.source}  ({_why})")

    # Chrome scraping needs the Claude CLI; warn if a different AI provider is set.
    if args.ai_provider and args.source == "chrome" and args.ai_provider != "claude-cli":
        print("Warning: Chrome integration requires Claude CLI for scraping. Notifications")
        print("will be scraped via Chrome, but AI categorization uses the specified provider.")

    median = get_daily_median()
    estimate = get_estimated_new_videos(last_date)
    if first_run:
        ui.kv("Mode", "first run")
    else:
        ui.kv("Mode", f"incremental (last video {last_date})")
        ui.detail(f"daily median {median:.1f} videos/day · estimated new ~{estimate}")

    # Phase 1: Scrape
    if completed_phase >= PHASE_ORDER["scraping"]:
        print("Skipping scraping (already completed in checkpoint)")
    else:
        import sys
        # Change A: keep channels.json (subscription source of truth) fresh from
        # the API when possible (no-op / cached fallback if the API is down).
        if args.source == "api":
            try:
                from ..api_scraper import _get_subscribed_channel_ids
                _get_subscribed_channel_ids()
            except Exception:
                pass
        channel_override = _resolve_channel_source(args, first_run, run_date, estimate)
        if channel_override is _ABORT:
            return

        # --source web: pull recent uploads from the authenticated subscriptions
        # feed (one quota-free GET). On the documented device-bound re-challenge
        # (or an empty parse) fall back web -> chrome -> api.
        scraped_web = False
        if args.source == "web":
            ui.phase(1, 4, "Scrape — subscriptions feed (web cookie session)")
            from ..web_session import SessionError
            try:
                from ..web_videos import scrape_via_web
                # reextract=False: use only the `yt-catalog login` token.
                videos = scrape_via_web(max_videos=args.max_videos, reextract=False)
            except SessionError as e:
                print(f"  Web session unavailable ({e}).", file=sys.stderr)
                videos = []
            except Exception as e:
                print(f"  Web source error ({type(e).__name__}: {e}).", file=sys.stderr)
                videos = []
            if channel_override and videos:
                allow = set(channel_override)
                videos = [v for v in videos if v.channel_id in allow]
            if videos:
                save_checkpoint(videos, run_dir, phase="scraping")
                ui.ok(f"Got {len(videos)} videos from the subscriptions feed")
                scraped_web = True
            else:
                # web -> api -> chrome: prefer the fast quota-cheap API over the
                # slow Chrome spawn when the cookie session is unavailable.
                import shutil as _sh
                if _api_available():
                    args.source = "api"
                elif _sh.which("claude"):
                    args.source = "chrome"
                else:
                    args.source = "api"  # last resort; will surface its own error
                ui.warn(f"Web session unavailable; falling back to {args.source}.")
                if args.source == "api":
                    try:
                        from ..api_scraper import _get_subscribed_channel_ids
                        _get_subscribed_channel_ids()
                    except Exception:
                        pass

        if scraped_web:
            pass  # web videos flow into Phase 2 enrichment (source != "api")
        elif args.source == "api":
            ui.phase(1, 4, "Scrape — YouTube Data API v3")
            since = None if first_run else last_date
            videos = scrape_via_api(
                max_days=args.max_days,
                max_videos=args.max_videos,
                since_date=since,
                channel_ids=channel_override,
            )
            # Dedup against previous run
            if prev_ids and videos:
                pre_dedup = len(videos)
                videos = [v for v in videos if v.video_id not in prev_ids]
                if pre_dedup != len(videos):
                    ui.step(f"deduped {pre_dedup - len(videos)} overlapping with previous run")
            if not videos:
                ui.warn("No videos found. Nothing to catalog.")
                return
            save_checkpoint(videos, run_dir, phase="scraping")
            ui.ok(f"Scraped {len(videos)} videos (already filtered)")
            # API path: skip enrichment since we already have full metadata
            ui.phase(2, 4, "Enrich — skipped (API provides full metadata)")
            ui.step("downloading thumbnails")
            download_thumbnails(videos, run_dir)
            save_checkpoint(videos, run_dir, phase="enrichment")
        else:
            strategy, count = _choose_notification_source(args, estimate=estimate)
            if strategy == "bell":
                ui.phase(1, 4, "Scrape — bell dropdown (chrome)")
                videos = scrape_notifications(max_days=args.max_days, max_videos=count)
            else:  # "rss" — fetch the N most-recent uploads across subs (no quota)
                label = str(count) if count else "all recent"
                ui.phase(1, 4, f"Scrape — {label} recent uploads via RSS (no API quota)")
                videos = scrape_recent_via_rss(max_videos=count, channel_ids=channel_override)
            if not videos:
                ui.warn("No videos found. Nothing to catalog.")
                return
            save_checkpoint(videos, run_dir, phase="scraping")
            ui.ok(f"Got {len(videos)} videos")

    # Phase 2: Enrich (web/chrome source -- api source already completed above)
    if completed_phase < PHASE_ORDER["enrichment"] and args.source != "api":
        ui.phase(2, 4, "Enrich — video metadata via InnerTube")
        videos = enrich_videos_innertube(videos)
        pre_filter = len(videos)
        videos = [v for v in videos if not v.is_short and not v.is_live]
        filtered_count = pre_filter - len(videos)
        if filtered_count:
            ui.step(f"removed {filtered_count} Shorts/Livestreams")

        # Auto-save channel name->ID map for future API runs
        channels_map = {}
        for v in videos:
            if v.channel and v.channel_id:
                channels_map[v.channel] = v.channel_id
        if channels_map:
            _save_channels_json(channels_map)

        ui.step("downloading thumbnails")
        download_thumbnails(videos, run_dir)
        save_checkpoint(videos, run_dir, phase="enrichment", shorts_filtered=filtered_count)
        ui.ok(f"Enriched {len(videos)} videos")
    elif completed_phase < PHASE_ORDER["enrichment"] and args.source == "api":
        # Already handled in scraping block above
        pass
    else:
        ui.step("skipping enrichment (already completed in checkpoint)")

    # Optional: filter out videos already watched >= threshold%. Watch history
    # is NOT exposed by the YouTube Data API, so this always reads it via the
    # Chrome integration. After an API scrape (fast), confirm before starting
    # the slower Chrome pass; if the scrape was Chrome anyway, just proceed.
    if args.filter_watched and videos and completed_phase < PHASE_ORDER["categorization"]:
        proceed = _confirm_chrome_watch_filter() if args.source == "api" else True
        if not proceed:
            ui.step("skipping watch-history filter; keeping all videos")
        else:
            oldest = min((v.upload_date for v in videos if v.upload_date), default="")
            since_date = (oldest or "").split("T")[0]
            if since_date:
                ui.step(f"filtering against watch history since {since_date} (>={args.watched_threshold}% watched)")
                watched_ids = fetch_watched_ids(since_date, min_percent=args.watched_threshold)
                if watched_ids:
                    pre_count = len(videos)
                    videos = [v for v in videos if v.video_id not in watched_ids]
                    dropped = pre_count - len(videos)
                    ui.ok(f"dropped {dropped} already-watched videos ({len(watched_ids)} in history window)")
                    save_checkpoint(videos, run_dir, phase="enrichment")
                else:
                    ui.step("no watch-history entries collected; keeping all videos")
            else:
                ui.step("no upload_date on scraped videos; skipping watch filter")

    # Phase 3: Categorize & Rank
    if completed_phase < PHASE_ORDER["categorization"]:
        if not videos:
            ui.warn("No videos left after filters. Nothing to categorize.")
            return
        ui.phase(3, 4, "Categorize & rank")
        videos = categorize_and_rank(videos)
        save_checkpoint(videos, run_dir, phase="categorization")
        ui.ok(f"Categorized {len(videos)} videos")
    else:
        ui.step("skipping categorization (already completed in checkpoint)")

    # Phase 4: Generate Obsidian vault (hiding anything already marked
    # watched/skipped in a prior run).
    ui.phase(4, 4, "Generate Obsidian vault")
    from ..curate import load_state
    generate_vault(videos, run_dir,
                   mermaid_thumbnails=not args.no_mermaid_thumbnails,
                   state=load_state())
    ui.ok(f"vault written to {run_dir}/")

    # Update run state for incremental tracking
    stats = update_after_run(
        [video_to_dict(v) for v in videos],
        run_date,
    )
    # Mark the run finished so a re-run today offers "view vs restart" instead
    # of silently redoing everything.
    save_checkpoint(videos, run_dir, phase="complete")
    try:
        vault_uri = Path(run_dir).resolve().as_uri()
    except Exception:
        vault_uri = None
    pairs = [
        ("Vault", f"{run_dir}/", vault_uri),
        ("Videos", f"{stats['total_videos']} total · {stats['new_videos']} new"),
    ]
    if stats['overlap_with_previous']:
        pairs.append(("Overlap w/ previous", str(stats['overlap_with_previous'])))
    pairs.append(("Daily median", f"{stats['daily_median']:.1f} videos/day"))
    pairs.append(("Next run estimate", f"~{stats['estimated_next_run']} videos"))
    ui.summary("Done", pairs)
