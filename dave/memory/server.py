"""MCP server "dave-memory" (stdio, JSON-RPC 2.0): Dave's long-term memory. Standard library only.

Run as:  python3 -I dave/memory/server.py   (config from dave/config.toml; DAVE_MEMORY_DIR etc. override)
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dave.memory import store as st  # noqa: E402

INSTRUCTIONS = (
    "Dave's long-term memory: player profiles, the playbook of solved answers, server facts and your own "
    "lessons, stored as files that outlive any conversation. Before working out a non-trivial answer, "
    "memory_recall it: a playbook hit means you have solved this before (say so, and check it is still right if "
    "it is stale). After a non-trivial answer, memory_save it to the playbook. Note durable facts about players "
    "with player_note. When a player corrects you, use memory_correct, never a silent edit. Every player may "
    "read, change or have you forget any memory (theirs or shared); pass asked_by on every change so the log "
    "shows who asked. Nothing is ever deleted; memory_forget archives."
)

KIND_ENUM = ["players", "playbook", "server", "lessons"]
ASKED_BY = {"type": "string", "description": "The player whose request this is (name or UUID from <player>). "
                                            "Logged so every change shows who asked for it."}

TOOLS = [
    {
        "name": "memory_recall",
        "description": (
            "Search your memories by keywords and return the best matches (id, kind, title, status, snippet). "
            "Call this first for any real question: a playbook hit is an answer you already worked out, a lesson "
            "is a mistake you should not repeat. Stale playbook entries (from an older pack version) are hidden "
            "unless include_stale is true; if you use one, re-check it with the tools before trusting it. "
            "Use memory_get to read a hit in full."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. 'nitrogen HV' or 'cleanroom setup'."},
                "kind": {"type": "string", "enum": KIND_ENUM, "description": "Only this kind of memory."},
                "player": {"type": "string", "description": "Only memories about or asked by this player (name or UUID)."},
                "k": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
                "include_stale": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_get",
        "description": "Read one memory in full by id (e.g. playbook/best-nitrogen-at-hv), with its status, "
                       "pack version, who asked and any corrections.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "memory_save",
        "description": (
            "Save a new memory. kind: playbook (a solved, non-trivial answer), server (a server-wide fact: rules, "
            "shared infrastructure, landmarks), lessons (a mistake or gotcha to avoid next time). Player facts go "
            "through player_note instead. For playbook, write the body as: 'Question: ...', 'Constraints: ...' "
            "(locks, bans, tier), 'Answer: ...' (the short version you gave), 'Chain: ...' (if any), 'Sources: ...' "
            "(which tool results it rests on). Pass player = who asked. Refuses a near-duplicate title and names "
            "the existing id: update that one instead, or pass supersedes=<id> if the new one replaces it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["playbook", "server", "lessons"]},
                "title": {"type": "string", "description": "Short and specific, e.g. 'Best nitrogen source at HV'."},
                "body": {"type": "string", "description": "Markdown body."},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "Lowercase keywords: items, tiers, machines. Tag 'pinned' on a server fact "
                                        "to have it shown on every turn."},
                "player": {"type": "string", "description": "Who asked or told you (name or UUID)."},
                "supersedes": {"type": "string", "description": "Id of an entry this one replaces."},
                "asked_by": ASKED_BY,
            },
            "required": ["kind", "title", "body"],
        },
    },
    {
        "name": "memory_update",
        "description": (
            "Change an existing memory (a new logged revision; the old version is kept). Any player may ask you "
            "to change any memory. Use it to refine an entry, add tags, or mark a stale playbook entry as re-checked with reverify=true after you "
            "confirmed it with the tools on the current pack. For a player telling you you were wrong, use "
            "memory_correct instead so the correction is credited."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "body": {"type": "string", "description": "Replaces the whole body."},
                "title": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Replaces the tags."},
                "status": {"type": "string", "enum": ["active", "stale"]},
                "reverify": {"type": "boolean", "description": "Stamp it with the current pack version."},
                "note": {"type": "string", "description": "Why, for the change log."},
                "asked_by": ASKED_BY,
            },
            "required": ["id"],
        },
    },
    {
        "name": "memory_correct",
        "description": (
            "Record that a player corrected a memory. The player's correction wins, and it is kept with who and "
            "when. For a playbook entry this writes a new corrected entry and marks the old one superseded; pass "
            "body with the corrected answer (otherwise the correction is appended to the old body). Other kinds "
            "are corrected in place. If the correction contradicts what the tools say, check before saving and "
            "tell the player what you found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "correction": {"type": "string", "description": "What the player said was wrong, in a sentence."},
                "by_player": {"type": "string", "description": "Name or UUID of the player who corrected it."},
                "body": {"type": "string", "description": "The full corrected body (recommended for playbook)."},
            },
            "required": ["id", "correction", "by_player"],
        },
    },
    {
        "name": "memory_forget",
        "description": "Archive a memory that is wrong, no longer useful, or that a player asked you to forget "
                       "(any player may ask). It stops appearing in recall; nothing is deleted, the owner can "
                       "restore it, and the reason and asker are logged.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "reason": {"type": "string"},
                                                         "asked_by": ASKED_BY},
                        "required": ["id", "reason"]},
    },
    {
        "name": "player_get",
        "description": "Read a player's profile by name or UUID: tier, base, setup, preferences, client-eval "
                       "opt-in, notes, each with the date you learned it. Any player may ask what you know about "
                       "them or anyone else.",
        "inputSchema": {"type": "object", "properties": {"player": {"type": "string"}}, "required": ["player"]},
    },
    {
        "name": "player_note",
        "description": (
            "Remember a durable fact about a player. field: tier (e.g. 'HV'; replaces the old value), base "
            "(where and what), setup (what they have built: cleanroom, EBF coils, AE system...), preferences "
            "(how they like answers, mods they avoid), client_eval (opt-in as they reported it), notes (anything "
            "else). Skip chit-chat and anything that will be untrue next week. Use the UUID from the <player> "
            "tag when the player has no profile yet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player": {"type": "string", "description": "UUID (preferred) or current name."},
                "fact": {"type": "string", "description": "One fact, e.g. 'has a cleanroom at spawn base'."},
                "field": {"type": "string", "enum": list(st.PLAYER_FIELDS), "default": "notes"},
                "name": {"type": "string", "description": "Player name, used when creating a new profile."},
                "asked_by": ASKED_BY,
            },
            "required": ["player", "fact"],
        },
    },
    {
        "name": "memory_list",
        "description": "List memories of one kind (id, status, title). By default lists active and stale ones; "
                       "pass status to see superseded or archived entries, or 'all'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": KIND_ENUM},
                "status": {"type": "string", "enum": ["active", "stale", "superseded", "archived", "all"]},
            },
            "required": ["kind"],
        },
    },
]


def log(msg):
    print("[dave-memory] " + msg, file=sys.stderr, flush=True)


def _hit_line(score, m):
    meta = m["meta"]
    who = meta.get("player_name") or meta.get("name") or ""
    extra = []
    if m["status"] != "active":
        extra.append(m["status"] + (" (pack %s)" % meta.get("pack") if m["status"] == "stale" else ""))
    if who and m["meta"].get("kind") != "players":
        extra.append("asked/told by " + who)
    if meta.get("corrections"):
        extra.append("%d correction(s)" % len(meta["corrections"]))
    return "%s  [%s] %s  score %.2f%s\n    %s" % (
        m["id"], meta.get("kind"), m["title"], score, ("  " + "; ".join(extra)) if extra else "",
        st.snippet(m["body"]))


class Service:
    def __init__(self, store):
        self.store = store

    def call(self, name, a):
        s = self.store
        if name == "memory_recall":
            q = (a.get("query") or "").strip()
            if not q:
                return "query is required", True
            hits = s.recall(q, a.get("kind"), a.get("player"), int(a.get("k") or 8), bool(a.get("include_stale")))
            if not hits:
                return "No memories match. (Stale entries hidden: %s.)" % ("no" if a.get("include_stale") else "yes"), False
            return "\n".join(_hit_line(sc, m) for sc, m in hits), False
        if name == "memory_get":
            meta, body, status = s.get(a.get("id") or "")
            head = "status: %s%s" % (status, "  (stale: saved on pack %s, current pack %s; re-check before relying "
                                     "on it)" % (meta.get("pack"), s.pack) if status == "stale" else "")
            return head + "\n" + st.render(meta, body), False
        if name == "memory_save":
            mem_id = s.save(a.get("kind"), a.get("title"), a.get("body"), a.get("tags"), a.get("player"),
                            a.get("supersedes"), asked_by=a.get("asked_by"))
            return "saved " + mem_id + (" (superseding %s)" % a["supersedes"] if a.get("supersedes") else ""), False
        if name == "memory_update":
            mem_id = s.update(a.get("id") or "", a.get("body"), a.get("title"), a.get("tags"), a.get("status"),
                              bool(a.get("reverify")), note=a.get("note"), asked_by=a.get("asked_by"))
            return "updated " + mem_id, False
        if name == "memory_correct":
            mem_id = s.correct(a.get("id") or "", a.get("correction"), a.get("by_player"), a.get("body"))
            if mem_id != a.get("id"):
                return "corrected: new entry %s supersedes %s" % (mem_id, a.get("id")), False
            return "corrected " + mem_id, False
        if name == "memory_forget":
            return "archived " + s.forget(a.get("id") or "", a.get("reason"), asked_by=a.get("asked_by")), False
        if name == "player_get":
            pid = s.find_player(a.get("player"))
            if not pid:
                return "No profile for %r yet." % a.get("player"), False
            meta, body, _ = s.get(pid)
            return st.render(meta, body), False
        if name == "player_note":
            pid, what = s.player_note(a.get("player"), a.get("fact"), a.get("field") or "notes", name=a.get("name"),
                                      asked_by=a.get("asked_by"))
            return "%s: %s" % (what, pid), False
        if name == "memory_list":
            rows = s.list(a.get("kind"), a.get("status"))
            if not rows:
                return "(none)", False
            return "\n".join("%s  %s  %s" % (m["id"], m["status"], m["title"]) for m in rows), False
        return "unknown tool: %s" % name, True


def handle(service, msg):
    """Returns the JSON-RPC response for one message, or None for notifications."""
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "dave-memory", "version": "1.0.0"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            text, is_error = service.call(params.get("name"), params.get("arguments") or {})
        except st.MemoryStoreError as e:
            text, is_error = str(e), True
        except Exception as e:
            log(traceback.format_exc())
            text, is_error = "error: %s" % e, True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    service = Service(st.open_store())
    log("memory at %s, pack %s" % (service.store.root, service.store.pack))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(service, msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
