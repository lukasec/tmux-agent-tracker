#!/usr/bin/env python3
"""Build restore-all.sh covering EVERY session ever captured — the union across the
whole git history, keeping each session's most-recent layout. Use this after a crash
when the live restore.sh only has a subset (e.g. you restarted tmux smaller and the
snapshot overwrote it). Writes ~/.tmux-agents/restore-all.sh.

Run:  python3 ~/.tmux-agents/recover-all.py
Then: bash ~/.tmux-agents/restore-all.sh
"""
import subprocess, json, sys, os
from pathlib import Path

DIR = Path(os.environ.get("TMUX_AGENTS_DIR", Path.home() / ".tmux-agents"))
sys.path.insert(0, str(DIR))
import snapshot  # reuse the same restore.sh generator


def git(*a):
    return subprocess.run(["git", "-C", str(DIR), *a], capture_output=True, text=True).stdout


seen = {}                                   # session name -> most-recent session object
for h in git("log", "--format=%H").split():  # newest first
    blob = git("show", f"{h}:state.json")
    if not blob.strip():
        continue
    try:
        d = json.loads(blob)
    except Exception:
        continue
    for s in d.get("sessions", []):
        seen.setdefault(s["name"], s)        # first seen wins = most recent

# Optional: drop scratch/numeric sessions you don't care about, e.g.
#   sessions = [s for n, s in seen.items() if not n.isdigit()]
sessions = sorted(seen.values(), key=lambda s: s["name"])

out = DIR / "restore-all.sh"
out.write_text(snapshot.restore_script({"sessions": sessions}))
os.chmod(out, 0o755)
print(f"wrote {out} covering {len(sessions)} sessions:")
for s in sessions:
    nag = sum(1 for w in s["windows"] for p in w["panes"]
              if p["agent"] and p["agent"].get("session_id"))
    print(f"  {s['name']:16} {nag} agents")
