# tmux-agent-tracker

Keep a live, crash-proof map of every **Claude Code / Codex** agent running in your
tmux sessions — so when the tmux server dies (and it does), **one command rebuilds
every session and resumes every agent** exactly where it left off.

> Born from a real problem: long-running tmux servers crash (e.g. the macOS copy-mode
> `grid_free_line` double-free), taking down a dozen named sessions with 20+ resumable
> agents. The transcripts survive on disk — but *which agent was in which named window*
> is gone, and rebuilding it by hand is a nightmare. This tool persists that map.

---

## What it records

For every pane running `claude` or `codex`, it writes to `~/.tmux-agents/state.json`:
the session name, window/pane, cwd, the running command, the **session id**, and a
ready-to-run **resume command** (`claude --resume <id>` / `codex resume <id>`). From
that it regenerates `~/.tmux-agents/restore.sh` — a script that recreates every
session/window/pane (with layout) and resumes every agent. Every change is
**git-committed**, so you also get full history.

```
~/.tmux-agents/
  state.json      # current map (machine-readable)
  restore.sh      # runnable: rebuild latest + resume agents
  .git/           # every change committed -> time-machine recovery
```

## How it works

Three triggers, **no periodic polling** — nothing runs while you're idle:

| trigger | catches | latency |
|---|---|---|
| **tmux hooks** | new / close / split pane·window·session | instant |
| **zsh `preexec`** | an agent launched by *typing* `claude`/`codex` (tmux has no event for that) | instant |
| **launchd `RunAtLoad`** | a baseline snapshot at login | once |

Plus a **self-limiting session-id backfill**: a session id only exists *after* the
agent's first prompt (Codex especially). When a pane has a running agent but no id
yet, a short loop re-checks on a fast ramp (2s, 2s, 3s…) and stops the moment the id
appears — hard-capped at 10 minutes, and never spawned for plain (non-agent) panes.

Two safety properties:
- **Crash guard** — an *empty* scan never overwrites `restore.sh`, so a snapshot taken
  while tmux is down can't wipe your recovery script.
- **tmux-only** — state is built purely from `tmux list-panes`, so an agent you run in
  a plain terminal (no tmux) never ends up in the db.

## Install (macOS)

Requires: macOS, `tmux`, `python3`, `zsh`, and a `claude` and/or `codex` on your PATH.

```bash
mkdir -p ~/.tmux-agents
cp snapshot.py view.py install.sh uninstall.sh preexec.zsh recover-all.py .gitignore ~/.tmux-agents/
# (optional) adapt the launchers — see "Adapting it" below
bash ~/.tmux-agents/install.sh
# open a NEW tmux pane (or `source ~/.zshrc`) so the zsh hook loads
```

`install.sh` is idempotent. It generates the launchd plist (with a PATH that can find
Homebrew's tmux), wires the tmux hooks + a rename-key wrap, and adds the zsh preexec.

## Adapting it

The **only** thing that's personal is *how you launch the agents*. Defaults assume the
plain `claude` / `codex` binaries, producing `claude --resume <id>` and
`codex resume <id>`. If you use shell wrappers/aliases, edit two functions in
`snapshot.py` (both have your-version examples in comments):

```python
def claude_launcher(cwd):     # return your Claude launcher, e.g. "cc"
    return "claude"

def codex_alias(home):        # return your Codex launcher, e.g. "cx"
    return "codex"            # (the original author maps CODEX_HOME -> cx/cxbu accounts)
```

Whatever you return must be a valid command in an interactive shell, because
`restore.sh` types it into the pane. That's it — everything else is generic.

## Recovering after a crash

```bash
bash ~/.tmux-agents/restore.sh        # rebuild the latest snapshot + resume agents
tmux attach -t <session>              # then attach
```

If the latest `restore.sh` is only a subset (you restarted tmux smaller and a snapshot
overwrote it), rebuild the **union of every session you've ever had**:

```bash
python3 ~/.tmux-agents/recover-all.py # writes restore-all.sh from full git history
bash    ~/.tmux-agents/restore-all.sh
```

Or time-travel to any past layout:

```bash
git -C ~/.tmux-agents log --oneline
git -C ~/.tmux-agents show <commit>:restore.sh | bash
```

## Live viewer

```bash
python3 ~/.tmux-agents/view.py        # refreshes ~1s; ctrl-c to quit
```
Green = agent + resolved id; yellow `⏳` = agent up, id pending (its first prompt
hasn't landed yet); grey = plain shell.

## Caveats

- **macOS-only** as written (launchd, `ps eww`, BSD `stat`). Linux would need systemd +
  GNU-`stat`/`ps` tweaks.
- It recovers the **map, not the transcripts** — those already persist
  (`~/.claude/projects`, `~/.codex*/sessions`). A resume id is a dead pointer without
  them, so a *total disk loss* is a Time-Machine problem, not this tool's.
- A **smaller** restart can shrink `restore.sh` (only *empty* scans are blocked) — use
  `recover-all.py` or git history for the full set.

## Uninstall

```bash
bash ~/.tmux-agents/uninstall.sh      # removes launchd/hooks/preexec; keeps state + history
```
