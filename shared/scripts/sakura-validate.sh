#!/usr/bin/env bash
# Run catalog validator from anywhere under SakuraSoft.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/sakura/.venv"
if [[ ! -x "$VENV/bin/sakura" ]]; then
  echo "sakura CLI not installed. Run:" >&2
  echo "  cd $ROOT/tools/sakura && uv venv && uv pip install -e ." >&2
  exit 2
fi
exec "$VENV/bin/sakura" validate --catalog "$ROOT/catalog" "$@"
