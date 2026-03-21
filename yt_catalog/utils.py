"""Utility functions for the YouTube Notification Cataloger."""
from __future__ import annotations
import os
import time
import sys
from pathlib import Path
from typing import Callable, TypeVar


def load_dotenv(dotenv_path: str | None = None) -> None:
    """Load .env file into os.environ. No-op if file doesn't exist."""
    path = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:  # Don't override existing env vars
                os.environ[key] = value

T = TypeVar("T")


def retry(fn: Callable[[], T], max_retries: int = 3, delay: float = 2, backoff: float = 2,
          dont_retry: tuple[type[BaseException], ...] = ()) -> T:
    """Retry a function with exponential backoff.

    Args:
        fn: Zero-argument callable to retry.
        max_retries: Maximum number of attempts (default 3).
        delay: Initial delay in seconds between retries (default 2).
        backoff: Multiplier applied to delay after each failure (default 2).
        dont_retry: Exception types that should propagate immediately without
            retrying (e.g. a quota error, where retrying is pointless).

    Returns:
        The return value of fn() on success.

    Raises:
        The last exception raised by fn() if all retries are exhausted, or any
        exception in dont_retry on its first occurrence.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except dont_retry:
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = delay * (backoff ** attempt)
            print(f"  Retry {attempt + 1}/{max_retries} after {wait:.0f}s: {e}", file=sys.stderr)
            time.sleep(wait)
    # unreachable, but satisfies type checker
    raise RuntimeError("retry exhausted")  # pragma: no cover


def progress_bar(done: int, total: int, label: str = "", width: int = 30) -> None:
    """Render an in-place progress bar to stderr.

    On a TTY: a live `\\r`-updated bar that newlines once complete. On a non-TTY
    (piped/CI), falls back to occasional count lines so logs aren't smeared with
    carriage returns.
    """
    if total <= 0:
        return
    if not sys.stderr.isatty():
        step = max(1, total // 10)
        if done == total or done % step == 0:
            print(f"  {label}{done}/{total}", file=sys.stderr)
        return
    frac = done / total
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    end = "\n" if done >= total else ""
    print(f"\r  {label}[{bar}] {done}/{total} ({frac * 100:3.0f}%)",
          end=end, flush=True, file=sys.stderr)


def _looks_like_catalog_dir(p: Path) -> bool:
    """True if directory p already holds yt-catalog data (a vault or channels.json)."""
    return (p / "vault").is_dir() or (p / "channels.json").exists()


def get_data_dir() -> Path:
    """Resolve the base directory for catalog data (vault/, runs/, channels.json).

    Precedence:
      1. $YT_CATALOG_DATA_DIR
      2. the current directory, if it already looks like a catalog dir
      3. 'data_dir' saved in ~/.config/yt-catalog/config.json
      4. default ~/.local/share/yt-catalog
    """
    env = os.environ.get("YT_CATALOG_DATA_DIR")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd()
    if _looks_like_catalog_dir(cwd):
        return cwd
    try:
        from .oauth import load_config
        saved = load_config().get("data_dir")
        if saved:
            return Path(saved).expanduser()
    except Exception:
        pass
    return Path.home() / ".local" / "share" / "yt-catalog"
