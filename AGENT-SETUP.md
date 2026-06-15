# Setting it up with a coding agent

Hand the prompt below to your coding agent (Claude Code, Codex, …) from inside this repo
(or give it the repo URL). It briefs the agent on what the tool is, the behaviors not to
"fix," and how to adapt it to **your** machine — your launchers, your Codex accounts, your
shell. The agent should still read the `README.md` and the actual code as ground truth.

---

```
You're setting up "tmux-agent-tracker" on my machine. It keeps a live, crash-proof map of
every Claude Code / Codex agent running in my tmux sessions, so if the tmux server crashes
I can rebuild every session and resume every agent with one command. Code + README are in
this repo. Read the README first, then install it and adapt it to MY setup.

STEP 1 — Prerequisites + discover my setup (inspect my dotfiles or ASK me; don't guess):
- OS: this is macOS-only (launchd, BSD `stat`, `ps eww`). If I'm on Linux, STOP and tell
  me it needs porting — do not install.
- On PATH: tmux, python3, zsh, and claude and/or codex.
- HOW I LAUNCH CLAUDE: plain `claude`, or a shell alias/function (e.g. `cc`)? Check
  ~/.zshrc / ~/.zshenv or ask. The resume command must be runnable in my interactive shell.
- HOW I LAUNCH CODEX: plain `codex`, or an alias (e.g. `cx`)? Do I run MULTIPLE Codex
  accounts via CODEX_HOME (e.g. ~/.codex-work)? If so, each account needs its own mapping.

STEP 2 — Behaviors to RESPECT (do not "fix" these — they're correct by design):
- CODEX IDS ARE DELAYED. A Codex session has NO session id until I send its FIRST message
  (it only writes its rollout file then). The tool's backfill loop re-checks until the id
  appears — fast at first, hard-capped at 10 minutes. Keep it. Don't treat the transient
  "waiting for session id" state as a bug. (Claude Code writes its id at startup, so it
  resolves instantly — the asymmetry is expected.)
- TYPED LAUNCHES NEED THE ZSH HOOK. tmux fires no event when I type claude/codex into a
  pane, so the tool hooks zsh `preexec`. After install I must open a NEW pane (or run
  `source ~/.zshrc`) for it to activate — remind me.
- IT'S EVENT-DRIVEN, NO POLLING. Don't add a cron/timer/watch loop "to be safe."
- RESUMED sessions read their id from argv (`--resume` / `resume <id>`) — leave that alone.

STEP 3 — Adapt the launchers (the ONLY real customization), in snapshot.py:
- `claude_launcher(cwd)` -> return my Claude launcher (default `claude`; e.g. `cc`).
- `codex_alias(home)`    -> return my Codex launcher (default `codex`; e.g. `cx`). For
  multi-account CODEX_HOME, map the home dir to the right alias — the commented example in
  the file shows the ~/.codex-<name> -> cx<name> pattern.
Resume lines are built as `<launcher> --resume <id>` (Claude) and `<launcher> resume <id>`
(Codex) and typed into the pane on restore, so they MUST be valid commands for me.

STEP 4 — Install (avoid the remote footgun):
- COPY the files into ~/.tmux-agents. Do NOT `git clone` this repo INTO ~/.tmux-agents —
  the tool auto-commits my private session names there, and if that dir is wired to a
  remote, a push would leak them. If you cloned, copy the files out, or run
  `git remote remove origin` inside ~/.tmux-agents.
      mkdir -p ~/.tmux-agents
      cp snapshot.py view.py install.sh uninstall.sh preexec.zsh recover-all.py .gitignore ~/.tmux-agents/
- After editing the launchers: bash ~/.tmux-agents/install.sh
- Tell me to open a NEW tmux pane (or `source ~/.zshrc`).

STEP 5 — Verify (you'll need ME to drive part of this):
- Start the viewer: python3 ~/.tmux-agents/view.py
- Have me open a Claude pane -> it should show GREEN (resolved id) within ~1s.
- Have me open a Codex pane and send a FIRST message -> it shows YELLOW "waiting for
  session id" until the message lands, then flips GREEN within a few seconds on its own,
  with no tmux action from me. If that hands-off flip works, the backfill is correct.
- Confirm ~/.tmux-agents/state.json and restore.sh are populated.

STEP 6 — Show me recovery (for later):
- `bash ~/.tmux-agents/restore.sh` rebuilds the latest snapshot + resumes agents.
- `python3 ~/.tmux-agents/recover-all.py` then `bash ~/.tmux-agents/restore-all.sh`
  rebuilds EVERY session ever captured (union across git history) — use if a small
  restart shrank restore.sh.
- `git -C ~/.tmux-agents log` + `git show <commit>:restore.sh | bash` is the time machine.

DON'T: push ~/.tmux-agents to any remote; add polling; treat delayed Codex ids as a bug;
assume Linux. If anything about my launchers or Codex accounts is unclear, ASK me.
```
