#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/sakura/.venv"
if [[ ! -x "$VENV/bin/sakura" ]]; then
  echo "Install: cd $ROOT/tools/sakura && uv venv && uv pip install -e ." >&2
  exit 2
fi
exec "$VENV/bin/sakura" studio --catalog "$ROOT/catalog" "$@"
