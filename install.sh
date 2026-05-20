#!/usr/bin/env bash
set -euo pipefail

# yt-catalog installer
REPO="https://github.com/andrejorgelopes/yt-catalog.git"
INSTALL_DIR="${HOME}/.local/share/yt-catalog"

echo "Installing yt-catalog..."

# Clone or update
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
pip install -e . --quiet

# yt-dlp exports the browser's YouTube cookies for the headless web session
# (bell channels + watch history). pip install above pulls it in, but prefer a
# PATH-level install if the user has pipx/brew so the console script is global.
if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Installing yt-dlp (cookie export for the web session)..."
    if command -v pipx >/dev/null 2>&1; then
        pipx install yt-dlp || true
    elif command -v brew >/dev/null 2>&1; then
        brew install yt-dlp || true
    fi
fi

# Setup .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it to add your YOUTUBE_API_KEY and ANTHROPIC_API_KEY"
fi

echo ""
echo "yt-catalog installed!"
echo "   Run:   yt-catalog --help"
echo "   Setup: yt-catalog setup"
