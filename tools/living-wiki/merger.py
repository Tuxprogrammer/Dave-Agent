"""Page mergers for the living wiki: a deterministic section merge (the stub, and the lossless fallback), the Sonnet
merger through the Claude Code CLI on the owner's subscription, and validation of any merger's output.

The wiki describes what is true now: page text never carries merge notes or history. What was kept or dropped, and
the losing alternative, go into the merge commit message, the merge report and the review queue.
"""

import copy
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
PROMPT_FILE = HERE / "merge_prompt.md"
DEFAULT_MODEL = os.environ.get("LIVING_WIKI_MERGE_MODEL", "sonnet")
# Model calls allowed per update run; pages past the budget take the lossless fallback (flagged).
MAX_CALLS = int(os.environ.get("LIVING_WIKI_MERGE_MAX_CALLS", "50"))

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7}|\|{7})(\s|$)", re.M)
# Phrasing that narrates history instead of stating current fact. A warning for Dave's edits; for a merger's output it
# fails validation only when neither input already contains the phrase.
HISTORY_PHRASES = re.compile(
    r"\b(used to|previously|no longer|was changed|has been changed|old version|corrected|as of the last update|"
    r"the guide used to say|official update|needs review|server corrections?|merge note)\b|~~", re.I)


# Sections

def heading_lines(text):
    """[(line index, level, heading text)] for every Markdown heading outside code fences."""
    out, fence = [], False
    for i, line in enumerate(text.split("\n")):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def sections(text):
    """Splits Markdown at headings (outside code fences). Returns [(key, heading text, chunk)], where chunk is the heading
    line through the line before the next heading. The preamble has key ''. Repeated headings get '#2', '#3' keys."""
    lines = text.split("\n")
    out, seen, starts = [], {}, heading_lines(text)
    if not starts or starts[0][0] > 0:
        out.append(("", "", "\n".join(lines[:starts[0][0] if starts else len(lines)])))
    for n, (i, _, title) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        base = title.lower()
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else "%s#%d" % (base, seen[base])
        out.append((key, title, "\n".join(lines[i:end])))
    return [s for s in out if s[0] or s[2].strip()]


def headings(text):
    return [t for k, t, _ in sections(text) if k]


def same(a, b):
    return (a or "").strip() == (b or "").strip()


def merge_sections(base, new, living):
    """Three-way merge by section. Official changes win where Dave did not touch a section, Dave's version wins where he
    did (his edits carry evidence), and every true contradiction is reported. Returns a merger result dict."""
    b = {k: c for k, _, c in sections(base)}
    n_list = sections(new)
    n = {k: c for k, _, c in n_list}
    l_list = sections(living)
    l = {k: c for k, _, c in l_list}
    titles = {k: t for k, t, _ in n_list + l_list}
    out, conflicts, dropped, took_dave = [], [], [], []
    for k, title, nc in n_list:
        if k not in l:
            if k in b and not same(b[k], nc):
                conflicts.append({"section": title or "(intro)", "kept": "removed (Dave removed this section)", "losing_text": nc})
            if k in b:
                dropped.append({"heading": title, "reason": "Dave removed this section"})
                continue
            out.append((k, nc))
        elif same(l[k], b.get(k)) or same(l[k], nc):
            out.append((k, nc))
        elif k in b and same(nc, b[k]):
            out.append((k, l[k]))
            took_dave.append(title or "(intro)")
        else:
            out.append((k, l[k]))
            conflicts.append({"section": title or "(intro)", "kept": "Dave's version", "losing_text": nc})
    placed = {k for k, _ in out}
    order = [k for k, _, _ in l_list]
    for i, k in enumerate(order):
        if k in placed:
            continue
        if k in b and same(l[k], b[k]):
            continue  # removed officially, never touched by Dave
        if k in b:
            conflicts.append({"section": titles.get(k) or "(intro)", "kept": "Dave's version (removed officially)", "losing_text": ""})
        prev = next((p for p in reversed(order[:i]) if p in placed), None)
        at = next((j + 1 for j, (pk, _) in enumerate(out) if pk == prev), 0)
        out.insert(at, (k, l[k]))
        placed.add(k)
        took_dave.append(titles.get(k) or "(intro)")
    text = "\n\n".join(c.strip("\n") for _, c in out).strip() + "\n"
    note = []
    if took_dave:
        note.append("kept Dave's sections: " + ", ".join(took_dave))
    if conflicts:
        note.append("contradictions kept as Dave's version: " + ", ".join(c["section"] for c in conflicts))
    return {
        "merged_text": text,
        "commit_note": "; ".join(note) or "took the new official text",
        "flag": bool(conflicts),
        "flag_reason": "; ".join("%s: official and Dave disagree, kept %s" % (c["section"], c["kept"]) for c in conflicts),
        "losing_text": "\n\n".join(c["losing_text"] for c in conflicts if c["losing_text"]),
        "dropped_headings": dropped,
    }


