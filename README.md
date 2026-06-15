# tmux-agent-tracker

Keep a live, crash-proof map of every **Claude Code / Codex** agent running in your
tmux sessions — so when the tmux server dies (and it does), **one command rebuilds
every session and resumes every agent** exactly where it left off.

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

## tmux keybindings & where the hooks fire

`install.sh` installs **only** the snapshot triggers — it does **not** add any spawn or
navigation keybindings; those are yours to define. It doesn't need to touch them either:
the hooks fire on the tmux **event**, so it makes no difference whether you trigger that
event with a keybinding, the mouse, or a `tmux` command on the CLI.

What the tool installs:
- the 7 global `set-hook`s listed below, each running a snapshot in the background;
- a wrap on the **rename-session** key (`M-s` by default) — tmux fires no rename hook, so
  the key itself snapshots after renaming. Rebind it in `tmux-agents.tmux` if you use a
  different key for rename.

If you launch agents via keybindings, here's how a typical set lines up with the hooks
(`M` = Option/Alt). These bindings are **optional examples** — adapt freely:

| key | does | event → snapshot |
|---|---|---|
| `M-c` / `M-x` | new claude / codex pane (`split-window`) | `after-split-window` ✓ |
| `M-T` | new window (`new-window`) | `after-new-window` ✓ |
| `M-w` | kill pane (`kill-pane`) | `after-kill-pane` ✓ |
| `M-m` | new session | `session-created` ✓ |
| `M-q` | kill session | `session-closed` ✓ |
| `M-s` | rename session | wrapped by the tool ✓ |
| `M-o` / `M-Tab` | switch session / window | `client-session-changed` ✓ (on session switch) |
| `M-hjkl` | move between panes | — (nothing changed to track) |
| *type `claude` / `codex` in a pane* | launch an agent by hand | caught by the **zsh `preexec`** hook, not tmux |

That last row is the point of the `preexec` hook: typing a launch fires no tmux event at
all, so without it a hand-started agent wouldn't be recorded until your next tmux action.

<details><summary>Optional starter keybindings — paste into <code>~/.tmux.conf</code></summary>

```tmux
# M = Option/Alt. Agents launched here are picked up by the after-split/new-window hooks.
bind -n M-c split-window -h -c "#{pane_current_path}" 'claude' \; select-layout tiled
bind -n M-x split-window -h -c "#{pane_current_path}" 'codex'  \; select-layout tiled
bind -n M-t split-window -h -c "#{pane_current_path}" \; select-layout tiled
bind -n M-T new-window   -c "#{pane_current_path}"
bind -n M-w kill-pane
bind -n M-m command-prompt -p "new session:" { new-session -d -s "%%" }
bind -n M-q confirm-before -p "kill session? (y/n)" kill-session
bind -n M-h select-pane -L
bind -n M-l select-pane -R
bind -n M-k select-pane -U
bind -n M-j select-pane -D
bind -n M-o choose-tree -s
# (M-s "rename session" is added by install.sh)
```
</details>

## Install (macOS)

> **Prefer your coding agent to do it?** Hand it **[`AGENT-SETUP.md`](AGENT-SETUP.md)** — a
> ready-to-paste prompt that discovers your setup (launchers, multi-account Codex), installs,
> and verifies, while respecting the gotchas (e.g. Codex ids only appear after the first
> message). Manual steps follow.

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
