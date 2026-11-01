"""MCP server (stdio, JSON-RPC 2.0) giving Dave semantic search over GT New Horizons knowledge. Standard library plus numpy.

  python3 -I tools/gtnh-search/server.py [--profile prose] [--readonly]
"""

import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semsearch as s  # noqa: E402

REFRESH_AFTER = 600
# gtnh_reindex waits this long for its refresh, then reports that it continues in the background.
REINDEX_WAIT = 120
# Tool calls run on workers, so a slow search or reindex never blocks pings, status or other searches.
CALL_WORKERS = 4

INSTRUCTIONS = (
    "Semantic search over GT New Horizons 2.9 knowledge: the quest book (one hit per quest, with its quest line, "
    "tasks, rewards and prerequisites), GuideNH guide pages (machines, multiblocks, power, AE2, Thaumcraft), the "
    "en_US.lang player text of every mod (item and machine names, tooltips, structure hints), the offline GTNH wiki "
    "when it has been mirrored, and your own saved answers (playbook) and server notes (memory). Use gtnh_search "
    "first to turn a player's loose wording ('liquid air', 'N2', 'that blue circuit') into real item names and IDs, "
    "and to find written advice: which quest covers a machine, what a multiblock needs, how a mechanic works. "
    "Search resolves names and finds prose; it never decides which recipes exist. Exact recipe facts (inputs, "
    "outputs, EU/t, duration, tier, cleanroom, coil heat) come from the recipe tools, and the best chain from the "
    "planner: pass them the item IDs a hit gives you. Quests and guides can lag behind the pack, so check numbers "
    "against the recipe tools before you quote them. Check the playbook for an earlier answer before solving from "
    "scratch."
)

KIND_ENUM = ["any"] + list(s.KINDS)

