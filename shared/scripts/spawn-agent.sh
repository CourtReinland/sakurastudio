#!/bin/bash
# Spawn a new Claude Code agent in its own worktree
#
# Requires a local Unity / game checkout. Defaults:
#   SAKURA_AGENT_PROJECT  — project with git worktrees (default: $SAKURA_UNITY_ROOT or ./projects/sakura-match)
#   SAKURA_AGENT_WORKTREES — worktree parent (default: ./worktrees next to project)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROJECT_DIR="${SAKURA_AGENT_PROJECT:-${SAKURA_UNITY_ROOT:-$REPO_ROOT/projects/sakura-match}}"
WORKTREE_DIR="${SAKURA_AGENT_WORKTREES:-$(dirname "$PROJECT_DIR")/worktrees}"
AGENT_NAME=${1:-}
TASK=${2:-}

if [ -z "$AGENT_NAME" ]; then
    echo "Usage: spawn-agent.sh <agent-name> [task]"
    echo "Example: spawn-agent.sh research 'Analyze top match-3 games'"
    echo "Set SAKURA_AGENT_PROJECT or SAKURA_UNITY_ROOT to your Unity/game checkout."
    exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ] && [ ! -f "$PROJECT_DIR/.git" ]; then
    echo "ERROR: Not a git checkout: $PROJECT_DIR"
    echo "Clone/checkout the game repo and set SAKURA_AGENT_PROJECT or SAKURA_UNITY_ROOT."
    exit 1
fi

BRANCH_NAME="agent/${AGENT_NAME}"
WORKTREE_PATH="${WORKTREE_DIR}/sakura-match-${AGENT_NAME}"

# Create worktree if it doesn't exist
if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Creating worktree for ${AGENT_NAME}..."
    mkdir -p "$WORKTREE_DIR"
    cd "$PROJECT_DIR"
    git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>/dev/null || \
    git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"
fi

# Navigate to worktree
cd "$WORKTREE_PATH"

echo "==================================="
echo "Agent: ${AGENT_NAME}"
echo "Worktree: ${WORKTREE_PATH}"
echo "Branch: ${BRANCH_NAME}"
echo "==================================="

# Start Claude Code with task if provided
if [ -n "$TASK" ]; then
    echo "Starting Claude with task: ${TASK}"
    claude "$TASK"
else
    echo "Starting Claude Code..."
    claude
fi
