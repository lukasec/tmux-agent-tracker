#!/usr/bin/env python3
"""Live viewer for the tmux-agents db. Reads state.json (~1s) and renders the
current pane->session-id map. Display-only; it never writes. Ctrl-C to exit."""
import json, time
from pathlib import Path

STATE = Path.home() / ".tmux-agents" / "state.json"
B, D, R = "\033[1m", "\033[2m", "\033[0m"
G, Y, C, RED = "\033[32m", "\033[33m", "\033[36m", "\033[31m"
CLEAR = "\033[2J\033[H"


def render():
    try:
        st = json.loads(STATE.read_text())
        age = int(time.time() - STATE.stat().st_mtime)
    except Exception:
        return "waiting for state.json …"
    fresh = G if age < 3 else D
    out = [
        f"{B}tmux-agents · live{R}    {fresh}updated {age}s ago{R}    {D}{st.get('captured_at','?')}{R}",
        f"{D}agents={st.get('agent_count',0)}   pending={st.get('pending_ids',0)}{R}",
        "",
    ]
    for s in st.get("sessions", []):
        out.append(f"{B}{C}▍ session  {s['name']}{R}")
        for w in s["windows"]:
            out.append(f"  {D}└ window {w['index']}  ({w['name']}){R}")
            for p in w["panes"]:
                addr = f"{s['name']}:{w['index']}.{p['index']}"
                a = p["agent"]
                if not a:
                    out.append(f"     {D}{addr}   (shell)   {p['cwd']}{R}")
                elif a.get("session_id"):
                    out.append(f"     {addr}   {G}{a['resume_cmd']}{R}")
                else:
                    out.append(f"     {addr}   {Y}{a['alias']}  ⏳ waiting for session id…{R}")
        out.append("")
    out.append(f"{D}try:  M-c claude · M-x codex · M-T new shell window · M-t split · "
               f"M-w kill pane · M-s rename session · M-q kill session{R}")
    out.append(f"{D}ctrl-c to exit{R}")
    return "\n".join(out)


def main():
    try:
        while True:
            print(CLEAR + render(), end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
