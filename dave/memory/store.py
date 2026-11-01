"""Dave's file-backed memory store. Standard library only.

Layout under the memory directory (data/memory/ in dev, a volume in production):

    players/<uuid>.md      one profile per player, keyed by UUID
    playbook/<slug>.md     solved answers
    server/<slug>.md       server-wide facts
    lessons/<slug>.md      Dave's notes to himself
    INDEX.md               regenerated on every write: one line per active memory
    .log.jsonl             every write: who, what, when, before/after content hashes
    .objects/xx/<sha>.md   every version ever written, by content hash (what restore() reads)
    .lock                  fcntl lock taken around every write
    .tmp-*.part            a write in progress (renamed into place when complete; leftovers are removed on open)

A memory's id is its path without ".md", e.g. "playbook/best-nitrogen-at-hv". Each file is Markdown with a
small frontmatter block of "key: value" lines; lists, dicts and anything ambiguous are written as JSON.

Nothing is deleted: forget() archives, correct() supersedes, and every version stays in .objects/.

CLI (for the owner):  python3 -I dave/memory/store.py index | log [N] | restore <id> <sha>
"""

import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

KINDS = ("players", "playbook", "server", "lessons")
STATUSES = ("active", "stale", "superseded", "archived")
# Player profile fields: single-valued ones are replaced, list ones collect dated bullets.
PLAYER_FIELDS = {"tier": "single", "client_eval": "single", "base": "list", "setup": "list",
                 "preferences": "list", "notes": "list"}
FIELD_HEADINGS = {"tier": "Tier", "client_eval": "Client eval", "base": "Base", "setup": "Setup",
                  "preferences": "Preferences", "notes": "Notes"}
META_ORDER = ("id", "kind", "title", "name", "uuid", "aliases", "status", "tags", "player", "player_name", "pack",
              "tier", "tier_since", "client_eval", "client_eval_since", "created", "updated", "revision", "by",
              "supersedes", "superseded_by", "archived_reason", "archived_at", "corrections")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
DUP_JACCARD = 0.85          # title word overlap at or above which save() refuses a near-duplicate
TMP_PREFIX, TMP_SUFFIX = ".tmp-", ".part"   # never matches the "*.md" memory glob
STALE_TMP_SECONDS = 600     # a temp file this old belongs to a writer that died; removed when a Store opens
STOP = set("a an and are at be by can do does for from how i in is it its me my of on or the to what when "
           "where which who why with you your".split())


class MemoryStoreError(Exception):
    """A user-facing error: the message is shown to Dave as-is."""


class DuplicateError(MemoryStoreError):
    def __init__(self, existing_id, title):
        super().__init__("A memory with a near-identical title already exists: %s (\"%s\"). Use memory_update "
                         "on it instead of saving a new one, or pass supersedes=%s if this replaces it."
                         % (existing_id, title, existing_id))
        self.existing_id = existing_id


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_uuid(s):
    h = s.replace("-", "").lower()
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:])


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s[:60].rstrip("-") or "memory")


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOP]


# ---------------------------------------------------------------- file format

_INT = re.compile(r"^-?\d+$")


def _dump(v):
    if isinstance(v, bool) or isinstance(v, (int, float)) or isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    if (not s or s != s.strip() or "\n" in s or s[0] in "[{\"'#" or _INT.match(s)
            or s in ("true", "false", "null")):
        return json.dumps(s, ensure_ascii=False)
    return s


def _load(raw):
    raw = raw.strip()
    if raw[:1] in ("[", "{", "\"") or raw in ("true", "false", "null") or _INT.match(raw):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def parse(text):
    """Splits a memory file into (meta dict, body)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            meta[k.strip()] = _load(v)
    return meta, text[end + 5:].lstrip("\n")


def render(meta, body):
    keys = [k for k in META_ORDER if k in meta] + sorted(k for k in meta if k not in META_ORDER)
    lines = ["%s: %s" % (k, _dump(meta[k])) for k in keys if meta[k] not in (None, "", [])]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.strip() + "\n"


# ---------------------------------------------------------------- ranking

def bm25_rank(query, docs, k1=1.5, b=0.75):
    """Default ranker: BM25 over title (x3) + tags (x2) + body. docs: dicts with "title", "tags", "body".

    Returns [(score, doc), ...] best first, only docs with a positive score.
    """
    q = list(dict.fromkeys(tokens(query)))
    if not q or not docs:
        return []
    bags = []
    for d in docs:
        toks = tokens(d.get("title")) * 3 + tokens(" ".join(d.get("tags") or [])) * 2 + tokens(d.get("body"))
        bag = {}
        for t in toks:
            bag[t] = bag.get(t, 0) + 1
        bags.append((bag, len(toks)))
    n = len(docs)
    avg = sum(length for _, length in bags) / n or 1.0
    df = {t: sum(1 for bag, _ in bags if t in bag) for t in q}
    out = []
    for d, (bag, length) in zip(docs, bags):
        score = 0.0
        for t in q:
            f = bag.get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * length / avg))
        if score > 0:
            out.append((score, d))
    out.sort(key=lambda x: -x[0])
    return out


# ---------------------------------------------------------------- store

class Store:
    """All reads and writes of Dave's memories. Safe for several processes (fcntl lock + atomic rename)."""

    def __init__(self, root, pack, actor="dave"):
        self.root = Path(root)
        self.pack = str(pack)
        self.actor = actor
        # Ranking hook. recall() calls self.ranker(query, docs) -> [(score, doc), ...] best first.
        # Swap in semantic or hybrid ranking here: tools/gtnh-search will index data/memory/playbook/ as kind
        # "playbook"; a ranker that asks it for playbook hits and merges them with bm25_rank for the other
        # kinds needs no change anywhere else.
        self.ranker = bm25_rank
        for kind in KINDS:
            (self.root / kind).mkdir(parents=True, exist_ok=True)
        self.clean_temp_files()

    def clean_temp_files(self, max_age=STALE_TMP_SECONDS):
        """Removes temp files left by writers that died mid-write. Young ones may be a live write: kept."""
        now = time.time()
        removed = []
        dirs = [self.root] + [self.root / k for k in KINDS] + sorted((self.root / ".objects").glob("*"))
        for d in dirs:
            for p in d.glob(TMP_PREFIX + "*"):
                try:
                    if now - p.lstat().st_mtime >= max_age:
                        p.unlink()
                        removed.append(p)
                except OSError:
                    continue
        return removed

    # ---- low level

    def _path(self, mem_id):
        kind, _, name = mem_id.partition("/")
        if kind not in KINDS or not name or "/" in name or name.startswith(".") or ".." in name:
            raise MemoryStoreError("Not a memory id: %r. Ids look like playbook/some-title." % mem_id)
        return self.root / kind / (name + ".md")

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _save_object(self, text):
        h = sha(text)
        p = self.root / ".objects" / h[:2] / (h + ".md")
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(p, text)
        return h

    @staticmethod
    def _atomic_write(path, text):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TMP_PREFIX, suffix=TMP_SUFFIX)
        try:
            os.fchmod(fd, 0o644)          # mkstemp makes 0600; memories are plain shared files
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _write(self, mem_id, meta, body, op, by=None, note=None, player=None, asked_by=None):
        """Writes one memory. Caller holds the lock. Logs the change; the caller regenerates the index.

        by = the process that wrote (dave, daemon, owner); asked_by = the player whose request it was.
        """
        path = self._path(mem_id)
        before = None
        if path.exists():
            before = self._save_object(path.read_text(encoding="utf-8"))
        meta["id"] = mem_id
        text = render(meta, body)
        after = self._save_object(text)
        self._atomic_write(path, text)
        entry = {"ts": now_iso(), "by": by or self.actor, "op": op, "id": mem_id, "before": before, "after": after}
        if player:
            entry["player"] = player
        if asked_by:
            entry["asked_by"] = asked_by
        if note:
            entry["note"] = note
        with open(self.root / ".log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return after

    def _read(self, mem_id):
        path = self._path(mem_id)
        if not path.exists():
            raise MemoryStoreError("No memory with id %s." % mem_id)
        meta, body = parse(path.read_text(encoding="utf-8"))
        meta.setdefault("kind", mem_id.split("/")[0])
        meta["id"] = mem_id
        return meta, body

    def _all(self, kind=None):
        out = []
        for k in ([kind] if kind else KINDS):
            for p in sorted((self.root / k).glob("*.md")):
                if p.name.startswith("."):       # temp files and other hidden files are never memories
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                except FileNotFoundError:        # replaced or removed by another process since the listing
                    continue
                meta, body = parse(text)
                meta.setdefault("kind", k)
                meta["id"] = "%s/%s" % (k, p.stem)
                out.append({"meta": meta, "body": body, "id": meta["id"], "title": meta.get("title") or
                            meta.get("name") or p.stem, "tags": meta.get("tags") or []})
        return out

    def status_of(self, meta):
        """Effective status: an active playbook entry from another pack version reads as stale."""
        status = meta.get("status") or "active"
        if status == "active" and meta.get("kind") == "playbook" and str(meta.get("pack") or "") != self.pack:
            return "stale"
        return status

    def _new_id(self, kind, title):
        base = slugify(title)
        mem_id, n = "%s/%s" % (kind, base), 2
        while self._path(mem_id).exists():
            mem_id, n = "%s/%s-%d" % (kind, base, n), n + 1
        return mem_id

    def _find_duplicate(self, kind, title, ignore=()):
        # Word sets, not characters: "nitrogen at HV" and "nitrogen at EV" are different questions.
        t = set(tokens(title))
        for m in self._all(kind):
            if m["id"] in ignore or self.status_of(m["meta"]) in ("superseded", "archived"):
                continue
            other = set(tokens(m["title"]))
            if t and len(t & other) / len(t | other) >= DUP_JACCARD:
                return m
        return None

    # ---- players

    def find_player(self, player):
        """Returns the profile id for a UUID or a (case-insensitive) current or former name, or None."""
        player = (player or "").strip()
        if not player:
            return None
        if UUID_RE.match(player):
            mem_id = "players/" + norm_uuid(player)
            return mem_id if self._path(mem_id).exists() else None
        low = player.lower()
        for m in self._all("players"):
            names = [m["meta"].get("name") or ""] + list(m["meta"].get("aliases") or [])
            if any(n.lower() == low for n in names):
                return m["id"]
        return None

    def _player_ref(self, player):
        """(uuid-or-name, display name) for recording who asked or corrected."""
        if not player:
            return None, None
        pid = self.find_player(player)
        if pid:
            meta, _ = self._read(pid)
            return meta.get("uuid") or pid.split("/")[1], meta.get("name") or player
        return player, (None if UUID_RE.match(player) else player)

    def ensure_player(self, uuid, name, by=None):
        """For the daemon: creates the profile on first sight and tracks renames. Returns the profile id."""
        uuid = norm_uuid(uuid)
        mem_id = "players/" + uuid
        with self._locked():
            if self._path(mem_id).exists():
                meta, body = self._read(mem_id)
                if name and meta.get("name") != name:
                    aliases = list(meta.get("aliases") or [])
                    if meta.get("name") and meta["name"] not in aliases:
                        aliases.append(meta["name"])
                    meta.update(name=name, aliases=aliases, updated=now_iso(),
                                revision=int(meta.get("revision") or 1) + 1)
                    self._write(mem_id, meta, body, "rename", by, note="name is now " + name)
                    self.write_index()
                return mem_id
            meta = {"kind": "players", "name": name or uuid, "uuid": uuid, "status": "active", "pack": self.pack,
                    "created": now_iso(), "updated": now_iso(), "revision": 1, "by": by or self.actor}
            self._write(mem_id, meta, "# %s\n" % (name or uuid), "create", by)
            self.write_index()
            return mem_id

    def player_note(self, player, fact, field="notes", by=None, name=None, asked_by=None):
        field = field or "notes"
        if field not in PLAYER_FIELDS:
            raise MemoryStoreError("Unknown field %r. Use one of: %s." % (field, ", ".join(PLAYER_FIELDS)))
        fact = " ".join((fact or "").split())
        if not fact:
            raise MemoryStoreError("fact is required.")
        pid = self.find_player(player)
        if pid is None:
            if not UUID_RE.match(player or ""):
                raise MemoryStoreError("No profile for %r. Pass the player's UUID (from the <player> tag) to create "
                                   "one." % player)
            pid = self.ensure_player(player, name, by)
        with self._locked():
            meta, body = self._read(pid)
            sections = _sections(body)
            heading = FIELD_HEADINGS[field]
            bullet = "- %s (since %s)" % (fact, today())
            if PLAYER_FIELDS[field] == "single":
                meta[field], meta[field + "_since"] = fact, today()
                sections[heading] = [bullet]
            else:
                existing = sections.setdefault(heading, [])
                if any(re.sub(r" \(since [^)]*\)$", "", b)[2:].lower() == fact.lower() for b in existing):
                    return pid, "already noted"
                existing.append(bullet)
            meta.update(updated=now_iso(), revision=int(meta.get("revision") or 1) + 1)
            self._write(pid, meta, _join_sections(meta.get("name") or pid, sections), "note", by,
                        note="%s: %s" % (field, fact), asked_by=asked_by)
            self.write_index()
        return pid, "noted"

    # ---- generic memories

    def get(self, mem_id):
        meta, body = self._read(mem_id)
        return meta, body, self.status_of(meta)

    def save(self, kind, title, body, tags=None, player=None, supersedes=None, by=None, asked_by=None):
        if kind == "players":
            raise MemoryStoreError("Player profiles are written with player_note, not memory_save.")
        if kind not in KINDS:
            raise MemoryStoreError("kind must be one of: %s." % ", ".join(k for k in KINDS if k != "players"))
        title = " ".join((title or "").split())
        if not title or not (body or "").strip():
            raise MemoryStoreError("title and body are required.")
        with self._locked():
            if supersedes:
                old_meta, old_body = self._read(supersedes)
            dup = self._find_duplicate(kind, title, ignore=(supersedes,) if supersedes else ())
            if dup:
                raise DuplicateError(dup["id"], dup["title"])
            mem_id = self._new_id(kind, title)
            pref, pname = self._player_ref(player)
            meta = {"kind": kind, "title": title, "status": "active", "tags": _clean_tags(tags), "player": pref,
                    "player_name": pname, "pack": self.pack, "created": now_iso(), "updated": now_iso(),
                    "revision": 1, "by": by or self.actor, "supersedes": supersedes}
            asked_by = asked_by or player
            self._write(mem_id, meta, body, "save", by, player=pref, asked_by=asked_by)
            if supersedes:
                old_meta.update(status="superseded", superseded_by=mem_id, updated=now_iso(),
                                revision=int(old_meta.get("revision") or 1) + 1)
                self._write(supersedes, old_meta, old_body, "supersede", by, note="superseded by " + mem_id,
                            asked_by=asked_by)
            self.write_index()
        return mem_id

    def update(self, mem_id, body=None, title=None, tags=None, status=None, reverify=False, by=None, note=None,
               asked_by=None):
        if status not in (None, "active", "stale"):
            raise MemoryStoreError("status can only be set to active or stale here; use memory_forget to archive "
                               "and memory_correct or memory_save(supersedes=...) to supersede.")
        with self._locked():
            meta, old_body = self._read(mem_id)
            if title:
                meta["title"] = " ".join(title.split())
            if tags is not None:
                meta["tags"] = _clean_tags(tags)
            if status:
                meta["status"] = status
            if reverify:
                meta["pack"], meta["status"] = self.pack, "active"
            meta.update(updated=now_iso(), revision=int(meta.get("revision") or 1) + 1)
            self._write(mem_id, meta, old_body if body is None else body, "update", by, note=note, asked_by=asked_by)
            self.write_index()
        return mem_id

    def correct(self, mem_id, correction, by_player, body=None, by=None):
        """Records a player's correction. Playbook: writes a corrected entry and supersedes the old one.

        Other kinds are corrected in place (new revision). Returns the id holding the corrected memory.
        """
        correction = (correction or "").strip()
        if not correction or not by_player:
            raise MemoryStoreError("correction and by_player are required.")
        pref, pname = self._player_ref(by_player)
        corr = {"by": pname or pref, "uuid": pref if pref and UUID_RE.match(pref) else None, "at": now_iso(),
                "text": correction}
        corr = {k: v for k, v in corr.items() if v}
        with self._locked():
            meta, old_body = self._read(mem_id)
            if self.status_of(meta) in ("superseded", "archived"):
                raise MemoryStoreError("%s is %s; correct %s instead." % (
                    mem_id, self.status_of(meta), meta.get("superseded_by") or "the current entry"))
            corrections = list(meta.get("corrections") or []) + [corr]
            note_line = "Corrected by %s on %s: %s" % (corr["by"], today(), correction)
            if body is not None:
                new_body = body
            elif meta.get("kind") == "players":  # profiles are sections; keep the shape player_note rewrites
                sections = _sections(old_body)
                sections.setdefault("Corrections", []).append("- " + note_line)
                new_body = _join_sections(meta.get("name") or mem_id, sections)
            else:
                new_body = old_body.rstrip() + "\n\n" + note_line
            if meta.get("kind") == "playbook":
                new_id = self._new_id("playbook", meta.get("title") or "answer")
                new_meta = {k: v for k, v in meta.items() if k not in ("superseded_by", "archived_reason")}
                new_meta.update(status="active", pack=self.pack, created=now_iso(), updated=now_iso(), revision=1,
                                by=by or self.actor, supersedes=mem_id, corrections=corrections)
                self._write(new_id, new_meta, new_body, "correct", by, player=pref, note=correction, asked_by=by_player)
                meta.update(status="superseded", superseded_by=new_id, updated=now_iso(),
                            revision=int(meta.get("revision") or 1) + 1)
                self._write(mem_id, meta, old_body, "supersede", by, player=pref, note="corrected as " + new_id,
                            asked_by=by_player)
                result = new_id
            else:
                meta.update(corrections=corrections, updated=now_iso(), revision=int(meta.get("revision") or 1) + 1)
                self._write(mem_id, meta, new_body, "correct", by, player=pref, note=correction, asked_by=by_player)
                result = mem_id
            self.write_index()
        return result

    def forget(self, mem_id, reason, by=None, asked_by=None):
        reason = (reason or "").strip()
        if not reason:
            raise MemoryStoreError("reason is required.")
        with self._locked():
            meta, body = self._read(mem_id)
            if meta.get("status") == "archived":
                return mem_id
            meta.update(status="archived", archived_reason=reason, archived_at=now_iso(), updated=now_iso(),
                        revision=int(meta.get("revision") or 1) + 1)
            self._write(mem_id, meta, body, "forget", by, note=reason, asked_by=asked_by)
            self.write_index()
        return mem_id

    def recall(self, query, kind=None, player=None, k=8, include_stale=False):
        """Returns [(score, memory dict with "status")] for active (optionally stale) memories, best first."""
        if kind and kind not in KINDS:
            raise MemoryStoreError("kind must be one of: %s." % ", ".join(KINDS))
        allowed = ("active", "stale") if include_stale else ("active",)
        pref = None
        if player:
            pid = self.find_player(player)
            pref = pid.split("/")[1] if pid else player
        docs = []
        for m in self._all(kind):
            m["status"] = self.status_of(m["meta"])
            if m["status"] not in allowed:
                continue
            if pref and pref.lower() not in (str(m["meta"].get("player") or "").lower(),
                                             str(m["meta"].get("uuid") or "").lower(),
                                             str(m["meta"].get("player_name") or "").lower()):
                continue
            docs.append(m)
        return self.ranker(query, docs)[:max(1, int(k))]

    def list(self, kind, status=None):
        out = []
        for m in self._all(kind):
            st = self.status_of(m["meta"])
            if status in (None, "") and st in ("superseded", "archived"):
                continue
            if status not in (None, "", "all") and st != status:
                continue
            m["status"] = st
            out.append(m)
        return out

    def write_index(self):
        lines = ["# Dave's memory index", "",
                 "Generated on every write; do not edit by hand. One line per active memory. Stale playbook "
                 "entries (from another pack version) are flagged.", ""]
        for kind in KINDS:
            rows = []
            for m in self._all(kind):
                st = self.status_of(m["meta"])
                if st not in ("active", "stale"):
                    continue
                extra = ""
                if kind == "players" and m["meta"].get("tier"):
                    extra = " (tier %s)" % m["meta"]["tier"]
                if st == "stale":
                    extra += " [stale: pack %s]" % (m["meta"].get("pack") or "?")
                rows.append("- `%s` %s%s" % (m["id"], m["title"], extra))
            lines += ["## %s (%d)" % (kind, len(rows)), ""] + (rows or ["(none)"]) + [""]
        text = "\n".join(lines)
        path = self.root / "INDEX.md"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            self._atomic_write(path, text)

    def restore(self, mem_id, object_sha, by=None):
        """Writes an earlier version (by content hash from .log.jsonl) back as the current one."""
        p = self.root / ".objects" / object_sha[:2] / (object_sha + ".md")
        if not p.exists():
            raise MemoryStoreError("No stored version %s." % object_sha)
        meta, body = parse(p.read_text(encoding="utf-8"))
        with self._locked():
            self._write(mem_id, meta, body, "restore", by, note="restored " + object_sha)
            self.write_index()
        return mem_id


# ---------------------------------------------------------------- helpers

def _clean_tags(tags):
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    return sorted({t.strip().lower() for t in (tags or []) if t and t.strip()})


PREAMBLE = ""     # _sections key for text before the first "## " heading (free-form profile text)


def _sections(body):
    """Parses '## Heading' blocks of a profile body into {heading: [lines]} (order kept).

    Text before the first heading (other than the "# Name" title line) is kept under the key PREAMBLE, so a
    free-form body written with memory_update survives the next player_note.
    """
    out, cur, titled = {}, PREAMBLE, False
    for line in body.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out.setdefault(cur, [])
        elif cur == PREAMBLE and not titled and line.startswith("# "):
            titled = True                      # the profile's own title; _join_sections writes it again
        elif line.strip():
            out.setdefault(cur, []).append(line.rstrip())
    return out


def _join_sections(title, sections):
    order = [FIELD_HEADINGS[f] for f in ("tier", "base", "setup", "preferences", "client_eval", "notes")]
    keys = [h for h in order if sections.get(h)] + [h for h in sections if h not in order and h != PREAMBLE
                                                     and sections[h]]
    parts = ["# %s" % title]
    if sections.get(PREAMBLE):
        parts.append("\n".join(sections[PREAMBLE]))
    for h in keys:
        parts.append("## %s\n%s" % (h, "\n".join(sections[h])))
    return "\n\n".join(parts) + "\n"


def format_profile(meta, body, limit=None):
    """A compact one-block rendering of a player profile for prompts."""
    head = "%s (uuid %s)" % (meta.get("name") or "?", meta.get("uuid") or "?")
    if meta.get("aliases"):
        head += ", formerly " + ", ".join(meta["aliases"])
    lines = [head]
    for h, items in _sections(body).items():
        lines.append("%s: %s" % (h or "About", "; ".join(i.lstrip("- ") for i in items)))
    text = "\n".join(lines)
    return text if limit is None or len(text) <= limit else text[:limit - 3].rstrip() + "..."


def snippet(body, n=240):
    s = " ".join(body.split())
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def open_store(cfg=None, actor=None):
    """A Store built from dave/config.toml (env overrides apply)."""
    if cfg is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from dave import config
        cfg = config.load()
    return Store(cfg["paths"]["memory"], cfg["pack"]["version"], actor or os.environ.get("DAVE_MEMORY_ACTOR", "dave"))


def load_turn_context(player_uuid, query=None, player_name=None, limit=1500, store=None):
    """For the daemon: the text that goes in the per-turn <profile> block. Read-only, capped at `limit` chars.

    The player's profile, then pinned and relevant server facts, then relevant lessons, then pointers to
    playbook entries that look related to `query` (the player's message). Lower-priority parts are dropped
    first when over the cap.
    """
    store = store or open_store()
    parts = []
    pid = store.find_player(player_uuid) if player_uuid else None
    if pid is None and player_name:
        pid = store.find_player(player_name)
    if pid:
        meta, body = store._read(pid)
        parts.append("Player: " + format_profile(meta, body, limit=700))
    else:
        parts.append("Player: %s - no profile yet." % (player_name or player_uuid or "unknown"))

    def pick(kind, n):
        active = [m for m in store._all(kind) if store.status_of(m["meta"]) == "active"]
        pinned = [m for m in active if "pinned" in (m["tags"] or [])]
        ranked = [d for _, d in store.ranker(query, active)] if query else []
        seen, out = set(), []
        for m in pinned + ranked:
            if m["id"] not in seen:
                seen.add(m["id"])
                out.append(m)
        return out[:n]

    facts = pick("server", 3)
    if facts:
        parts.append("Server facts:\n" + "\n".join("- %s: %s" % (m["title"], snippet(m["body"], 160)) for m in facts))
    lessons = pick("lessons", 3)
    if lessons:
        parts.append("Lessons:\n" + "\n".join("- %s: %s" % (m["title"], snippet(m["body"], 160)) for m in lessons))
    if query:
        hits = store.recall(query, kind="playbook", k=2)
        if hits:
            parts.append("Maybe related playbook: " + "; ".join("%s (%s)" % (d["title"], d["id"]) for _, d in hits))
    out = ""
    for p in parts:
        cand = (out + "\n\n" + p) if out else p
        if len(cand) > limit:
            break
        out = cand
    return out or parts[0][:limit]


def main(argv):
    store = open_store(actor="owner")
    if argv[:1] == ["index"]:
        store.write_index()
        print("wrote", store.root / "INDEX.md")
    elif argv[:1] == ["log"]:
        n = int(argv[1]) if len(argv) > 1 else 20
        log = store.root / ".log.jsonl"
        for line in (log.read_text().splitlines()[-n:] if log.exists() else []):
            print(line)
    elif argv[:1] == ["restore"] and len(argv) == 3:
        print("restored", store.restore(argv[1], argv[2]))
    else:
        print(__doc__.strip().splitlines()[-1])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