# Validation

def validate(result, base, new, living):
    """Problems with a merger's output; an empty list means it can be committed."""
    if not isinstance(result, dict):
        return ["result is not a JSON object"]
    text = result.get("merged_text")
    if not isinstance(text, str) or not text.strip():
        return ["merged text is empty"]
    problems = []
    if CONFLICT_MARKER.search(text):
        problems.append("merged text contains conflict markers")
    lo = 0.5 * min(len(new.strip()), len(living.strip()))
    hi = 1.5 * max(len(new), len(living)) + 2000
    if not lo <= len(text.strip()) <= hi:
        problems.append("merged length %d is outside %d..%d" % (len(text.strip()), lo, hi))
    dropped = {str(d.get("heading", "")).strip().lower() for d in result.get("dropped_headings") or []
               if isinstance(d, dict) and str(d.get("reason", "")).strip()}
    have = {h.lower() for h in headings(text)}
    missing = [h for h in headings(new) if h.lower() not in have and h.lower() not in dropped]
    if missing:
        problems.append("missing official headings without a reason: " + ", ".join(missing[:5]))
    inputs = new + "\n" + living
    leaked = sorted({m.group(0).lower() for m in HISTORY_PHRASES.finditer(text)} -
                    {m.group(0).lower() for m in HISTORY_PHRASES.finditer(inputs)})
    if leaked:
        problems.append("merged text narrates history (%s); that belongs in the commit message" % ", ".join(leaked))
    return problems


def fallback(base, new, living, why):
    """The lossless fallback: the deterministic section merge, always flagged. Nothing is lost: the losing text goes
    to the report and the review queue, not into the page."""
    r = merge_sections(base, new, living)
    r["flag"] = True
    r["flag_reason"] = "; ".join(x for x in ("fallback merge: " + why, r["flag_reason"]) if x)
    return r


# The preservation audit

def norm(line):
    return re.sub(r"\s+", " ", line or "").strip()


def significant(line):
    return len(re.sub(r"\W", "", line)) >= 3


class _Lines:
    """A text's normalized lines, for 'is this line still there' checks. Exact after whitespace normalization (a line
    joined into a longer one still counts): no fuzzy matching, because Dave's corrections are often one number."""

    def __init__(self, text):
        self.lines = [norm(l) for l in (text or "").split("\n") if norm(l)]
        self.set = set(self.lines)
        self.full = " ".join(self.lines)

    def has(self, line):
        n = norm(line)
        return n in self.set or (" %s " % n) in (" %s " % self.full)


def changed_lines(old, new):
    """([(index in new, line)] added or changed in new, [(index in old, line)] removed from old)."""
    a, b = old.split("\n"), new.split("\n")
    added, removed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            added += [(j, b[j]) for j in range(j1, j2)]
        if tag in ("replace", "delete"):
            removed += [(i, a[i]) for i in range(i1, i2)]
    return added, removed


def section_titles(text):
    """The section heading for every line of text ('(intro)' before the first heading)."""
    out, cur, starts = [], "(intro)", {i: t for i, _, t in heading_lines(text)}
    for i in range(len(text.split("\n"))):
        cur = starts.get(i, cur)
        out.append(cur)
    return out


