#!/usr/bin/env bash
# One command after .env is in place: install what is missing, then serve the app.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x "${HOME}/.local/bin/uv" ]]; then
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv が見つかりません。https://docs.astral.sh/uv/ を見てインストールしてください。" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  uv sync --all-groups
fi

if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend install
fi

if [[ ! -f frontend/dist/index.html ]]; then
  npm --prefix frontend run build
fi

exec uv run tomoshibi "$@"
