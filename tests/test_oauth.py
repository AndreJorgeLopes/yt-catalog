"""Tests for oauth module — token save/load, config save/load, refresh logic."""
import json
import time
from unittest.mock import patch, MagicMock

import pytest
from yt_catalog.oauth import (
    save_config,
    load_config,
    is_authenticated,
    get_access_token,
    refresh_access_token,
    _save_tokens,
    _load_tokens,
    _generate_pkce,
    CONFIG_DIR,
    TOKENS_FILE,
    CONFIG_FILE,
)


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to tmp_path so tests don't touch real config."""
    fake_dir = tmp_path / "yt-catalog-config"
    monkeypatch.setattr("yt_catalog.oauth.CONFIG_DIR", fake_dir)
    monkeypatch.setattr("yt_catalog.oauth.TOKENS_FILE", fake_dir / "oauth_tokens.json")
    monkeypatch.setattr("yt_catalog.oauth.CONFIG_FILE", fake_dir / "config.json")
    return fake_dir


# ── Config save/load ─────────────────────────────────────────────────────────

def test_save_and_load_config(isolate_config):
    save_config("my-client-id", "my-secret")
    config = load_config()
    assert config["client_id"] == "my-client-id"
    assert config["client_secret"] == "my-secret"
    assert "api_key" not in config


def test_load_config_missing(isolate_config):
    config = load_config()
    assert config == {}


def test_save_config_overwrites_previous(isolate_config):
    save_config("id1", "secret1")
    save_config("id2", "secret2")
    config = load_config()
    assert config["client_id"] == "id2"
    assert config["client_secret"] == "secret2"


# ── Token save/load ──────────────────────────────────────────────────────────

def test_save_and_load_tokens(isolate_config):
    tokens = {
        "access_token": "ya29.test",
        "refresh_token": "1//test",
        "expires_in": 3600,
    }
    _save_tokens(tokens)
    loaded = _load_tokens()
    assert loaded["access_token"] == "ya29.test"
    assert loaded["refresh_token"] == "1//test"
    assert "saved_at" in loaded


def test_load_tokens_missing(isolate_config):
    assert _load_tokens() is None


# ── is_authenticated ─────────────────────────────────────────────────────────

def test_is_authenticated_true(isolate_config):
    _save_tokens({"access_token": "ya29.test", "refresh_token": "1//test", "expires_in": 3600})
    assert is_authenticated() is True


def test_is_authenticated_false_no_tokens(isolate_config):
    assert is_authenticated() is False


def test_is_authenticated_false_no_refresh(isolate_config):
    _save_tokens({"access_token": "ya29.test", "expires_in": 3600})
    assert is_authenticated() is False


# ── get_access_token ─────────────────────────────────────────────────────────

def test_get_access_token_valid(isolate_config):
    """Returns existing token if not expired."""
    _save_tokens({
        "access_token": "ya29.valid",
        "refresh_token": "1//test",
        "expires_in": 3600,
    })
    token = get_access_token()
    assert token == "ya29.valid"


def test_get_access_token_expired_triggers_refresh(isolate_config):
    """Expired token triggers refresh."""
    tokens = {
        "access_token": "ya29.old",
        "refresh_token": "1//test",
        "expires_in": 3600,
        "saved_at": time.time() - 7200,  # 2 hours ago — expired
    }
    _save_tokens(tokens)
    # Manually set saved_at to make it appear expired
    raw = json.loads((isolate_config / "oauth_tokens.json").read_text())
    raw["saved_at"] = time.time() - 7200
    (isolate_config / "oauth_tokens.json").write_text(json.dumps(raw))

    save_config("test-client", "test-secret")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "access_token": "ya29.refreshed",
        "expires_in": 3600,
    }).encode()

    with patch("yt_catalog.oauth.urllib.request.urlopen", return_value=mock_response):
        token = get_access_token()

    assert token == "ya29.refreshed"


def test_get_access_token_no_tokens(isolate_config):
    """Raises RuntimeError if no tokens exist."""
    with pytest.raises(RuntimeError, match="Not authenticated"):
        get_access_token()


# ── refresh_access_token ─────────────────────────────────────────────────────

def test_refresh_preserves_refresh_token(isolate_config):
    """If token response doesn't include refresh_token, keep the old one."""
    _save_tokens({
        "access_token": "ya29.old",
        "refresh_token": "1//my-refresh",
        "expires_in": 3600,
    })
    save_config("test-client", "test-secret")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "access_token": "ya29.new",
        "expires_in": 3600,
        # No refresh_token in response
    }).encode()

    with patch("yt_catalog.oauth.urllib.request.urlopen", return_value=mock_response):
        new_token = refresh_access_token()

    assert new_token == "ya29.new"
    loaded = _load_tokens()
    assert loaded["refresh_token"] == "1//my-refresh"


def test_refresh_no_refresh_token(isolate_config):
    """Raises RuntimeError if no refresh_token stored."""
    _save_tokens({"access_token": "ya29.test", "expires_in": 3600})
    with pytest.raises(RuntimeError, match="No refresh token"):
        refresh_access_token()


def test_refresh_no_client_credentials(isolate_config):
    """Raises RuntimeError if no client credentials in config."""
    _save_tokens({
        "access_token": "ya29.old",
        "refresh_token": "1//test",
        "expires_in": 3600,
    })
    with pytest.raises(RuntimeError, match="No client credentials"):
        refresh_access_token()


# ── PKCE ─────────────────────────────────────────────────────────────────────

def test_pkce_generation():
    verifier, challenge = _generate_pkce()
    assert len(verifier) > 40
    assert len(challenge) > 20
    # Challenge should be base64url encoded (no padding)
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge
