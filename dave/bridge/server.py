"""MCP server "bridge" (stdio, JSON-RPC 2.0): Dave's hands in the live game. Standard library only.

Run as:  python3 -I dave/bridge/server.py   (Claude starts it from launch/mcp.json)

Every tool call is forwarded to the Dave daemon over its unix socket (DAVE_BRIDGE_SOCKET, `<run>/bridge.sock`; see
dave/daemon/rpc.py), which holds the one WebSocket to DaveBridge (DaveBridge/PROTOCOL.md section 1.8). Without a
running daemon (a --probe or --smoke launch) every tool answers that the game is not reachable.
"""

import json
import os
import socket
import sys
import threading
import traceback

PROTOCOL = "2025-06-18"

INSTRUCTIONS = (
    "Live access to the GT New Horizons server you serve: run Groovy inside the server JVM (eval), inspect what a "
    "player looks at or holds (describe), and run saved queries (query_run). Use eval to compute exact facts the "
    "other tools can't confirm: recipe inputs, EU/t and duration straight from GregTech's recipe maps, what a "
    "machine or chest holds, where things are. Read pack source in gtnh-src/ first to find the right classes and "
    "fields, then script against them. Prefer a saved query when one fits (query_list); save a script that worked "
    "and will be asked again (query_save). Anything that changes the world must be mode=write with a summary: the "
    "asking player confirms it in chat before it runs."
)

SCRIPT_HELP = (
    "Groovy, run on the server thread. The last expression is the result (returned as JSON, capped). Variables: "
    "server, player (the asker, or null), asker, world, params, out (println), log, and dave: dave.fields(obj), "
    "dave.methods(obj, 'filter'), dave.get(obj, 'name'), dave.call(obj, 'name', args...), dave.cls('a.b.C'), "
    "dave.players(), dave.player(name), dave.world(dim), dave.te(dim,x,y,z), dave.tiles(world), dave.item(stack), "
    "dave.fluid(fs), dave.markupId(stack), dave.waypoint(x,y,z,dim,label), dave.describe(stack). MCP names work "
    "(player.inventory, entity.getHealth()). Never loads chunks unless you do. Keep it fast: it holds the tick."
)

