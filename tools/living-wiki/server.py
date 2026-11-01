"""MCP server (stdio, JSON-RPC 2.0) that lets Dave read and edit the living wiki. Standard library only.

  python3 -I tools/living-wiki/server.py

Every edit is a commit on the `living` branch with Reason / Evidence / Asked-by trailers. After an edit the search
corpus is re-materialized and an incremental index build runs in the background.
"""

import json
import subprocess
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import living_wiki as lw_mod  # noqa: E402
from living_wiki import s  # noqa: E402

MAX_PAGE_CHARS = lw_mod.VIEW_LIMIT

INSTRUCTIONS = (
    "The living wiki is this server's own copy of wiki.gtnewhorizons.com. It starts from the official wiki, takes "
    "the official monthly updates, and keeps your corrections across them. Read a page with wiki_get before you "
    "rely on it or change it. Change a page when you have evidence that it is wrong or missing something for this "
    "server's pack: a recipe lookup, source in gtnh-src, an in-game check, or a player's report you have confirmed. "
    "Players may ask for any edit; record who asked. "
    "THE WIKI DESCRIBES WHAT IS TRUE NOW. Write page text as current fact in the wiki's own neutral voice. Replace "
    "wrong text; never write 'used to', 'previously', 'the guide said', 'corrected by Dave', dates of changes or "
    "strikethrough in a page. The why, the old claim and the evidence go in `reason`, `supersedes` and `evidence`, "
    "which become commit trailers that wiki_history shows. Search hits from pages you edited show 'locally edited'."
)

CURRENT_FACT = ("Write the page as current fact in the wiki's neutral voice. Put why it changed in `reason`, the "
                "old claim in `supersedes` and the proof in `evidence`; never put history in the page text.")

