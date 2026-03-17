"""Utility functions for the YouTube Notification Cataloger."""
from __future__ import annotations
import time
import sys
from typing import Callable, TypeVar

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
