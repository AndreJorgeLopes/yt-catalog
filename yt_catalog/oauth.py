"""OAuth 2.0 for YouTube Data API — stdlib-only (no google-auth, no requests)."""

from __future__ import annotations
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "yt-catalog"
TOKENS_FILE = CONFIG_DIR / "oauth_tokens.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def save_config(client_id: str, client_secret: str, api_key: str | None = None) -> None:
    """Save OAuth client credentials (and optionally API key) to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    data["client_id"] = client_id
    data["client_secret"] = client_secret
    if api_key is not None:
        data["api_key"] = api_key
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def load_config() -> dict:
    """Load config from CONFIG_DIR/config.json. Returns empty dict if missing."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_tokens(tokens: dict) -> None:
    """Save OAuth tokens to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Store the time we received the tokens so we can check expiry
    tokens["saved_at"] = time.time()
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def _load_tokens() -> dict | None:
    """Load OAuth tokens from disk. Returns None if missing."""
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text())
        except Exception:
            return None
    return None


def is_authenticated() -> bool:
    """Check if we have valid OAuth tokens with a refresh_token."""
    tokens = _load_tokens()
    return tokens is not None and "refresh_token" in tokens


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    auth_code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            _OAuthCallbackHandler.error = params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2>Error: {params['error'][0]}</h2></body></html>".encode()
            )
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Suppress HTTP server log output
        pass


def authorize(client_id: str, client_secret: str) -> dict:
    """Run the full OAuth 2.0 authorization code flow with PKCE.

    Opens a browser for user consent, starts a temporary localhost server
    to receive the callback, exchanges the code for tokens, and saves them.

    Returns the token response dict.
    """
    code_verifier, code_challenge = _generate_pkce()

    # Start temporary HTTP server on a random port
    server = http.server.HTTPServer(("127.0.0.1", 0), _OAuthCallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}"

    # Reset class-level state
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.error = None

    # Build authorization URL
    auth_params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{AUTH_URL}?{auth_params}"

    print(f"\nOpening browser for authorization...")
    print(f"If the browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for callback (timeout after 120 seconds)
    server.timeout = 120
    while _OAuthCallbackHandler.auth_code is None and _OAuthCallbackHandler.error is None:
        server.handle_request()

    server.server_close()

    if _OAuthCallbackHandler.error:
        print(f"Authorization failed: {_OAuthCallbackHandler.error}", file=sys.stderr)
        sys.exit(1)

    auth_code = _OAuthCallbackHandler.auth_code
    if not auth_code:
        print("No authorization code received.", file=sys.stderr)
        sys.exit(1)

    # Exchange code for tokens
    token_data = urllib.parse.urlencode({
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        tokens = json.loads(resp.read())
    except Exception as e:
        print(f"Token exchange failed: {e}", file=sys.stderr)
        sys.exit(1)

    _save_tokens(tokens)
    print("Authorization successful! Tokens saved.")
    return tokens


def refresh_access_token() -> str:
    """Refresh the access token using the stored refresh_token.

    Returns the new access_token string.
    """
    tokens = _load_tokens()
    if not tokens or "refresh_token" not in tokens:
        raise RuntimeError("No refresh token available. Run 'yt-catalog setup' first.")

    config = load_config()
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")
    if not client_id or not client_secret:
        raise RuntimeError("No client credentials found. Run 'yt-catalog setup' first.")

    refresh_data = urllib.parse.urlencode({
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=refresh_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    new_tokens = json.loads(resp.read())

    # Merge: keep the existing refresh_token if the response doesn't include one
    if "refresh_token" not in new_tokens:
        new_tokens["refresh_token"] = tokens["refresh_token"]

    _save_tokens(new_tokens)
    return new_tokens["access_token"]


def get_access_token() -> str:
    """Get a valid access token, auto-refreshing if expired (within 5 min).

    Returns the access_token string.
    """
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated. Run 'yt-catalog setup' first.")

    # Check if token is expired or will expire within 5 minutes
    saved_at = tokens.get("saved_at", 0)
    expires_in = tokens.get("expires_in", 3600)
    expires_at = saved_at + expires_in
    buffer = 300  # 5 minutes

    if time.time() >= (expires_at - buffer):
        return refresh_access_token()

    return tokens["access_token"]