def audit(merged, base, new, living):
    """What a merge left out, line by line, with the section each line belongs to:
      dave/dropped        Dave's added or changed lines (living vs base) missing from merged
      dave/reinstated     lines Dave removed that merged has again
      official/dropped    official's added or changed lines (new vs base) missing from merged
      official/reinstated lines official removed, kept by Dave untouched, that merged still has
    Dave-added headings count as Dave's lines. Returns [{"side", "kind", "section", "line"}]."""
    m, lv, nw = _Lines(merged), _Lines(living), _Lines(new)
    out = []

    def scan(side, other, changed_text):
        added, removed = changed_lines(base, changed_text)
        titles_new, titles_base = section_titles(changed_text), section_titles(base)
        for j, line in added:
            if significant(line) and not m.has(line):
                out.append({"side": side, "kind": "dropped", "section": titles_new[j], "line": norm(line)})
        changed = _Lines(changed_text)
        for i, line in removed:
            # Removed on this side, still in the other side's text (so the other side did not remove or change it),
            # and back in the merge.
            if significant(line) and not changed.has(line) and other.has(line) and m.has(line):
                out.append({"side": side, "kind": "reinstated", "section": titles_base[i], "line": norm(line)})

    scan("dave", nw, living)
    scan("official", lv, new)
    have = {h.lower() for h in headings(merged)}
    for h in set(headings(living)) - set(headings(base)):
        if h.lower() not in have and not any(g["line"].lstrip("#").strip() == h for g in out):
            out.append({"side": "dave", "kind": "dropped", "section": h, "line": "## " + h})
    return out


def check(result, base, new, living):
    """validate() plus the preservation audit. Returns problems; an empty list means result (flagged and given any
    unreported losing text by this call) can be committed. Dave's text dropped without being reported in
    losing_text is a problem (the fallback keeps it); everything else the audit finds is flagged for review."""
    problems = validate(result, base, new, living)
    if problems:
        return problems
    gaps = audit(result["merged_text"], base, new, living)
    reported = _Lines(str(result.get("losing_text") or ""))
    silent = [g for g in gaps if g["side"] == "dave" and g["kind"] == "dropped" and not reported.has(g["line"])]
    if silent:
        return ["merger dropped Dave's text without reporting it (%s)" % "; ".join(
            "%s: %s" % (g["section"], g["line"][:80]) for g in silent[:5])]
    if gaps:
        summary = {}
        for g in gaps:
            summary.setdefault((g["side"], g["kind"]), []).append(g["section"])
        words = {("dave", "dropped"): "Dave's text replaced", ("dave", "reinstated"): "text Dave removed is back",
                 ("official", "dropped"): "official changes not used", ("official", "reinstated"): "text official removed kept"}
        why = "merge check: " + "; ".join("%s in %s" % (words[k], ", ".join(sorted(set(v))[:5])) for k, v in summary.items())
        extra = ["[%s %s, %s] %s" % (g["side"], g["kind"], g["section"], g["line"]) for g in gaps
                 if g["kind"] == "dropped" and not reported.has(g["line"])]
        result["flag"] = True
        result["flag_reason"] = "; ".join(x for x in (str(result.get("flag_reason") or "").strip(), why) if x)
        if extra:
            result["losing_text"] = "\n\n".join(x for x in (str(result.get("losing_text") or "").strip(),
                                                             "\n".join(extra)) if x)
    return []


# Mergers

class StubMerger:
    """Deterministic and offline: the section merge. Used in tests and dry runs."""
    name = "stub"

    def merge(self, page, base, new, living, edits):
        return merge_sections(base, new, living)


class Cached:
    """Remembers a merger's answer (or failure) per exact input, so an update can run every model call before it takes
    the wiki lock and replay the answers under it; only pages Dave edited in between reach the merger again."""

    def __init__(self, inner):
        self.inner, self.name, self.memo = inner, inner.name, {}

    def merge(self, page, base, new, living, edits):
        key = hashlib.sha1(json.dumps([page, base, new, living, edits], sort_keys=True).encode("utf-8")).hexdigest()
        if key not in self.memo:
            try:
                self.memo[key] = (copy.deepcopy(self.inner.merge(page, base, new, living, edits)), None)
            except Exception as e:  # remembered too: a failing page is not retried under the lock
                self.memo[key] = (None, e)
        result, err = self.memo[key]
        if err is not None:
            raise err
        return copy.deepcopy(result)