TOOLS = [
    {
        "name": "wiki_get",
        "description": "Returns a wiki page's current text, whether it has local edits or open review flags, and its "
                       "recent history. Page titles are case-insensitive.",
        "inputSchema": {"type": "object", "properties": {
            "page": {"type": "string", "description": "Page title, e.g. 'Electric Blast Furnace'."},
            "history": {"type": "integer", "minimum": 0, "maximum": 50, "default": 5}},
            "required": ["page"]},
    },
    {
        "name": "wiki_search_titles",
        "description": "Lists page titles starting with (then containing) the given text. Use gtnh_search to search "
                       "page content by meaning.",
        "inputSchema": {"type": "object", "properties": {
            "prefix": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
            "required": ["prefix"]},
    },
    {
        "name": "wiki_edit",
        "description": "Changes a wiki page, or one section of it, and commits the change with your reason and "
                       "evidence. " + CURRENT_FACT + " With `section`, new_text replaces the text under that heading "
                       "up to the next heading of any level (the heading stays; subsections are separate sections; the "
                       "page title heading means the intro); without it, new_text is the whole page. Text that narrates history is "
                       "returned for a rewrite unless confirm_current_fact is true (for real current facts such as "
                       "'no longer drops from mobs'). Pages longer than wiki_get shows must be edited by section: a "
                       "whole-page edit that drops their hidden tail is refused unless confirm_whole_page is true.",
        "inputSchema": {"type": "object", "properties": {
            "page": {"type": "string"},
            "section": {"type": "string", "description": "Heading text of the section to replace; omit for the whole page."},
            "new_text": {"type": "string", "description": "The current, correct text, Markdown, no history."},
            "reason": {"type": "string", "description": "Why the page changed, in a sentence or two."},
            "evidence": {"type": "string", "description": "Required. A tool result summary, a gtnh-src path, a recipe ID or an in-game eval result."},
            "asked_by": {"type": "string", "description": "The player who asked for the change, if any."},
            "supersedes": {"type": "string", "description": "The old claim this replaces, in a few words."},
            "resolves_review": {"type": "boolean", "default": False, "description": "True when this edit settles the page's open review flag."},
            "confirm_current_fact": {"type": "boolean", "default": False},
            "confirm_whole_page": {"type": "boolean", "default": False,
                                   "description": "True only to really shorten a page longer than wiki_get shows."}},
            "required": ["page", "new_text", "reason", "evidence"]},
    },
    {
        "name": "wiki_create",
        "description": "Creates a page that the official wiki doesn't have, such as server-specific content (the "
                       "GregGuns mod, local rules for machines). " + CURRENT_FACT,
        "inputSchema": {"type": "object", "properties": {
            "page": {"type": "string"}, "text": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "string"}, "asked_by": {"type": "string"},
            "confirm_current_fact": {"type": "boolean", "default": False}},
            "required": ["page", "text", "reason", "evidence"]},
    },
    {
        "name": "wiki_history",
        "description": "A page's history: official imports, merges and your edits with their reason, evidence, "
                       "superseded claim and who asked.",
        "inputSchema": {"type": "object", "properties": {
            "page": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
            "required": ["page"]},
    },
    {
        "name": "wiki_revert",
        "description": "Undoes one of your earlier edits (a commit from wiki_history) with a new commit. Official "
                       "imports and merges can't be reverted.",
        "inputSchema": {"type": "object", "properties": {
            "commit": {"type": "string"}, "reason": {"type": "string"}, "asked_by": {"type": "string"}},
            "required": ["commit", "reason"]},
    },
]


def log(msg):
    print("[living-wiki] " + msg, file=sys.stderr, flush=True)


class Reindexer:
    """Runs one incremental index build at a time in the background; a request during a build queues one more."""

    def __init__(self, argv=None):
        self.argv = argv or [sys.executable, "-I", str(lw_mod.SEARCH / "index.py")]
        self.lock = threading.Lock()
        self.running = self.pending = False

    def request(self):
        with self.lock:
            if self.running:
                self.pending = True
                return
            self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                p = subprocess.run(self.argv, capture_output=True, text=True, timeout=3600, stdin=subprocess.DEVNULL)
                log("reindex exit %d: %s" % (p.returncode, (p.stderr.strip().splitlines() or [""])[-1]))
            except Exception as e:  # the search server's own refresh catches up later
                log("reindex failed: %s" % e)
            with self.lock:
                if not self.pending:
                    self.running = False
                    return
                self.pending = False


class Service:
    def __init__(self, ctx, reindexer=None):
        self.ctx = ctx
        self.wiki, _ = lw_mod.ensure(ctx, log)
        self.reindexer = reindexer if reindexer is not None else Reindexer()
        if self.wiki.exists():
            self.wiki.sync(log)

    def after_change(self):
        """Refreshes the corpus and queues a reindex. Never raises: the edit is already committed, and an error here would
        make Dave retry a change that was saved. Returns a note for the reply when the refresh failed."""
        note = ""
        try:
            self.wiki.sync(log)
        except Exception as e:
            log("corpus sync after an edit failed: %s" % traceback.format_exc())
            note = " (the search corpus refresh failed: %s; the next edit or restart retries it)" % e
        if self.reindexer:
            self.reindexer.request()
        return note

    def call(self, name, a):
        w = self.wiki
        if not w.exists():
            return "No living wiki yet at %s (no wiki snapshot to start from)." % w.dir, True
        if name == "wiki_search_titles":
            q = (a.get("prefix") or "").strip().lower()
            limit = max(1, min(200, int(a.get("limit") or 50)))
            titles = sorted(w.pages())
            hits = [t for t in titles if t.lower().startswith(q)] + [t for t in titles if q in t.lower() and not t.lower().startswith(q)]
            return ("\n".join(hits[:limit]) + ("\n(+%d more)" % (len(hits) - limit) if len(hits) > limit else "")) or "No titles match.", False
        if name == "wiki_get":
            title, text = w.text(a.get("page") or "")
            if not title:
                return "No page %r. Try wiki_search_titles." % a.get("page"), True
            _, hist = w.history(title, max(0, min(50, int(a.get("history", 5)))) or 1)
            p = w.pages()[title]
            lines = ["# page: %s" % title]
            if p.get("local"):
                lines.append("server-only page (not in the official wiki)")
            local = [h for h in hist if h["kind"] == "dave"]
            if local:
                lines.append("locally edited %s" % local[0]["date"])
            for r in w.open_reviews(title):
                lines.append("OPEN REVIEW (%s): %s" % (r.get("item", ""), r.get("reason", "")))
            for h in hist[:int(a.get("history", 5))]:
                lines.append("history %s %s %s: %s%s" % (h["date"], h["commit"], h["kind"], h["reason"] or h["subject"],
                                                       (" (asked by %s)" % h["asked_by"]) if h["asked_by"] else ""))
            body = text if len(text) <= MAX_PAGE_CHARS else text[:MAX_PAGE_CHARS] + "\n[… truncated; edit by section]"
            return "\n".join(lines) + "\n---\n" + body, False
        if name == "wiki_history":
            title, hist = w.history(a.get("page") or "", max(1, min(100, int(a.get("limit") or 20))))
            if not title:
                return "No page %r." % a.get("page"), True
            return json.dumps({"page": title, "history": hist}, indent=1, ensure_ascii=False), False
        if name in ("wiki_edit", "wiki_create"):
            text = a.get("new_text") if name == "wiki_edit" else a.get("text")
            if not (text or "").strip():
                return "The new text is empty.", True
            warn = lw_mod.history_warnings(text)
            if warn and not a.get("confirm_current_fact"):
                return ("Not saved: the text narrates history (%s). %s If these words describe a current fact, resend "
                        "with confirm_current_fact: true." % (", ".join(warn), CURRENT_FACT)), True
            if name == "wiki_edit":
                title, sha = w.edit(a.get("page") or "", text, a.get("reason"), a.get("evidence"), a.get("asked_by"),
                                    a.get("section") or None, a.get("supersedes"), bool(a.get("resolves_review")),
                                    bool(a.get("confirm_whole_page")))
            else:
                title, sha = w.create(a.get("page") or "", text, a.get("reason"), a.get("evidence"), a.get("asked_by"))
            note = self.after_change()
            return "Saved %s as %s. Search will include it after the background reindex.%s" % (title, sha[:10], note), False
        if name == "wiki_revert":
            sha = w.revert(a.get("commit") or "", a.get("reason"), a.get("asked_by"))
            return "Reverted with %s.%s" % (sha[:10], self.after_change()), False
        return "unknown tool: %s" % name, True


def handle(service, msg):
    """Returns the JSON-RPC response for one message, or None for notifications."""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: not a JSON object"}}
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params")
    params = params if isinstance(params, dict) else {}
    if mid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "living-wiki", "version": "1.0.0"},
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
        except (KeyError, ValueError, RuntimeError) as e:
            text, is_error = "error: %s" % (e.args[0] if e.args else e), True
        except Exception as e:
            log(traceback.format_exc())
            text, is_error = "error: %s" % e, True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    service = Service(s.Context())
    out_lock = threading.Lock()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            reply = handle(service, msg)
        except Exception as e:  # one bad message never stops the server
            log(traceback.format_exc())
            reply = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                     "error": {"code": -32603, "message": "internal error: %s" % e}}
        if reply is not None:
            with out_lock:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
