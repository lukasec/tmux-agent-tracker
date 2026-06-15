# tmux-agents — snapshot when an agent is launched by TYPING it into a shell.
# tmux fires no event for typed commands, so we hook zsh's preexec. The snapshot's
# backfill then catches claude's id immediately and codex's after the first message.
_tmux_agents_preexec() {
  [ -n "$TMUX" ] || return        # only track agents launched INSIDE tmux
  case "${1%% *}" in
    claude|codex)                   # add your own launchers, e.g.  cc|ccbu|cx|cxbu)
      ( /usr/bin/python3 "$HOME/.tmux-agents/snapshot.py" --launch >/dev/null 2>&1 & ) ;;
  esac
}
if [ -n "$ZSH_VERSION" ]; then
  autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook preexec _tmux_agents_preexec
fi