TOOLS = [
    {
        "name": "eval",
        "description": (
            "Run a Groovy script in the live game. " + SCRIPT_HELP + " mode=read (default) for looking things up. "
            "mode=write for anything that changes the world, inventories or entities: give summary (one line the "
            "player sees, saying exactly what will change); the call then waits until the asking player clicks "
            "Confirm or Cancel in chat. side=client runs on the asker's own client instead (only if they opted in: "
            "clientEval=\"true\" in their turn; variables mc, player, world, dave.tooltip(stack)). Errors come back "
            "with errorType (compile, blocked, needs_confirm, timeout, exception), the message and the script line."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "mode": {"type": "string", "enum": ["read", "write"], "default": "read"},
                "summary": {"type": "string", "description": "write only: what will change, for the confirm."},
                "params": {"type": "object", "description": "Bound as `params` (numbers arrive as doubles)."},
                "timeout_ms": {"type": "integer", "description": "Default 500, at most 5000 on the server."},
                "side": {"type": "string", "enum": ["server", "client"], "default": "server"},
                "player": {"type": "string", "description": "Override the player; defaults to the asker."},
            },
            "required": ["script"],
        },
    },
    {
        "name": "describe",
        "description": (
            "What a block, tile entity, item or entity is at runtime: registry id and meta, class, display name, "
            "GregTech MetaTileEntity id, name, recipe map, owner and description lines, inventory contents. target: "
            "looking (what the asker looks at), held (the asker's held item), player, block (x, y, z, dim) or "
            "entity (entity_id, dim). Tooltips are client-side; use eval side=client for those."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["looking", "held", "player", "block", "entity"],
                           "default": "looking"},
                "x": {"type": "integer"}, "y": {"type": "integer"}, "z": {"type": "integer"},
                "dim": {"type": "integer"}, "entity_id": {"type": "integer"},
                "player": {"type": "string", "description": "Defaults to the asker."},
            },
        },
    },
    {
        "name": "query_run",
        "description": (
            "Run a saved query by name with params (see query_list). The starter set answers world lookups with "
            "{waypoint:} links (where is my machine, which chest or AE network holds an item, nearest ore vein, "
            "structures) and live GregTech recipe lookups (gt-recipes: producers or uses of an item with inputs, "
            "outputs, EU/t, duration, cleanroom and other special values, straight from the server's recipe maps)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "params": {"type": "object"},
                "summary": {"type": "string", "description": "For write queries: what will change."},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "query_list",
        "description": "The saved queries: name, what each answers, its params, mode and side.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_get",
        "description": "One saved query in full, script included (to adapt it into a new eval).",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "query_save",
        "description": (
            "Save a script that worked as a named query, so it can be rerun with query_run. Use params for the "
            "parts that change between asks (an item id, a radius) and document each in params_doc. Names: "
            "lowercase, digits, - and _. replace=true overwrites your own saved query of that name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string", "description": "What question it answers."},
                "script": {"type": "string"},
                "mode": {"type": "string", "enum": ["read", "write"], "default": "read"},
                "side": {"type": "string", "enum": ["server", "client"], "default": "server"},
                "params_doc": {"type": "object", "description": "{param: 'type, required. meaning'}"},
                "timeout_ms": {"type": "integer"},
                "replace": {"type": "boolean", "default": False},
            },
            "required": ["name", "description", "script"],
        },
    },
    {
        "name": "say",
        "description": (
            "Post a chat line now, mid-turn (progress on a long job: \"Scanning loaded chunks...\"). Your normal "
            "answer is the turn's final text, not this tool. markup is Dave markup; target @a (default) or a "
            "player name (whisper)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"markup": {"type": "string"}, "target": {"type": "string", "default": "@a"}},
            "required": ["markup"],
        },
    },
    {
        "name": "lesson",
        "description": (
            "Show the player a guided demonstration in their own world (\"show me\"): a ghost Dave only they can "
            "see walks the steps, points, holds items and shows ghost blocks with labels, looping until they stop "
            "it. Data only, no code, so it needs no client-eval opt-in, but it needs the DaveBridge client mod: on "
            "error no_client_mod, answer in chat instead. Inspect the world first (describe/eval) so positions are "
            "real. lesson = {\"title\"?, \"loop\"?: true, \"speed\"?: 0.6, \"steps\": [...]}; each step is one "
            "of {\"walkTo\":[x,y,z]}, {\"lookAt\":[x,y,z]}, {\"hold\":\"modid:name[:meta]\"}, "
            "{\"highlight\":{\"pos\":[x,y,z],\"color\"?:\"gold\",\"label\"?:\"text\"}}, "
            "{\"ghost\":{\"pos\":[x,y,z],\"block\":\"modid:name\",\"meta\"?:0,\"facing\"?:\"north\"}}, "
            "{\"swing\":true}, {\"say\":\"step text\"}, {\"wait\":ticks}. Limits: positions within 32 blocks "
            "of the player and in loaded chunks, at most 64 steps and 180 s per pass; unknown items or blocks are "
            "dropped. Read the ack's warnings. The player defaults to the asker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"player": {"type": "string"}, "lesson": {"type": "object"}},
            "required": ["lesson"],
        },
    },
    {
        "name": "lesson_stop",
        "description": "Stop the player's guided demonstration (the asker by default; id = only that lesson).",
        "inputSchema": {"type": "object", "properties": {"player": {"type": "string"}, "id": {"type": "string"}}},
    },
    {
        "name": "list_players",
        "description": "Who is online: name, UUID, dimension, position, whether they have the client mod.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

OPS = {"eval": "eval", "describe": "describe", "query_run": "query_run", "query_list": "query_list",
       "query_get": "query_get", "query_save": "query_save", "say": "say", "list_players": "list_players",
       "lesson": "lesson", "lesson_stop": "lesson_stop"}


def log(msg):
    sys.stderr.write("[bridge-mcp] %s\n" % msg)
    sys.stderr.flush()


class Daemon:
    """One request per connection to the daemon's unix socket."""

    def __init__(self, path):
        self.path = path
        self.next_id = 0
        self.lock = threading.Lock()

    def call(self, op, args, timeout=900):
        if not self.path or not os.path.exists(self.path):
            raise ConnectionError("the game is not reachable right now (the Dave daemon's bridge socket is missing)")
        with self.lock:
            self.next_id += 1
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(self.path)
            s.sendall((json.dumps({"id": self.next_id, "op": op, "args": args}) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            s.close()
        if not buf:
            raise ConnectionError("the Dave daemon closed the connection without an answer")
        return json.loads(buf)


def format_result(op, result):
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    is_error = isinstance(result, dict) and result.get("ok") is False
    return text, is_error


def handle(daemon, msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", PROTOCOL), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "bridge", "version": "1.0.0"}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            if name not in OPS:
                raise ValueError("unknown tool: %s" % name)
            reply = daemon.call(OPS[name], args)
            if reply.get("ok"):
                text, is_error = format_result(name, reply.get("result"))
            else:
                text, is_error = reply.get("error") or "failed", True
        except (ConnectionError, OSError, socket.timeout) as e:
            text, is_error = str(e), True
        except Exception as e:                      # noqa: BLE001
            log(traceback.format_exc())
            text, is_error = "error: %s" % e, True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    daemon = Daemon(os.environ.get("DAVE_BRIDGE_SOCKET"))
    log("daemon socket %s" % daemon.path)
    out_lock = threading.Lock()

    def answer(msg):
        reply = handle(daemon, msg)
        if reply is not None:
            with out_lock:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("method") == "tools/call":
            # A write waits for a player's click: other calls must not queue behind it.
            threading.Thread(target=answer, args=(msg,), daemon=True).start()
        else:
            answer(msg)


if __name__ == "__main__":
    main()
