"""Saved eval queries: named Groovy scripts that worked, reused through query_run. Standard library only.

Two folders, searched in order:
  saved    [paths] queries (DAVE_QUERIES_DIR), default data/memory/queries: what Dave saves. It sits inside the
           memory folder, so in production it is on the memory volume and exported with the memories.
  starter  dave/queries/ in the app: the shipped set (world lookups, live recipe lookup). Read-only.

A saved query with the same name as a starter overrides it.

File format, <name>.groovy, a header of `// @key: value` lines, then the script:

    // @description: Where is a GT machine, by name or type, nearest first
    // @mode: read
    // @side: server
    // @timeout_ms: 2000
    // @param type: string, required. Machine name or id fragment, e.g. "blast furnace"
    // @param limit: number. How many to list (default 5)
    def type = params.type ...
"""

import os
import re
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
HEADER_RE = re.compile(r"^//\s*@([a-z_]+)(?:\s+([A-Za-z0-9_]+))?\s*:\s*(.*)$")
MAX_SCRIPT = 64 * 1024
APP_STARTERS = Path(__file__).resolve().parents[1] / "queries"


class QueryError(Exception):
    pass


def parse(text, name=None):
    """Returns the query as a dict: name, description, mode, side, timeout_ms, params {name: doc}, script."""
    q = {"name": name, "description": "", "mode": "read", "side": "server", "timeout_ms": None, "params": {},
         "script": text}
    for line in text.splitlines():
        m = HEADER_RE.match(line.strip())
        if not m:
            if line.strip() and not line.strip().startswith("//"):
                break
            continue
        key, arg, value = m.group(1), m.group(2), m.group(3).strip()
        if key == "param" and arg:
            q["params"][arg] = value
        elif key == "timeout_ms":
            try:
                q["timeout_ms"] = int(value)
            except ValueError:
                pass
        elif key in ("description", "mode", "side"):
            q[key] = value
    return q


def render(name, description, script, mode="read", side="server", params=None, timeout_ms=None):
    """The file text for a query; the script keeps any header it already has below ours."""
    lines = ["// @description: %s" % " ".join((description or "").split())]
    lines.append("// @mode: %s" % mode)
    lines.append("// @side: %s" % side)
    if timeout_ms:
        lines.append("// @timeout_ms: %d" % int(timeout_ms))
    for pname, doc in (params or {}).items():
        lines.append("// @param %s: %s" % (pname, " ".join(str(doc).split())))
    body = "\n".join(l for l in script.splitlines() if not HEADER_RE.match(l.strip()))
    return "\n".join(lines) + "\n" + body.strip("\n") + "\n"


class Queries:
    def __init__(self, saved_dir, starter_dir=APP_STARTERS):
        self.saved = Path(saved_dir)
        self.starter = Path(starter_dir)

    def _path(self, folder, name):
        return folder / (name + ".groovy")

    def check_name(self, name):
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise QueryError("query names are 2-64 characters: lowercase letters, digits, - and _ (got %r)" % (name,))

    def get(self, name):
        self.check_name(name)
        for origin, folder in (("saved", self.saved), ("starter", self.starter)):
            p = self._path(folder, name)
            if p.is_file():
                q = parse(p.read_text(encoding="utf-8"), name)
                q["origin"] = origin
                return q
        raise QueryError("no query named %r; query_list shows what exists" % name)

    def list(self):
        out = {}
        for origin, folder in (("starter", self.starter), ("saved", self.saved)):
            if not folder.is_dir():
                continue
            for p in sorted(folder.glob("*.groovy")):
                if NAME_RE.match(p.stem):
                    q = parse(p.read_text(encoding="utf-8"), p.stem)
                    q["origin"] = origin
                    out[p.stem] = q                 # saved overrides starter
        return [out[k] for k in sorted(out)]

    def save(self, name, description, script, mode="read", side="server", params=None, timeout_ms=None,
             replace=False):
        self.check_name(name)
        if not description or not description.strip():
            raise QueryError("description is required: say what the query answers")
        if not script or not script.strip():
            raise QueryError("script is empty")
        if len(script) > MAX_SCRIPT:
            raise QueryError("script too long (%d characters, at most %d)" % (len(script), MAX_SCRIPT))
        if mode not in ("read", "write"):
            raise QueryError("mode must be read or write")
        if side not in ("server", "client"):
            raise QueryError("side must be server or client")
        p = self._path(self.saved, name)
        if p.exists() and not replace:
            raise QueryError("a saved query %r already exists; pass replace=true to overwrite it" % name)
        self.saved.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".tmp-" + p.name)
        tmp.write_text(render(name, description, script, mode, side, params, timeout_ms), encoding="utf-8")
        os.replace(tmp, p)
        overrides = self._path(self.starter, name).is_file()
        return {"name": name, "path": str(p), "overrides_starter": overrides}