def load_dave_config():
    """Dave's config and launch helpers (dave/config.py, dave/launch/dave_cmd.py), imported, not copied."""
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from dave import config  # noqa: E402
    from dave.launch import dave_cmd  # noqa: E402
    return config, dave_cmd


class ClaudeMerger:
    """One `claude -p` call per conflicted page: Sonnet (configurable) on the owner's subscription via
    CLAUDE_CODE_OAUTH_TOKEN, with no tools, no settings, no MCP servers, no CLAUDE.md, its own config dir and a cwd
    outside the repository and the owner's home."""
    name = "claude"

    def __init__(self, model=DEFAULT_MODEL, cfg=None, timeout=600, max_calls=MAX_CALLS):
        self.config, self.dave_cmd = load_dave_config()
        self.cfg = cfg or self.config.load()
        self.model, self.timeout = model, timeout
        self.max_calls, self.calls = max_calls, 0
        run = self.cfg["paths"]["run"] / "wiki-merger"
        self.home = run / "home"
        self.workdir = self.cfg["paths"]["workdir"].parent / "wiki-merge"
        self.mcp_file = run / "empty-mcp.json"

    def command(self):
        claude = self.cfg.get("claude", {}).get("bin", "claude")
        claude = shutil.which(claude) or claude
        return [
            claude, "-p", "--model", self.model, "--output-format", "json", "--no-session-persistence",
            "--system-prompt-file", str(PROMPT_FILE),
            "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(self.mcp_file),
            "--disable-slash-commands",
        ]

    def environment(self):
        """Only the launcher's allow-listed variables, plus an isolated config dir and the OAuth token. Never an API key."""
        token, _ = self.config.secret(self.cfg, "claude_oauth_token")
        env = {k: v for k, v in os.environ.items() if k in self.dave_cmd.ENV_ALLOW or k.startswith("LC_")}
        env.update({
            "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home),
            "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "DISABLE_AUTOUPDATER": "1",
        })
        env.pop("ANTHROPIC_API_KEY", None)
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return env

    def problems(self):
        out = self.dave_cmd.problems(self.cfg, self.workdir)
        if "CLAUDE_CODE_OAUTH_TOKEN" not in self.environment():
            out.append("CLAUDE_CODE_OAUTH_TOKEN is not available (env, NAME_FILE, /run/secrets or dave/.env)")
        return out

    def prepare(self):
        for d in (self.home, self.workdir):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        self.mcp_file.parent.mkdir(parents=True, exist_ok=True)
        self.mcp_file.write_text('{"mcpServers": {}}\n')

    def merge(self, page, base, new, living, edits):
        if self.calls >= self.max_calls:
            raise RuntimeError("merge budget of %d model calls is used up (LIVING_WIKI_MERGE_MAX_CALLS)" % self.max_calls)
        problems = self.problems()
        if problems:
            raise RuntimeError("; ".join(problems))
        self.prepare()
        self.calls += 1
        payload = json.dumps({"page": page, "base": base, "official_new": new, "living": living, "dave_edits": edits},
                             ensure_ascii=False)
        proc = subprocess.run(self.command(), input=payload, cwd=self.workdir, env=self.environment(),
                              capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError("claude exited %d: %s" % (proc.returncode, (proc.stderr or proc.stdout)[-500:]))
        return parse_reply(proc.stdout)


def parse_reply(stdout):
    """The model's JSON object from `claude -p --output-format json` output (tolerates a code fence around it)."""
    outer = json.loads(stdout)
    if outer.get("is_error"):
        raise RuntimeError("claude returned an error: %s" % str(outer.get("result"))[:300])
    text = (outer.get("result") or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("no JSON object in the reply")
    result = json.loads(text[start:end + 1])
    result["cost_usd"] = outer.get("total_cost_usd")
    return result


def make(kind, model=DEFAULT_MODEL):
    if kind == "stub":
        return StubMerger()
    if kind == "claude":
        return ClaudeMerger(model)
    raise ValueError("unknown merger %r (stub|claude)" % kind)
