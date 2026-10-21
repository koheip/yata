#!/usr/bin/env bash
# API on 8741 and the Vite dev server on 8742, with /api proxied to the API.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x "${HOME}/.local/bin/uv" ]]; then
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [[ ! -d .venv ]]; then
  uv sync --all-groups
fi
if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend install
fi

uv run tomoshibi --host 127.0.0.1 --port 8741 &
api_pid=$!
trap 'kill ${api_pid} 2>/dev/null || true' EXIT

npm --prefix frontend run dev
