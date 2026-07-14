#!/usr/bin/env bash
# sakura bind wrapper from SakuraSoft root.
# Usage: ./shared/scripts/sakura-bind.sh set SLOT ASSET [flags...]
#        ./shared/scripts/sakura-bind.sh list [--title ...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/sakura/.venv"
if [[ ! -x "$VENV/bin/sakura" ]]; then
  echo "sakura CLI not installed. Run:" >&2
  echo "  cd $ROOT/tools/sakura && uv venv && uv pip install -e ." >&2
  exit 2
fi
if [[ $# -lt 1 ]]; then
  exec "$VENV/bin/sakura" bind --help
fi
SUB="$1"
shift
exec "$VENV/bin/sakura" bind "$SUB" --catalog "$ROOT/catalog" "$@"
