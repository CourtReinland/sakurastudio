#!/usr/bin/env bash
# Universal sakura CLI wrapper (works from Ghostty / any cwd).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/sakura/.venv"
BIN="$VENV/bin/sakura"
if [[ ! -x "$BIN" ]]; then
  echo "sakura CLI not installed. Run once:" >&2
  echo "  cd $ROOT/tools/sakura && uv venv && uv pip install -e ." >&2
  exit 2
fi
# default catalog if not already in args
export SAKURA_CATALOG="${SAKURA_CATALOG:-$ROOT/catalog}"
exec "$BIN" "$@"
