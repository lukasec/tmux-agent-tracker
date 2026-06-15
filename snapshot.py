#!/usr/bin/env python3
"""
tmux-agents snapshotter.

Scans every pane in the running tmux server, figures out which ones are running
Claude Code (`cc`/`ccbu`) or Codex (`cx`/`cxbu`/`cxbu2`), resolves each one's
session id, and writes:

  ~/.tmux-agents/state.json   machine-readable current state
  ~/.tmux-agents/restore.sh   runnable script that rebuilds everything

Intended to be run on a short launchd timer (~10s) so the map is always fresh
on disk and survives a tmux server crash. Read-only against tmux/agents.
"""
import json, os, re, shlex, subprocess, sys, glob, tempfile, time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DIR = Path(os.environ.get("TMUX_AGENTS_DIR", HOME / ".tmux-agents"))
STATE = DIR / "state.json"
RESTORE = DIR / "restore.sh"
# ── CUSTOMIZE: how YOU launch Claude Code / Codex (see README "Adapting it") ──
# Defaults assume the plain `claude` and `codex` binaries, so resume lines come
# out as `claude --resume <id>` / `codex resume <id>`. If you launch via shell
# wrappers/aliases, edit `claude_launcher` (below) and `codex_alias` (further down).
def claude_launcher(cwd):
    return "claude"
    # example — a wrapper `ccbu` (= cc + cd into a project dir) there, else `cc`:
    # return "ccbu" if cwd == str(HOME / "projects" / "myrepo") else "cc"
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'  # claude/codex session id


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


# ---- gather tmux structure -------------------------------------------------
def list_panes():
    fmt = "\t".join("#{%s}" % f for f in (
        "session_name", "window_index", "window_name",
        "pane_index", "pane_pid", "pane_tty", "pane_current_path", "pane_active"))
    out = tmux("list-panes", "-a", "-F", fmt).stdout
    panes = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) != 8:
            continue
        panes.append(dict(session=p[0], win=int(p[1]), win_name=p[2],
                          pane=int(p[3]), pid=int(p[4]), tty=p[5],
                          cwd=p[6], active=p[7] == "1"))
    return panes


def window_layouts():
    out = tmux("list-windows", "-a", "-F",
               "#{session_name}\t#{window_index}\t#{window_layout}").stdout
    lay = {}
    for line in out.splitlines():
        s, w, l = line.split("\t", 2)
        lay[(s, int(w))] = l
    return lay


# ---- process table (tty -> agent process) ----------------------------------
def proc_table():
    out = sh("ps", "-axo", "pid=,tty=,command=")
    procs = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        procs.append(dict(pid=int(m.group(1)), tty=m.group(2), cmd=m.group(3)))
    return procs


def start_epoch(pid):
    s = sh("ps", "-o", "lstart=", "-p", str(pid)).strip()
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return None


def agent_on_tty(tty, procs):
    short = tty.split("/")[-1]            # ttys019
    for p in procs:
        if p["tty"] != short:
            continue
        cmd = p["cmd"]
        if re.search(r"(^|/| )claude( |$)", cmd):
            return ("claude", p)
        if "/codex" in cmd or re.search(r"(^|/| )codex( |$)", cmd):
            return ("codex", p)
    return (None, None)


# ---- session-id resolution -------------------------------------------------
def claude_id(cwd, start, taken):
    d = HOME / ".claude" / "projects" / cwd.replace("/", "-")
    if not d.is_dir():
        return None
    cands = []
    for f in d.glob("*.jsonl"):
        try:
            b = f.stat().st_birthtime
        except Exception:
            b = f.stat().st_mtime
        cands.append((abs(b - start) if start else f.stat().st_mtime, f.stem))
    cands.sort()
    for _, sid in cands:
        if sid not in taken:                 # keep one-to-one across panes
            return sid
    return cands[0][1] if cands else None


