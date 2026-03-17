"""Tests for the AI provider abstraction module."""
from __future__ import annotations
import json
from io import BytesIO
from unittest.mock import MagicMock, patch


def test_get_provider_default():
    """get_provider returns 'claude-cli' when AI_PROVIDER is not set."""
    import os
    from yt_catalog.ai_provider import get_provider

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AI_PROVIDER", None)
        assert get_provider() == "claude-cli"


def test_get_provider_from_env():
    """get_provider reads from AI_PROVIDER env var."""
    import os
    from yt_catalog.ai_provider import get_provider

    with patch.dict(os.environ, {"AI_PROVIDER": "openai"}):
        assert get_provider() == "openai"


def test_chrome_supported_claude_cli():
    """chrome_supported returns True only when provider is claude-cli."""
    import os
    from yt_catalog.ai_provider import chrome_supported

    with patch.dict(os.environ, {"AI_PROVIDER": "claude-cli"}):
        assert chrome_supported() is True


def test_chrome_supported_other_provider():
    """chrome_supported returns False for non-claude-cli providers."""
    import os
    from yt_catalog.ai_provider import chrome_supported

    for provider in ("anthropic", "openai", "opencode-cli", "codex-cli"):
        with patch.dict(os.environ, {"AI_PROVIDER": provider}):
            assert chrome_supported() is False, f"Expected False for provider={provider}"


def test_categorize_with_ai_unknown_provider_returns_none(capsys):
    """categorize_with_ai returns None and prints warning for unknown provider."""
    import os
    from yt_catalog.ai_provider import categorize_with_ai

    with patch.dict(os.environ, {"AI_PROVIDER": "nonexistent-provider"}):
        result = categorize_with_ai("some prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "Unknown AI_PROVIDER" in captured.err


def test_call_anthropic_api_success():
    """_call_anthropic_api returns text from a successful API response."""
    import os
    from yt_catalog.ai_provider import _call_anthropic_api

    fake_response_body = json.dumps({
        "content": [{"text": "categorized output"}]
    }).encode()
    fake_resp = MagicMock()
    fake_resp.read.return_value = fake_response_body

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("yt_catalog.ai_provider.urllib.request.urlopen", return_value=fake_resp):
            result = _call_anthropic_api("test prompt")

    assert result == "categorized output"


def test_call_anthropic_api_no_key(capsys):
    """_call_anthropic_api returns None and prints error when key is missing."""
    import os
    from yt_catalog.ai_provider import _call_anthropic_api

    env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = _call_anthropic_api("test prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY not set" in captured.err


def test_call_openai_api_success():
    """_call_openai_api returns text from a successful API response."""
    import os
    from yt_catalog.ai_provider import _call_openai_api

    fake_response_body = json.dumps({
        "choices": [{"message": {"content": "openai output"}}]
    }).encode()
    fake_resp = MagicMock()
    fake_resp.read.return_value = fake_response_body

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("yt_catalog.ai_provider.urllib.request.urlopen", return_value=fake_resp):
            result = _call_openai_api("test prompt")

    assert result == "openai output"


def test_call_openai_api_no_key(capsys):
    """_call_openai_api returns None and prints error when key is missing."""
    import os
    from yt_catalog.ai_provider import _call_openai_api

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_API_KEY", None)
        result = _call_openai_api("test prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY not set" in captured.err


def test_categorize_with_ai_routes_to_claude_cli():
    """categorize_with_ai with claude-cli routes to _call_cli('claude', ...)."""
    import os
    from yt_catalog import ai_provider

    with patch.dict(os.environ, {"AI_PROVIDER": "claude-cli"}):
        with patch.object(ai_provider, "_call_cli", return_value="result") as mock_cli:
            result = ai_provider.categorize_with_ai("prompt")

    mock_cli.assert_called_once_with("claude", "prompt")
    assert result == "result"


def test_categorize_with_ai_routes_to_anthropic():
    """categorize_with_ai with anthropic routes to _call_anthropic_api."""
    import os
    from yt_catalog import ai_provider

    with patch.dict(os.environ, {"AI_PROVIDER": "anthropic"}):
        with patch.object(ai_provider, "_call_anthropic_api", return_value="result") as mock_api:
            result = ai_provider.categorize_with_ai("prompt")

    mock_api.assert_called_once_with("prompt")
    assert result == "result"


def test_categorize_with_ai_routes_to_openai():
    """categorize_with_ai with openai routes to _call_openai_api."""
    import os
    from yt_catalog import ai_provider

    with patch.dict(os.environ, {"AI_PROVIDER": "openai"}):
        with patch.object(ai_provider, "_call_openai_api", return_value="result") as mock_api:
            result = ai_provider.categorize_with_ai("prompt")

    mock_api.assert_called_once_with("prompt")
    assert result == "result"


def test_call_cli_not_found(capsys):
    """_call_cli returns None and prints error when CLI binary is not found."""
    from yt_catalog.ai_provider import _call_cli

    with patch("yt_catalog.ai_provider.subprocess.run", side_effect=FileNotFoundError):
        result = _call_cli("nonexistent-cli", "prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_call_cli_timeout(capsys):
    """_call_cli returns None and prints error on timeout."""
    import subprocess
    from yt_catalog.ai_provider import _call_cli

    with patch("yt_catalog.ai_provider.subprocess.run", side_effect=subprocess.TimeoutExpired("cli", 300)):
        result = _call_cli("claude", "prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "timed out" in captured.err


def test_call_cli_nonzero_return(capsys):
    """_call_cli returns None and prints error on non-zero exit code."""
    import subprocess
    from yt_catalog.ai_provider import _call_cli

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "some error"
    with patch("yt_catalog.ai_provider.subprocess.run", return_value=mock_result):
        result = _call_cli("claude", "prompt")

    assert result is None
    captured = capsys.readouterr()
    assert "failed" in captured.err
