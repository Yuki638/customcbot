#!/usr/bin/env sh
# Starts customcbot on macOS and Linux. Run it from a terminal:  ./start.sh
# The first run downloads what it needs (about 1 GB), so it takes a few minutes.
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    PATH="$HOME/.local/bin:$PATH"
  else
    echo "Installing uv (a small tool that sets up Python for this app)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
  fi
fi

exec uv run --no-dev customcbot "$@"