CODEX_RE = re.compile(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-([0-9a-f-]{36})\.jsonl$")


def codex_home(pid):
    """Authoritative account selector: CODEX_HOME from the process env."""
    m = re.search(r"CODEX_HOME=(\S+)", sh("ps", "eww", "-p", str(pid)))
    return m.group(1) if m else None


def codex_alias(home):
    return "codex"
    # author's version — multi-account Codex via CODEX_HOME=~/.codex-<name>:
    # prof = "" if home.rstrip("/").endswith(".codex") else home.rstrip("/").split(".codex-")[-1]
    # return "cx" + prof


def codex_id(cwd, start, homes):
    best = None
    for home in homes:
        for f in glob.glob(home + "/sessions/**/rollout-*.jsonl", recursive=True):
            m = CODEX_RE.search(f)
            if not m:
                continue
            try:
                fe = datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").timestamp()
            except ValueError:
                continue
            if start and abs(fe - start) > 4:
                continue
            # confirm cwd appears in the session_meta (first line)
            try:
                with open(f, "r") as fh:
                    head = fh.readline()
                if ('"cwd":"%s"' % cwd) not in head and ('"cwd": "%s"' % cwd) not in head:
                    continue
            except OSError:
                continue
            best = (m.group(2), codex_alias(home))
    return best


# ---- build snapshot --------------------------------------------------------
def build():
    procs = proc_table()
    layouts = window_layouts()
    panes = list_panes()
    taken = set()

    sessions = {}
    for pane in sorted(panes, key=lambda x: (x["session"], x["win"], x["pane"])):
        kind, proc = agent_on_tty(pane["tty"], procs)
        agent = None
        if kind:
            start = start_epoch(proc["pid"])
            if kind == "claude":
                # resumed? the id is in argv (claude --resume/-r <id>) -> ground truth.
                m = re.search(r'(?:--resume|-r)[ =]+(' + UUID + ')', proc["cmd"])
                sid = m.group(1) if m else claude_id(pane["cwd"], start, taken)
                if sid:
                    taken.add(sid)
                alias = claude_launcher(pane["cwd"])
                resume = f"{alias} --resume {sid}" if sid else f"{alias}  # no session id yet"
                agent = dict(kind="claude", pid=proc["pid"], alias=alias,
                             session_id=sid, resume_cmd=resume,
                             command=proc["cmd"], cwd=pane["cwd"])
            else:
                home = codex_home(proc["pid"])               # authoritative account
                if home:
                    alias, homes = codex_alias(home), [home]
                else:                                          # env unreadable: fall back to disk
                    alias = "codex"
                    homes = glob.glob(str(HOME / ".codex")) + glob.glob(str(HOME / ".codex-*"))
                # resumed? the id is in argv (codex ... resume <id>) -> ground truth.
                m = re.search(r'\bresume[ =]+(' + UUID + ')', proc["cmd"])
                if m:
                    sid = m.group(1)
                else:
                    hit = codex_id(pane["cwd"], start, homes)
                    sid = hit[0] if hit else None
                    if hit and not home:                       # trust disk-derived alias only w/o env
                        alias = hit[1]
                resume = f"{alias} resume {sid}" if sid else f"{alias}  # no session id yet"
                agent = dict(kind="codex", pid=proc["pid"], alias=alias,
                             session_id=sid, resume_cmd=resume,
                             command=proc["cmd"], cwd=pane["cwd"], codex_home=home)

        s = sessions.setdefault(pane["session"], {"name": pane["session"], "windows": {}})
        w = s["windows"].setdefault(pane["win"], {
            "index": pane["win"], "name": pane["win_name"],
            "layout": layouts.get((pane["session"], pane["win"]), ""), "panes": []})
        w["panes"].append(dict(index=pane["pane"], cwd=pane["cwd"],
                               active=pane["active"], agent=agent))

    # flatten windows dict -> sorted list
    out = {"captured_at": None, "sessions": []}
    for s in sessions.values():
        s["windows"] = [s["windows"][k] for k in sorted(s["windows"])]
        out["sessions"].append(s)
    out["sessions"].sort(key=lambda x: x["name"])
    return out


# ---- restore.sh generator --------------------------------------------------
def tmux_name(n):
    # tmux rejects '.' and ':' in window/session names (they are target separators)
    return re.sub(r'[.:]', '-', n) or 'win'


def restore_script(state):
    L = ["#!/usr/bin/env bash",
         "# Auto-generated by tmux-agents. Rebuilds sessions + resumes agents.",
         "# Review before running. Existing sessions of the same name are skipped.",
         "set -uo pipefail", ""]
    for s in state["sessions"]:
        name = tmux_name(s["name"])
        q = shlex.quote(name)
        L.append(f'if tmux has-session -t ={q} 2>/dev/null; then')
        L.append(f'  echo "session {name} exists — skipping"')
        L.append("else")
        first = True
        for w in s["windows"]:
            wq = shlex.quote(tmux_name(w["name"]))
            base_cwd = shlex.quote(w["panes"][0]["cwd"])
            if first:
                L.append(f'  tmux new-session -d -s {q} -n {wq} -c {base_cwd}')
                first = False
            else:
                L.append(f'  tmux new-window -t {q}: -n {wq} -c {base_cwd}')
            tgt = f'{q}:{w["index"]}'
            for p in w["panes"][1:]:
                L.append(f'  tmux split-window -t {tgt} -c {shlex.quote(p["cwd"])}')
            if w["layout"]:
                L.append(f'  tmux select-layout -t {tgt} {shlex.quote(w["layout"])}')
            for p in w["panes"]:
                if p["agent"] and p["agent"]["session_id"]:
                    cmd = p["agent"]["resume_cmd"]
                    L.append(f'  tmux send-keys -t {tgt}.{p["index"]} {shlex.quote(cmd)} C-m')
        L.append("fi")
        L.append("")
    return "\n".join(L) + "\n"


# ---- atomic write + git history -------------------------------------------
def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def git_commit():
    if not (DIR / ".git").exists():
        sh("git", "-C", str(DIR), "init", "-q")
    sh("git", "-C", str(DIR), "add", "-A")
    # commit only if something changed
    changed = subprocess.run(["git", "-C", str(DIR), "diff", "--cached", "--quiet"]).returncode
    if changed:
        ts = sh("date", "+%Y-%m-%d %H:%M:%S").strip()
        sh("git", "-C", str(DIR), "commit", "-q", "-m", f"snapshot {ts}")


def count_agents(state):
    return sum(1 for s in state["sessions"] for w in s["windows"]
               for p in w["panes"] if p["agent"])


def pending_count(state):
    # A real claude/codex process is on the pane but its session id hasn't shown
    # up yet (first prompt not sent). A pure-terminal pane is agent=None, so it
    # is NEVER pending and never keeps the backfill alive.
    return sum(1 for s in state["sessions"] for w in s["windows"] for p in w["panes"]
               if p["agent"] and not p["agent"].get("session_id"))


def take_snapshot():
    DIR.mkdir(parents=True, exist_ok=True)
    state = build()
    state["captured_at"] = sh("date", "+%Y-%m-%dT%H:%M:%S%z").strip()
    state["agent_count"] = count_agents(state)
    state["pending_ids"] = pending_count(state)
    write_atomic(STATE, json.dumps(state, indent=2) + "\n")
    # Crash guard: an empty scan (tmux just crashed / not yet restored) must NOT
    # clobber the recovery script. restore.sh always reflects the last snapshot
    # that actually had agents; git history still holds every prior state.
    if state["agent_count"] > 0:
        write_atomic(RESTORE, restore_script(state))
        os.chmod(RESTORE, 0o755)
    if "--no-git" not in sys.argv:
        git_commit()
    return state


# ---- self-limiting session-id backfill ------------------------------------
LOCK = DIR / ".backfill.lock"
# Re-check schedule while a session id is pending. Snappy at first — you normally
# send the agent's first message within seconds — then backs off to stay cheap.
# Sums to ~10 min, after which we give up (an agent launched but never prompted).
BACKFILL_SCHEDULE = [2, 2, 3, 3, 5, 5, 5, 10, 10, 10] + [20] * 27


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock():
    """One backfill loop at a time. Returns True if we got it."""
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            pid = int(Path(LOCK).read_text() or "0")
        except Exception:
            pid = 0
        if pid and pid_alive(pid):
            return False                       # another loop is already running
        try:
            os.unlink(LOCK)                     # stale lock -> reclaim
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def backfill_loop():
    if not acquire_lock():
        return
    # SETTLE: an agent launched by *typing* (preexec --launch) is not up yet when we
    # start, so keep re-checking through the first few ticks even if nothing is
    # pending — that lets the just-started claude/codex process appear. After the
    # settle window, stop as soon as everything is resolved.
    SETTLE = 4
    # HARD CAP: this loop can never run longer than 10 minutes of wall-clock, no
    # matter what BACKFILL_SCHEDULE says. Guarantees "refiring always stops <= 10 min".
    MAX_SECONDS = 600
    deadline = time.monotonic() + MAX_SECONDS
    try:
        for i, iv in enumerate(BACKFILL_SCHEDULE):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return                          # 10-min wall-clock cap reached -> stop
            time.sleep(min(iv, remaining))
            if pending_count(take_snapshot()) == 0 and i >= SETTLE:
                return                          # settled + every id resolved -> stop
        # Cap hit: an agent was launched but never prompted. Give up quietly; the
        # pane is already recorded (id null), and any later hook/launch restarts it.
    finally:
        try:
            os.unlink(LOCK)
        except OSError:
            pass


def spawn_backfill():
    args = [sys.executable, os.path.abspath(__file__), "--backfill-loop"]
    if "--no-git" in sys.argv:
        args.append("--no-git")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)    # detached: survives the hook/parent


def main():
    if "--backfill-loop" in sys.argv:
        backfill_loop()
        return
    state = take_snapshot()
    # --launch (fired by the zsh preexec hook the instant you type an agent command)
    # forces a backfill even though the process isn't up yet — the loop's settle
    # phase catches it. Otherwise only chase when an agent is already pending an id.
    # Pure-terminal panes are agent=None -> pending 0 -> nothing spawned.
    launch = "--launch" in sys.argv
    if (launch or pending_count(state) > 0) and "--no-backfill" not in sys.argv:
        spawn_backfill()
    if "--print" in sys.argv:
        for s in state["sessions"]:
            print(f'session {s["name"]}:')
            for w in s["windows"]:
                for p in w["panes"]:
                    a = p["agent"]
                    tag = a["resume_cmd"] if a else "(shell)"
                    print(f'  {s["name"]}:{w["index"]}.{p["index"]}  {tag}')


if __name__ == "__main__":
    main()
