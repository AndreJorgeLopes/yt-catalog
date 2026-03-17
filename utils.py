"""Utility functions for the YouTube Notification Cataloger."""
from __future__ import annotations
import os
import time
import sys
from pathlib import Path
from typing import Callable, TypeVar


def load_dotenv(dotenv_path: str | None = None) -> None:
    """Load .env file into os.environ. No-op if file doesn't exist."""
    path = Path(dotenv_path) if dotenv_path else Path(__file__).parent / ".env"
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


def retry(fn: Callable[[], T], max_retries: int = 3, delay: float = 2, backoff: float = 2) -> T:
    """Retry a function with exponential backoff.

    Args:
        fn: Zero-argument callable to retry.
        max_retries: Maximum number of attempts (default 3).
        delay: Initial delay in seconds between retries (default 2).
        backoff: Multiplier applied to delay after each failure (default 2).

    Returns:
        The return value of fn() on success.

    Raises:
        The last exception raised by fn() if all retries are exhausted.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = delay * (backoff ** attempt)
            print(f"  Retry {attempt + 1}/{max_retries} after {wait:.0f}s: {e}", file=sys.stderr)
            time.sleep(wait)
    # unreachable, but satisfies type checker
    raise RuntimeError("retry exhausted")  # pragma: no cover
