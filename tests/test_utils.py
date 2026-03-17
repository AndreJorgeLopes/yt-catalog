"""Tests for retry utility in utils.py."""
import time
from unittest.mock import patch
import pytest
from utils import retry


def test_retry_succeeds_on_first_try():
    """Function succeeds immediately, no retries needed."""
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry(fn, max_retries=3, delay=0, backoff=1)
    assert result == "ok"
    assert len(calls) == 1


def test_retry_succeeds_on_second_try():
    """Function fails once then succeeds."""
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("temporary failure")
        return "ok"

    with patch("utils.time.sleep"):
        result = retry(fn, max_retries=3, delay=1, backoff=2)
    assert result == "ok"
    assert len(calls) == 2


def test_retry_exhausted_raises_last_exception():
    """When all retries fail, the last exception is re-raised."""
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError(f"fail #{len(calls)}")

    with patch("utils.time.sleep"):
        with pytest.raises(RuntimeError, match="fail #3"):
            retry(fn, max_retries=3, delay=1, backoff=2)
    assert len(calls) == 3


def test_retry_uses_exponential_backoff():
    """Sleep durations follow exponential backoff pattern."""
    sleep_calls = []
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("fail")
        return "done"

    with patch("utils.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        result = retry(fn, max_retries=3, delay=2, backoff=3)

    assert result == "done"
    assert sleep_calls == [2.0, 6.0]  # 2*3^0=2, 2*3^1=6


def test_retry_max_retries_one_raises_immediately():
    """With max_retries=1, a single failure raises immediately."""
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("fail")

    with pytest.raises(ValueError):
        retry(fn, max_retries=1, delay=0, backoff=1)
    assert len(calls) == 1


def test_retry_prints_retry_message(capsys):
    """Retry attempts print a message to stderr."""
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("network error")
        return "ok"

    with patch("utils.time.sleep"):
        retry(fn, max_retries=3, delay=1, backoff=2)

    captured = capsys.readouterr()
    assert "Retry 1/3" in captured.err
    assert "network error" in captured.err
