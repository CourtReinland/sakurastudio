#!/bin/bash
# Clean up all agent worktrees
#
# Uses SAKURA_AGENT_PROJECT or SAKURA_UNITY_ROOT (default: ./projects/sakura-match).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROJECT_DIR="${SAKURA_AGENT_PROJECT:-${SAKURA_UNITY_ROOT:-$REPO_ROOT/projects/sakura-match}}"

if [ ! -d "$PROJECT_DIR/.git" ] && [ ! -f "$PROJECT_DIR/.git" ]; then
    echo "ERROR: Not a git checkout: $PROJECT_DIR"
    echo "Set SAKURA_AGENT_PROJECT or SAKURA_UNITY_ROOT to your Unity/game checkout."
    exit 1
fi

cd "$PROJECT_DIR"

echo "Current worktrees:"
git worktree list

echo ""
read -p "Remove all agent worktrees? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    git worktree list --porcelain | grep "worktree" | grep "agent" | cut -d' ' -f2 | while read worktree; do
        echo "Removing: $worktree"
        git worktree remove "$worktree" --force
    done
    echo "Cleanup complete!"
fi