TOOLS = [
    {
        "name": "gtnh_search",
        "description": (
            "Search GTNH knowledge by meaning. Returns the best-matching passages, each with its kind, title, source, "
            "score, IDs (quest_id, item_ids, guide page) and a snippet. Phrase the query as the player would, e.g. "
            "'best nitrogen source at HV', 'what is a cleanroom for', 'which quest unlocks the EBF'. Use it to "
            "resolve names and find advice, not to decide what recipes exist: take item IDs from the hits to the "
            "recipe tools for exact facts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What you are looking for, in natural language."},
                "k": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8, "description": "Number of hits."},
                "kind": {"type": "string", "enum": KIND_ENUM, "default": "any",
                         "description": "Restrict to one source: quest (quest book), guide (GuideNH pages), wiki, "
                                        "item (item cards), lang (item names and tooltips), playbook (saved answers), "
                                        "memory (server notes and lessons)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gtnh_search_status",
        "description": "Shows the index's size per kind, its model and build time, and whether a refresh is running or disabled.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "gtnh_reindex",
        "description": "Refreshes the index now, embedding only passages that changed (for example after saving a playbook answer). "
                       "Usually unnecessary: the server refreshes itself in the background.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def log(msg):
    print("[gtnh-search] " + msg, file=sys.stderr, flush=True)


class Service:
    def __init__(self, ctx, embedder, path, profile=s.DEFAULT_PROFILE):
        self.ctx, self.embedder, self.path, self.profile = ctx, embedder, path, profile
        self.mtime = self.file_mtime()
        self.index = s.read_index(path, log)
        self.lock = threading.Lock()
        self.refreshing = False
        self.last_refresh = 0.0
        # A damaged index file is served as "no index" and rebuilt by the first refresh (build() sets it aside).
        self.last_error = "the index file %s is unreadable; a refresh rebuilds it" % path.name \
            if self.index is None and path.is_file() else None

    def file_mtime(self):
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def maybe_reload(self):
        """Picks up an index another process wrote (the weekly wiki job, a CLI build). One stat per query."""
        mtime = self.file_mtime()
        if mtime is None or mtime == self.mtime or self.refreshing:
            return False
        try:
            index = s.load_index(self.path)
        except Exception as e:  # a half-visible file is retried on the next query
            log("reload failed: %s" % e)
            return False
        if index:
            self.index, self.mtime = index, mtime
            log("reloaded %s (%d chunks)" % (self.path.name, index["meta"]["chunks"]))
        return True

    def can_refresh(self):
        return self.embedder is not None and self.ctx.writable()

    def start_refresh(self):
        """Starts a refresh thread and returns it, or None when one is running or refreshing is off."""
        with self.lock:
            if self.refreshing or not self.can_refresh():
                return None
            self.refreshing, self.last_refresh = True, time.time()
        t = threading.Thread(target=self._refresh, daemon=True)
        t.start()
        return t

    def refresh(self):
        """Refreshes and waits. False when a refresh is already running or refreshing is off."""
        t = self.start_refresh()
        if t is None:
            return False
        t.join()
        return True

    def _refresh(self):
        try:
            index = s.build(self.ctx, self.embedder, self.path, self.profile, log=log)
            self.index = index or s.read_index(self.path, log) or self.index
            self.mtime = self.file_mtime()
            self.last_error = None
        except Exception as e:  # a failed refresh must not take the server down
            self.last_error = str(e)
            log("refresh failed: %s" % e)
        finally:
            self.refreshing = False

    def refresh_in_background(self):
        if self.can_refresh() and not self.refreshing and time.time() - self.last_refresh > REFRESH_AFTER:
            self.start_refresh()

    def status(self):
        lines = []
        if self.index:
            m = self.index["meta"]
            lines.append("Index: %d chunks from %d sources, profile %s, model %s" % (m["chunks"], m["sources"], m["profile"], m["model"]))
            lines.append("Per kind: " + ", ".join("%s %d" % kv for kv in sorted(m.get("kinds", {}).items())))
            lines.append("Built %s from pack %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(m["built_at"])), m.get("pack") or "?"))
        else:
            lines.append("No index yet at %s." % self.path)
        if self.ctx.state:
            lines.append("State directory: %s" % self.ctx.state)
        if not self.ctx.writable():
            lines.append("Read-only mode: the index is served as built; background refresh and gtnh_reindex are off.")
        else:
            lines.append("Refresh running: %s" % ("yes" if self.refreshing else "no"))
        if self.embedder is None:
            lines.append("OPENROUTER_API_KEY is not set (environment or .env at the repository root); search is unavailable.")
        if self.last_error:
            lines.append("Last refresh error: " + self.last_error)
        return "\n".join(lines)

    def call(self, name, args):
        self.maybe_reload()
        if name == "gtnh_search_status":
            return self.status(), False
        if name == "gtnh_reindex":
            t = self.start_refresh()
            if t is None:
                return "A refresh is already running, the index is read-only, or no API key is set.\n" + self.status(), True
            t.join(REINDEX_WAIT)
            if t.is_alive():
                return "The refresh is still running in the background; search keeps using the current index until " \
                       "it finishes.\n" + self.status(), False
            return self.status(), bool(self.last_error)
        if name == "gtnh_search":
            query = (args.get("query") or "").strip()
            if not query:
                return "query is required", True
            if self.embedder is None:
                return self.status(), True
            if self.index is None:
                if self.start_refresh() is not None:
                    return "The index is being built for the first time (a few minutes). Try again shortly.", True
                return self.status(), True
            self.refresh_in_background()
            k = max(1, min(25, int(args.get("k") or 8)))
            kind = args.get("kind") or "any"
            if kind not in KIND_ENUM:
                return "kind must be one of: " + ", ".join(KIND_ENUM), True
            hits = s.search(self.index, self.embedder.query(query), k, kind)
            return s.format_hits(hits), False
        return "unknown tool: %s" % name, True


def handle(service, msg):
    """Returns the JSON-RPC response for one message, or None for notifications."""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: expected an object"}}
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params")
    params = params if isinstance(params, dict) else {}
    if mid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gtnh-search", "version": "1.0.0"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            args = params.get("arguments")
            text, is_error = service.call(params.get("name"), args if isinstance(args, dict) else {})
        except Exception as e:
            log(traceback.format_exc())
            text, is_error = "error: %s" % e, True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def safe_handle(service, msg):
    """handle(), but any unexpected error becomes a JSON-RPC error reply instead of ending the server."""
    try:
        return handle(service, msg)
    except Exception as e:
        log(traceback.format_exc())
        mid = msg.get("id") if isinstance(msg, dict) else None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "internal error: %s" % e}}


def serve(service, stdin, stdout, workers=CALL_WORKERS):
    """The stdio loop: one JSON-RPC message per line. tools/call runs on a worker pool (replies may come back out of
    order, matched by id); everything else is answered inline."""
    out_lock = threading.Lock()

    def reply(msg):
        r = safe_handle(service, msg)
        if r is not None:
            with out_lock:
                stdout.write(json.dumps(r) + "\n")
                stdout.flush()

    with ThreadPoolExecutor(workers) as pool:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                log("ignored a line that is not JSON")
                continue
            if isinstance(msg, dict) and msg.get("method") == "tools/call" and msg.get("id") is not None:
                pool.submit(reply, msg)
            else:
                reply(msg)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    profile = argv[argv.index("--profile") + 1] if "--profile" in argv else s.DEFAULT_PROFILE
    ctx = s.Context(readonly=True if "--readonly" in argv else None)
    if ctx.state and not ctx.readonly:
        s.seed(ctx, log=log)
    key = s.load_key(ctx.root)
    model = s.PROFILES[profile]["model"]
    service = Service(ctx, s.OpenRouter(key, model) if key else None, s.index_path(ctx, profile), profile)
    service.start_refresh()
    serve(service, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
