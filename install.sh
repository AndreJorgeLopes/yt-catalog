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

# Setup .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it to add your YOUTUBE_API_KEY and ANTHROPIC_API_KEY"
fi

echo ""
echo "yt-catalog installed!"
echo "   Run:   yt-catalog --help"
echo "   Setup: yt-catalog setup"
