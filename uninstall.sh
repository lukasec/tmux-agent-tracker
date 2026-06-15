#!/usr/bin/env bash
# Remove launchd job + tmux hooks/rename-wrap + zsh preexec. Keeps state.json/restore.sh/git.
set -uo pipefail
LABEL="com.$(id -un).tmux-agents"
DIR="$HOME/.tmux-agents"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "launchd: removed"

# drop the source lines from ~/.tmux.conf and ~/.zshrc
for f in "$HOME/.tmux.conf" "$HOME/.zshrc"; do
  if [ -f "$f" ]; then
    /usr/bin/sed -i '' '/tmux-agents/d' "$f"
    echo "removed tmux-agents lines from $f"
  fi
done

# unset hooks live, then reload original config so the original M-s returns
for ev in session-created session-closed after-new-window window-unlinked \
          after-split-window after-kill-pane client-session-changed; do
  tmux set-hook -gu "$ev" 2>/dev/null || true
done
tmux source-file "$HOME/.tmux.conf" 2>/dev/null || true
rm -f "$DIR/tmux-agents.tmux" "$DIR/.backfill.lock"
echo "done. (state.json / restore.sh / git history kept)"
