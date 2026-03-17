"""AI provider abstraction — supports Claude CLI, Anthropic API, OpenAI API, OpenCode, Codex."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.request


def get_provider() -> str:
    return os.environ.get("AI_PROVIDER", "claude-cli")


def categorize_with_ai(prompt: str) -> str | None:
    """Send a categorization prompt to the configured AI provider. Returns raw text response."""
    provider = get_provider()
    if provider == "claude-cli":
        return _call_cli("claude", prompt)
    elif provider == "opencode-cli":
        return _call_cli("opencode", prompt)
    elif provider == "codex-cli":
        return _call_cli("codex", prompt)
    elif provider == "anthropic":
        return _call_anthropic_api(prompt)
    elif provider == "openai":
        return _call_openai_api(prompt)
    else:
        print(f"Unknown AI_PROVIDER: {provider}. Using rule-based fallback.", file=sys.stderr)
        return None


def _call_cli(cli_name: str, prompt: str) -> str | None:
    """Call a CLI tool (claude/opencode/codex) with --print."""
    try:
        result = subprocess.run(
            [cli_name, "--print", "-p", prompt],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"{cli_name} failed: {result.stderr[:200]}", file=sys.stderr)
            return None
        return result.stdout
    except FileNotFoundError:
        print(f"{cli_name} not found. Install it or use a different AI_PROVIDER.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"{cli_name} timed out after 300s.", file=sys.stderr)
        return None


def _call_anthropic_api(prompt: str) -> str | None:
    """Call Anthropic's Messages API directly."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return None
    try:
        body = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        return data.get("content", [{}])[0].get("text", "")
    except Exception as e:
        print(f"Anthropic API error: {e}", file=sys.stderr)
        return None


def _call_openai_api(prompt: str) -> str | None:
    """Call OpenAI's Chat Completions API directly."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set.", file=sys.stderr)
        return None
    try:
        body = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"OpenAI API error: {e}", file=sys.stderr)
        return None


def chrome_supported() -> bool:
    """Chrome integration only works with Claude CLI (has MCP tools)."""
    return get_provider() == "claude-cli"
