"""Live gym: asks the production Dave a fixed set of questions over RCON and checks that each feature was really used.

    python3 -I dave/deploy/gym.py [--host game-host.example.net] [--only NAME,...] [--out report.json]

How it works (no player needs to be online):
- Each case is sent with DaveBridge's console hook `/dave ask <asName> [@x,y,z,dim] <question>` through `rcon-cli` in
  the game container, so Dave sees an ordinary triggered chat line from that name.
- World changes wait for a confirm; the gym watches `/dave pending` and confirms from the console (`/dave confirm`).
- Dave's answer comes from his turn log (/dave/data/logs/turns.jsonl). Which tools he called comes from his Claude
  session transcript (/dave/home/projects/*/<session>.jsonl): a case passes only if one of its expected tools ran.
- Real model calls on the owner's subscription: a full run is roughly 20 turns, one of them the Opus recipe-planner.

Reads nothing secret and prints no tokens. Exit code 0 when every case passed.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
import time

GAME, DAVE = "gtnh-gtnh_2-1", "gtnh-dave-1"
AS = "DaveGym"
# 40 blocks above spawn (spawn chunks are always loaded); filled in from the world at start.
SKY = None

CASES = [
    # name, question, expected tools (any one of them, matched as substrings of the tool name), options
    ("search+quest", "which quest introduces the Electric Blast Furnace? link it", ["gtnh_search"], {}),
    ("recipe-db", "exactly how are NAND chips made: machine, inputs, EU/t and time?", ["recipe_producers", "recipe_get", "item_find"], {}),
    ("recipe-uses", "what are NAND chips used in? just the top few", ["recipe_uses"], {}),
    ("live-gt-recipe", "check the live game's own recipe map: what does the laser engraver need to make a NAND wafer?", ["query_run", "eval"], {}),
    ("eval-read", "use the live server: how many entities are loaded in the overworld right now?", ["eval", "query_run"], {}),
    ("describe", "what block is directly below me? check the live world", ["describe", "eval"], {}),
    ("world-lookup", "where is the nearest chest to me? give me a waypoint", ["query_run", "eval"], {"want": "{waypoint:"}),
    ("eval-write", "place one glass block at {sky}, nothing else", ["eval"], {"confirm": True}),
    ("eval-write-undo", "now remove that glass block at {sky} (set it back to air)", ["eval"], {"confirm": True}),
    ("query-save", "write a small script that counts loaded tile entities in the overworld and save it as a new saved "
     "query named {qname}", ["query_save"], {}),
    ("query-list", "check your saved query library right now and list every name in it", ["query_list"],
     {"want": "{qname}"}),
    ("planner", "I'm at HV: what's the best source of nitrogen? plan the chain", ["Agent", "Task", "plan_chain"], {}),
    # A target Dave hasn't planned before (he rightly reuses an earlier plan for a repeated question).
    ("recipe-planner", "design me an HV factory for {rate} aluminium ingots per minute: compare at least two "
     "routes with machine counts and power", ["Agent", "Task"], {"followup": True}),
    ("memory-save", "remember that my main base is at 1200 70 -800 and I'm at HV", ["player_note", "memory_save"], {}),
    # The asker's profile is already in the turn envelope, so answering from it without a tool is right.
    ("memory-recall", "what do you remember about me?", [], {"want_any": ["1200"]}),
    ("memory-forget", "forget my base location please", ["player_note", "memory_forget", "memory_update", "memory_correct"], {}),
    ("wiki-read", "what does our server wiki say about the Vacuum Freezer? one line", ["wiki_get", "wiki_search_titles"], {}),
    ("lesson-fallback", "try your guided demo tool: show me in the world where an EBF controller goes. If it fails, "
     "tell me why", ["lesson"], {}),
    ("client-eval-gate", "check my client's render distance setting on my own computer", [], {"want_any": ["opt", "client", "online"]}),
    ("whisper", "whisper me the answer: what voltage is HV?", [], {"directive": "whisper"}),
    ("players", "who is online right now?", ["list_players", "eval"], {}),
]


class Live:
    def __init__(self, host):
        self.host = host

    def ssh(self, cmd, timeout=120):
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", self.host, cmd], capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout

    def rcon(self, *args):
        return self.ssh("sudo docker exec %s rcon-cli %s" % (GAME, " ".join(shlex.quote(a) for a in args)))

    def turns(self):
        out = self.ssh("sudo docker exec %s cat /dave/data/logs/turns.jsonl" % DAVE)
        return [json.loads(l) for l in out.splitlines() if l.strip()]

    def tool_uses(self, session):
        """Every tool_use name in the session transcript, in order."""
        if not session:
            return []
        out = self.ssh("sudo docker exec %s sh -c %s" % (
            DAVE, shlex.quote("cat /dave/home/projects/*/%s.jsonl 2>/dev/null" % session)), timeout=180)
        names = []
        for line in out.splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            content = (m.get("message") or {}).get("content")
            if isinstance(content, list):
                names += [c.get("name", "") for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        return names

    def pending_ids(self):
        """Tokens of the gym's changes waiting for a confirm. `/dave pending` lines read
        "<token>  <player>  <n> s left  <summary>"; rcon-cli may run them together on one line."""
        return re.findall(r"(\S+)\s+" + AS + r"\s+\d+ s left", self.rcon("dave", "pending"))


def spawn(live, volume="/var/lib/docker/volumes/gtnh_gtnh_2_mc-data/_data", world="World"):
    """World spawn (SpawnX/Y/Z) from level.dat: gzip NBT, where each is a TAG_Int (type 3, name, big-endian int)."""
    import base64, gzip, struct
    raw = base64.b64decode(live.ssh("sudo base64 -w0 %s/%s/level.dat" % (volume, world)))
    nbt = gzip.decompress(raw)
    out = []
    for name in (b"SpawnX", b"SpawnY", b"SpawnZ"):
        i = nbt.find(b"\x03" + struct.pack(">H", len(name)) + name)
        if i < 0:
            raise SystemExit("no %s in level.dat" % name.decode())
        out.append(struct.unpack(">i", nbt[i + 3 + len(name):i + 7 + len(name)])[0])
    return tuple(out)


def run_case(live, name, question, tools, opts, pos, sky, qname):
    q = question.format(sky="%d %d %d" % sky, qname=qname, rate=int(time.time()) % 50 + 10)
    opts = {k: (v.replace("{qname}", qname) if isinstance(v, str) else v) for k, v in opts.items()}
    before = live.turns()
    n = len(before)
    # Tool calls already in the current session's transcript, so only this question's calls are counted.
    session = before[-1].get("session") if before else None
    base = len(live.tool_uses(session))
    live.rcon("dave", "ask", AS, "@%d,%d,%d,0" % pos, q)
    confirmed, deadline = [], time.time() + 900
    turn = None
    while time.time() < deadline:
        time.sleep(4)
        if opts.get("confirm"):
            for pid in live.pending_ids():
                if pid not in confirmed:
                    live.rcon("dave", "confirm", pid)
                    confirmed.append(pid)
        # This question's own row; a late row (a background planner's follow-up) belongs to an earlier turn.
        new = [t for t in live.turns()[n:] if t.get("player") == AS and not t.get("late")
               and (t.get("prompt") or "").strip() == q.strip()]
        if new:
            turn = new[-1]
            break
    if not turn:
        return {"case": name, "ok": False, "why": "no answer within 15 minutes"}
    used = live.tool_uses(turn.get("session"))
    this = used[base:] if turn.get("session") == session else used
    followup = None
    if any(u in ("Agent", "Task") for u in this):
        # A delegated recipe-planner may run in the background and answer later as a "late" row of the same turn.
        wait_until = min(deadline, time.time() + 600)
        while time.time() < wait_until and not followup:
            late = [t for t in live.turns()[n:] if t.get("turn") == turn.get("turn") and t.get("late")]
            followup = late[-1] if late else None
            if not followup:
                time.sleep(5)
    reply = turn.get("reply") or ""
    if followup:
        reply += "\n[follow-up] " + (followup.get("reply") or "")
    problems = []
    if tools and not any(any(t in u for t in tools) for u in this):
        problems.append("expected one of %s, used %s" % (tools, sorted(set(this)) or "no tools"))
    if opts.get("followup") and not followup and re.search(r"report|post|back", reply, re.I):
        problems.append("the delegated planner never posted its follow-up")
    if opts.get("confirm") and not confirmed:
        problems.append("no confirm was requested")
    if opts.get("want") and opts["want"] not in reply:
        problems.append("reply lacks %s" % opts["want"])
    if opts.get("want_any") and not any(w in reply.lower() for w in opts["want_any"]):
        problems.append("reply mentions none of %s" % opts["want_any"])
    if opts.get("directive") and turn.get("directive") != opts["directive"]:
        problems.append("directive %s, wanted %s" % (turn.get("directive"), opts["directive"]))
    bad = [w for w in (turn.get("warnings") or []) if "offline" not in w and "0 recipients" not in w]
    return {"case": name, "ok": not problems, "why": "; ".join(problems), "tools": sorted(set(this)),
            "confirmed": confirmed, "seconds": turn.get("seconds"), "cost": turn.get("cost_usd"),
            "directive": turn.get("directive"), "warnings": bad, "reply": reply}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="game-host.example.net")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    live = Live(a.host)
    pos = spawn(live)
    sky = (pos[0], min(pos[1] + 40, 250), pos[2])
    qname = time.strftime("gym-tiles-%m%d%H%M")
    only = set(filter(None, a.only.split(",")))
    results = []
    for name, q, tools, opts in CASES:
        if only and name not in only:
            continue
        r = run_case(live, name, q, tools, opts, pos, sky, qname)
        results.append(r)
        print("%-18s %s  %5ss  $%-7s %s" % (name, "PASS" if r["ok"] else "FAIL", r.get("seconds"),
                                            r.get("cost"), r["why"] or ", ".join(r.get("tools") or [])), flush=True)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"position": pos, "sky": sky, "results": results}, f, indent=1)
    print("%d/%d passed" % (sum(r["ok"] for r in results), len(results)))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
