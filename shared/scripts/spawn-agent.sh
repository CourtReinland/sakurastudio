#!/bin/bash
# Spawn a new Claude Code agent in its own worktree

PROJECT_DIR="$HOME/SakuraSoft/projects/sakura-match"
WORKTREE_DIR="$HOME/SakuraSoft/worktrees"
AGENT_NAME=$1
TASK=$2

if [ -z "$AGENT_NAME" ]; then
    echo "Usage: spawn-agent.sh <agent-name> [task]"
    echo "Example: spawn-agent.sh research 'Analyze top match-3 games'"
    exit 1
fi

BRANCH_NAME="agent/${AGENT_NAME}"
WORKTREE_PATH="${WORKTREE_DIR}/sakura-match-${AGENT_NAME}"

# Create worktree if it doesn't exist
if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Creating worktree for ${AGENT_NAME}..."
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
