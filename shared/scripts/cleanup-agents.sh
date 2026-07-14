#!/bin/bash
# Clean up all agent worktrees

PROJECT_DIR="$HOME/SakuraSoft/projects/sakura-match"

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
