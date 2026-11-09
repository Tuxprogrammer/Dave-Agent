"""Semantic search over GT New Horizons knowledge for Dave: corpus sources, chunking, embedding and the on-disk index.

Everything read from the pack, the wiki or memory files is untrusted data: it is parsed as text, never executed.
"""

import base64
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import struct
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import numpy as np

API_URL = "https://openrouter.ai/api/v1/embeddings"
MAX_CHARS = 6000
MIN_CHARS = 400
SNIPPET_CHARS = 1500
BATCH_INPUTS = 64
BATCH_CHARS = 200_000
WORKERS = 4
# Document embedding (builds) may wait; a player's query must not. Attempts include the first try.
DOC_ATTEMPTS, DOC_TIMEOUT = 7, 180
QUERY_ATTEMPTS, QUERY_TIMEOUT = 2, 20
# A build saves the vectors embedded so far after every this many chunks, so a failure doesn't lose paid work.
CHECKPOINT_CHUNKS = 1024
# Bump when an extractor's output changes, so cached docs.jsonl files are rebuilt.
EXTRACT_VERSION = 1

# Index profiles. Each has its own model and index file, so the later `code` index (a code model over real source)
# can sit beside the prose one without a refactor: add an entry here and a source per kind it covers.
PROFILES = {
    "prose": {
        # Provisional: pick the model with eval.py, then change it here (a new model starts a new index file).
        "model": "voyageai/voyage-4",
        "kinds": ("quest", "guide", "wiki", "item", "lang", "playbook", "memory"),
    },
}
DEFAULT_PROFILE = "prose"

# Per-model request quirks, matched by prefix. Models without input_type support take an instruction prefix instead.
MODEL_OPTIONS = {
    "qwen/qwen3-embedding": {
        "input_type": False,
        "query_prefix": "Instruct: Given a GT New Horizons player question, retrieve passages that answer it\nQuery: ",
    },
}

# Kinds that crowd out prose in a mixed search are capped to a share of the slots (lang chunks are long key=value
# lists that match item names strongly).
MIXED_SHARE = {"lang": 3}
KINDS = ("quest", "guide", "wiki", "item", "lang", "playbook", "memory")
SKIP_MEMORY_STATUS = {"archived", "superseded"}


# Locations. Every directory can be overridden by an environment variable, so a Docker image can bake the corpus and
# index in at another path, read-only.

def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def repo_root():
    if os.environ.get("GTNH_SEARCH_ROOT"):
        return Path(os.environ["GTNH_SEARCH_ROOT"]).resolve()
    return Path(__file__).resolve().parents[2]


def find_pack(root):
    """The extracted server pack: GTNH_PACK_DIR, else the newest .work/gtnh-*/pack with a mods/ folder."""
    if os.environ.get("GTNH_PACK_DIR"):
        p = Path(os.environ["GTNH_PACK_DIR"])
        return p if p.is_dir() else None
    found = sorted(p for p in (root / ".work").glob("gtnh-*/pack") if (p / "mods").is_dir())
    return found[-1] if found else None


class Context:
    """Where a build reads from and writes to. Tests point every path at a temporary directory.

    With a state directory (GTNH_SEARCH_STATE, a writable volume in the container), the corpus and index live in
    <state>/corpus and <state>/index, and GTNH_SEARCH_DATA / GTNH_SEARCH_INDEX_DIR name the read-only seed baked into
    the image, which seed() copies into the state directory."""

    def __init__(self, root=None, pack=None, corpus=None, index=None, memory=None, gtsrc=None, readonly=None, state=None,
                 tuxmine=None, jar_cache=None):
        self.root = Path(root) if root else repo_root()
        self.pack = Path(pack) if pack else find_pack(self.root)
        # Our extra mods: the tuxmine packwiz packs layered on the GTNH pack, and the cache packstate downloads their
        # URL mods into. Both absent in the image.
        self.tuxmine = Path(tuxmine or os.environ.get("TUXMINE_DIR") or self.root / "tuxmine")
        self.jar_cache = Path(jar_cache or os.environ.get("TUXMINE_JAR_CACHE") or self.root / ".work" / "tuxmine-jars")
        self._extras = (None, [], None)
        # Per cached kind, the packs its docs were extracted from: {"pack": packstate fingerprint, "pack_label": text}.
        self.extracted = {}
        self.seed_corpus = Path(corpus or os.environ.get("GTNH_SEARCH_DATA") or self.root / "data" / "corpus")
        self.seed_index = Path(index or os.environ.get("GTNH_SEARCH_INDEX_DIR") or self.root / "data" / "index")
        state = state or os.environ.get("GTNH_SEARCH_STATE")
        self.state = Path(state) if state else None
        self.corpus = self.state / "corpus" if self.state else self.seed_corpus
        self.index = self.state / "index" if self.state else self.seed_index
        self.wiki_dir = self.corpus / "wiki"
        self.memory = Path(memory or os.environ.get("GTNH_MEMORY_DIR") or self.root / "data" / "memory")
        if gtsrc is None:
            gtsrc = [self.root / "gtnh-src" / "source" / "GT5-Unofficial", self.root / "gtnh-src" / "mods" / "gregtech"]
        self.gtsrc = [Path(p) for p in gtsrc]
        self.readonly = env_flag("GTNH_SEARCH_READONLY") if readonly is None else readonly
        self._names = None

    def config_dir(self):
        """The pack's config/, falling back to the copy in gtnh-src/config."""
        for p in (self.pack / "config" if self.pack else None, self.root / "gtnh-src" / "config"):
            if p and p.is_dir():
                return p
        return None

    def jars(self):
        if not self.pack or not (self.pack / "mods").is_dir():
            return []
        return sorted((self.pack / "mods").rglob("*.jar"))

    def has_pack(self):
        return bool(self.pack and self.pack.is_dir())

    def extra_jars(self):
        """The tuxmine packs' jars, as packstate.jars() lists them (name, sha256, packs, path; path is None for a URL
        mod not downloaded yet). Only alongside a GTNH pack; empty without tuxmine/ (the image). Memoized on the
        packs' and the jar cache's file listings, so a long-lived server notices a pack change."""
        return self._extra_state()[1]

    def extras_error(self):
        return self._extra_state()[2]

    def _extra_state(self):
        sides = [self.tuxmine / side for side in ("server", "client")]
        if not self.has_pack() or not any((d / "index.toml").is_file() for d in sides):
            return (None, [], None)
        key = tuple((str(d), tuple(file_listing(d))) for d in [*sides, *(d / "mods" for d in sides), self.jar_cache])
        if self._extras[0] == key:
            return self._extras
        ps, jars, error = load_packstate(), [], None
        try:
            if ps is None:
                raise RuntimeError("tools/packstate.py could not be loaded (it needs Python 3.11 or newer)")
            jars = ps.jars(tuxmine=self.tuxmine, cache=self.jar_cache)
        except (Exception, SystemExit) as e:  # a broken pack must not take a refresh down; it blocks stamping instead
            jars, error = [], "tuxmine jars: %s" % e
        self._extras = (key, jars, error)  # replaced, never mutated: copy.copy(ctx) shares it
        return self._extras

    def extra_inputs(self):
        """Fingerprint tokens for the tuxmine jars: each jar's name and sha256, and whether its file can be read."""
        out = ["tuxmine:%s:%s:%s" % (e["name"], e["sha256"], "ok" if e["path"] else "missing") for e in self.extra_jars()]
        if self.extras_error():
            out.append("tuxmine:error")
        return out

    def note_extracted(self, kind, header):
        # Replaced, never mutated: copy.copy(ctx) (the living wiki's build) must not write into the original's dict.
        self.extracted = dict(self.extracted, **{kind: {"pack": header.get("pack"), "pack_label": header.get("pack_label")}})

    def names(self):
        """Item names for this pass. corpus_chunks() resets them, so a long-lived server never renders with stale names."""
        if self._names is None:
            self._names = Names(self)
        return self._names

    def writable(self):
        """False in read-only mode or when the index directory cannot be written (a baked-in image)."""
        if self.readonly:
            return False
        p = self.index
        while not p.exists():
            p = p.parent
        return os.access(p, os.W_OK)

    def living_wiki(self):
        """The living wiki's git repo (tools/living-wiki): GTNH_WIKI_GIT, else <state or data>/wiki-git."""
        if os.environ.get("GTNH_WIKI_GIT"):
            return Path(os.environ["GTNH_WIKI_GIT"])
        return (self.state or self.corpus.parent) / "wiki-git"

    def jobs_lock(self):
        """One lock for jobs that replace whole directories (seed, update_wiki). Outside the swapped directories."""
        return (self.state or self.index) / "jobs.lock"


@contextmanager
def file_lock(path, blocking=False):
    """Yields True while holding an exclusive flock on path, or False when another process holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


@contextmanager
def corpus_lock(ctx, profile=DEFAULT_PROFILE):
    """Waits for the profile's build lock, for commands that may rewrite the extraction caches outside build().
    Read-only contexts write nothing and take no lock."""
    if not ctx.writable():
        yield True
        return
    with file_lock(index_path(ctx, profile).with_suffix(".lock"), blocking=True) as held:
        yield held


def fsync_dir(d):
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def atomic_file(path, mode="w", encoding="utf-8"):
    """Yields a file object for a unique temporary file beside path; on success it is fsynced and renamed over path.
    Concurrent writers never share a temporary file, and a crash leaves either the old or the new file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        os.chmod(tmp, 0o644)
        with os.fdopen(fd, mode, encoding=None if "b" in mode else encoding) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(path.parent)


# Staging directories beside a target: ".<name>.old" is the fixed name swap_dir, recover_dir and live_dir rely on;
# every other tag gets a fresh unique directory (".<name>.<tag>.<random>"), so concurrent jobs never share one.
STAGING = re.compile(r"^\..+\.(?:new|import|download)\.[\w-]+$|^\..+\.old$")


def staged(target, tag):
    """A staging path beside target. For "old" the fixed recovery name (not created); for any other tag a new, empty,
    unique directory. Callers may delete it and write the same path again."""
    if tag == "old":
        return target.with_name(".%s.old" % target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".%s.%s." % (target.name, tag), dir=target.parent))


def sweep_staged(target, max_age=6 * 3600):
    """Removes unique staging directories of target left behind by a killed job (older than max_age seconds)."""
    if not target.parent.is_dir():
        return
    now = time.time()
    for p in target.parent.glob(".%s.*.*" % glob_escape(target.name)):
        try:
            if p.is_dir() and STAGING.match(p.name) and not p.name.endswith(".old") and now - p.stat().st_mtime > max_age:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def glob_escape(name):
    return re.sub(r"([*?\[])", r"[\1]", name)


def ignore_staging(_dir, names):
    """shutil.copytree ignore function: lock files, temporary files, checkpoints and staging directories."""
    return {n for n in names if n.endswith((".lock", ".tmp", ".tmp.npz", ".partial.npz", ".corrupt")) or STAGING.match(n)}


def swap_dir(new, target):
    """Replaces target with the fully written directory new. If a crash lands between the two renames, readers fall
    back to the .old copy (live_dir) and recover_dir puts it back."""
    old = staged(target, "old")
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        os.rename(target, old)
    os.rename(new, target)
    shutil.rmtree(old, ignore_errors=True)


def recover_dir(target):
    old = staged(target, "old")
    if not target.exists() and old.is_dir():
        os.rename(old, target)


def live_dir(target):
    old = staged(target, "old")
    return old if not target.exists() and old.is_dir() else target


def seed_stamp(ctx):
    """Identifies the baked seed: its file list with sizes and mtimes (image layers keep mtimes)."""
    files = []
    for d in (ctx.seed_corpus, ctx.seed_index):
        if d.is_dir():
            files += [f for f in d.rglob("*") if f.is_file()
                      and not any(ignore_staging(None, [part]) for part in f.relative_to(d).parts)]
    return fingerprint(files) if files else None


def seed(ctx, force=False, log=lambda s: None):
    """Copies the baked corpus and index into the state directory when it lacks them or holds an older seed.
    Returns True when it copied, False when already current, None when it could not run.

    Once the volume has a living wiki (<state>/wiki-git), its wiki is the source of truth: a re-seed keeps the volume's
    corpus/wiki snapshot, and a newer official dump in the image goes through the living wiki's merge (update_wiki.py),
    never a copy."""
    if not ctx.state:
        return None
    stamp = seed_stamp(ctx)
    if stamp is None:
        log("no seed corpus or index at %s, %s" % (ctx.seed_corpus, ctx.seed_index))
        return None
    marker = ctx.state / "seed.json"
    try:
        current = json.loads(marker.read_text()) if marker.is_file() else {}
    except (OSError, ValueError):
        current = {}
    if not force and current.get("stamp") == stamp and ctx.corpus.is_dir() and ctx.index.is_dir():
        return False
    with file_lock(ctx.jobs_lock()) as held:
        if not held:
            log("another job holds %s; seed skipped" % ctx.jobs_lock())
            return None
        for src, dst in ((ctx.seed_corpus, ctx.corpus), (ctx.seed_index, ctx.index)):
            recover_dir(dst)
            sweep_staged(dst)
            tmp = staged(dst, "new")
            if src.is_dir():
                shutil.copytree(src, tmp, ignore=ignore_staging, dirs_exist_ok=True)
            keep = live_dir(dst / "wiki")
            if dst == ctx.corpus and (ctx.living_wiki() / ".git").is_dir() and keep.is_dir():
                shutil.rmtree(tmp / "wiki", ignore_errors=True)
                shutil.copytree(keep, tmp / "wiki", ignore=ignore_staging)
            swap_dir(tmp, dst)
        with atomic_file(marker) as f:
            f.write(json.dumps({"stamp": stamp, "seeded_at": int(time.time()),
                                "from": [str(ctx.seed_corpus), str(ctx.seed_index)]}))
    log("seeded %s from %s and %s" % (ctx.state, ctx.seed_corpus, ctx.seed_index))
    return True


def file_listing(d):
    """(name, size, mtime) of each file directly in d; empty when d is missing."""
    out = []
    try:
        entries = list(os.scandir(d))
    except OSError:
        return out
    for e in entries:
        try:
            if e.is_file():
                st = e.stat()
                out.append((e.name, st.st_size, st.st_mtime_ns))
        except OSError:
            continue
    return sorted(out)


# Pack freshness. tools/packstate.py lists the tuxmine jars and records which packs each derived artifact was built
# from (stamps). Each cached kind's docs.jsonl header carries the packstate fingerprint it was extracted from, and an
# index carries those of the docs it embedded, so a stamp can only vouch for data really built from the current packs.

_PACKSTATE = []


def load_packstate():
    """tools/packstate.py as a module, or None where it is missing or cannot load (it needs Python 3.11's tomllib).
    Loaded by path, so neither python3 -I nor the caller's sys.path matters."""
    if not _PACKSTATE:
        try:
            spec = importlib.util.spec_from_file_location("dave_packstate", Path(__file__).resolve().parents[1] / "packstate.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001  (a missing file or an old Python: no stamps and no tuxmine jars)
            mod = None
        _PACKSTATE.append(mod)
    return _PACKSTATE[0]


def pack_identity(ctx):
    """(identity, None) for the packs ctx extracts from, identity being {"fingerprint": packstate's corpus fingerprint,
    "label": "GTNH 2.9.0, tuxmine server 0.1.23, client 0.1.21"}; or (None, reason) when a stamp would not be truthful:
    no GTNH pack (the image), packstate unavailable or resolving other directories than ctx (set DAVE_AGENT_ROOT like
    GTNH_SEARCH_ROOT), or a tuxmine jar that is not downloaded or not readable."""
    if not ctx.has_pack():
        return None, "no GTNH pack"
    ps = load_packstate()
    if ps is None:
        return None, "tools/packstate.py could not be loaded"
    try:
        theirs = ps.gtnh_pack_dir()
        if theirs is None or Path(theirs).resolve() != ctx.pack.resolve():
            return None, "packstate sees the GTNH pack at %s, the corpus reads %s" % (theirs, ctx.pack)
        if Path(ps.tuxmine_dir()).resolve() != ctx.tuxmine.resolve():
            return None, "packstate sees tuxmine at %s, the corpus reads %s" % (ps.tuxmine_dir(), ctx.tuxmine)
        if ctx.extras_error():
            return None, ctx.extras_error()
        missing = [e["name"] for e in ctx.extra_jars() if not e["path"]]
        if missing:
            return None, "tuxmine jars not downloaded: %s" % ", ".join(missing)
        st = ps.state()
    except (Exception, SystemExit) as e:
        return None, "packstate failed: %s" % e
    if not st.get("gtnh_version"):
        return None, "unknown GTNH version"
    tux = ", ".join("%s %s" % (side, st["tuxmine"][side]["version"]) for side in ("server", "client") if st["tuxmine"].get(side))
    return {"fingerprint": st["fingerprints"]["corpus"],
            "label": "GTNH %s" % st["gtnh_version"] + (", tuxmine " + tux if tux else "")}, None


def fetch_extras(ctx, log=lambda s: None):
    """Downloads the tuxmine packs' URL mods into the jar cache (sha256-checked by packstate), so an extraction reads
    every jar. Returns an error message, or None, also when there is nothing to fetch (no pack, no tuxmine/)."""
    if not ctx.has_pack() or not any((ctx.tuxmine / side / "index.toml").is_file() for side in ("server", "client")):
        return None
    ps = load_packstate()
    if ps is None:
        return "tools/packstate.py could not be loaded (it needs Python 3.11 or newer)"
    try:
        jars = ps.jars(fetch=True, tuxmine=ctx.tuxmine, cache=ctx.jar_cache)
    except (Exception, SystemExit) as e:
        return "fetching the tuxmine jars failed: %s" % e
    log("tuxmine: %d jars (%d of them URL mods, in %s)" % (len(jars), sum(e["origin"] == "url" for e in jars), ctx.jar_cache))
    return None


def pack_kinds(profile=DEFAULT_PROFILE):
    """The profile's kinds extracted from the packs (the cached ones); wiki, playbook and memory are not pack data."""
    return [k for k in PROFILES[profile]["kinds"] if SOURCES[k].cache]


def stale_kinds(extracted, fingerprint_now, profile=DEFAULT_PROFILE):
    """Pack kinds whose docs were not extracted from the packs with fingerprint_now. extracted: {kind: fingerprint}."""
    return [k for k in pack_kinds(profile) if not fingerprint_now or (extracted or {}).get(k) != fingerprint_now]


def stamp_pack(ctx, component, fingerprint_now, note=None):
    """packstate.stamp(component), kept only if the packs still have fingerprint_now: if they changed while it was
    written, the stamp is removed, so it never vouches for data built from other packs. Returns the record or None."""
    ps = load_packstate()
    rec = ps.stamp(component, note)
    if rec["fingerprint"] != fingerprint_now:
        try:
            (ps.stamp_dir() / ("%s.json" % component)).unlink()
        except OSError:
            pass
        return None
    return rec


def index_path(ctx, profile=DEFAULT_PROFILE, model=None):
    model = model or PROFILES[profile]["model"]
    return ctx.index / ("%s__%s.npz" % (profile, model.replace("/", "_").replace(":", "_")))


def load_key(*roots):
    """OPENROUTER_API_KEY, else the file named by OPENROUTER_API_KEY_FILE (a runtime secret), else .env."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    if os.environ.get("OPENROUTER_API_KEY_FILE"):
        f = Path(os.environ["OPENROUTER_API_KEY_FILE"])
        try:
            key = f.read_text(encoding="utf-8").strip() if f.is_file() else ""
        except (OSError, UnicodeDecodeError):
            key = ""  # an unreadable secret is reported as "no key", never as a crash
        if key:
            return key
    for root in roots:
        env = Path(root) / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                name, _, value = line.partition("=")
                name = name.strip()
                if name.startswith("export "):
                    name = name[7:].strip()
                if name == "OPENROUTER_API_KEY" and value.strip():
                    return value.strip().strip("'\"")
    return None


# Source registry. Each kind has a discover function (inputs -> docs) and a chunker (doc -> chunks). A doc is
# {"key", "title", "text", "meta"}; "key" is the stable source id shown in hits and used by the eval set.

class Source:
    def __init__(self, kind, discover, chunk, inputs, cache, doc, deps=None):
        self.kind, self.discover, self.chunk, self.inputs, self.cache, self.doc = kind, discover, chunk, inputs, cache, doc
        self.deps = deps or (lambda ctx: [])


SOURCES = {}


def source(kind, inputs, chunk=None, cache=True, doc="", deps=None):
    """Registers a corpus source. cache=True stores the discovered docs in <corpus>/<kind>/docs.jsonl, keyed on a
    fingerprint of the inputs, so a refresh only re-reads the pack when it changed.

    inputs(ctx) lists the primary inputs (pack files); with none, the cache is used as is. deps(ctx) lists derived
    files the rendering also depends on (the lang cache, items.tsv, GregTech source): they only invalidate the cache
    when primary inputs exist, so a corpus without its pack (a baked image) is never re-extracted from them."""
    def deco(fn):
        SOURCES[kind] = Source(kind, fn, chunk or chunk_markdown, inputs, cache, doc, deps)
        return fn
    return deco


def fingerprint(paths):
    """Paths by name, size and mtime, plus plain-string tokens taken as they are (the tuxmine jars' sha256)."""
    h = hashlib.sha256(("v%d" % EXTRACT_VERSION).encode())
    items = set(paths)
    for p in sorted(x for x in items if not isinstance(x, str)):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(("%s\0%d\0%d\n" % (p, st.st_size, st.st_mtime_ns)).encode("utf-8", "replace"))
    for token in sorted(x for x in items if isinstance(x, str)):
        h.update(("%s\n" % token).encode("utf-8", "replace"))
    return h.hexdigest()[:24]


def write_jsonl(path, header, rows):
    with atomic_file(path) as f:
        f.write(json.dumps(header) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        header = json.loads(f.readline() or "{}")
        return header, [json.loads(l) for l in f if l.strip()]


def load_docs(ctx, kind, force=False, log=lambda s: None):
    """Docs for one kind, from the cache when its inputs are unchanged (or absent, as in a baked-in image)."""
    src = SOURCES[kind]
    if not src.cache:
        return list(src.discover(ctx))
    cache = ctx.corpus / kind / "docs.jsonl"
    header, cached = {}, None
    if cache.is_file():
        try:
            header, cached = read_jsonl(cache)
        except (OSError, ValueError) as e:
            log("%s: unreadable cache %s (%s); re-extracting" % (kind, cache, e))
    # Without the pack (a baked image) the cache is the corpus: never re-extract it from fallbacks or derived files.
    inputs = src.inputs(ctx) if ctx.has_pack() or cached is None or force else []
    if cached is not None and not force:
        if not inputs or ctx.readonly or header.get("fingerprint") == fingerprint(inputs + src.deps(ctx)):
            if inputs and not ctx.readonly:
                # The inputs cover everything discovery reads, so these docs are what the current packs give even when
                # the packs' identity moved for another reason (a tuxmine config file): record that identity.
                ident, _ = pack_identity(ctx)
                if ident and header.get("pack") != ident["fingerprint"]:
                    header = dict(header, pack=ident["fingerprint"], pack_label=ident["label"])
                    write_jsonl(cache, header, cached)
            ctx.note_extracted(kind, header)
            return cached
    if ctx.readonly or not inputs:
        if cached is not None:
            ctx.note_extracted(kind, header)
        return cached or []
    t0 = time.time()
    before, _ = pack_identity(ctx)
    docs = list(src.discover(ctx))
    if not docs and cached:
        log("%s: extraction found nothing; keeping the %d cached docs" % (kind, len(cached)))
        ctx.note_extracted(kind, header)
        return cached
    # Claims only packs that were the same before and after discovery; a pack changing mid-extraction claims none.
    after, _ = pack_identity(ctx)
    ident = before if before == after else None
    # Fingerprinted after discovery: discovering can refresh the derived files (the lang cache, gregtech.json).
    header = {"kind": kind, "fingerprint": fingerprint(src.inputs(ctx) + src.deps(ctx)),
              "extracted_at": int(time.time()), "docs": len(docs),
              "pack": ident and ident["fingerprint"], "pack_label": ident and ident["label"]}
    write_jsonl(cache, header, docs)
    ctx.note_extracted(kind, header)
    log("%s: extracted %d docs in %.1fs" % (kind, len(docs), time.time() - t0))
    return docs


# Text helpers

FORMAT_CODE = re.compile("§.")
BQ_TAG = re.compile(r"\[/?(?:warn|note|url|quest|i|b|u)\]", re.I)


def clean(text):
    return FORMAT_CODE.sub("", text or "").replace("\r\n", "\n").strip()


def camel_words(name):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).replace("_", " ").strip()


def item_spec(reg, damage=0):
    return "%s:%d" % (reg, damage) if damage else reg


def parse_spec(spec):
    """'mod:reg:12' or 'mod:reg' -> ('mod:reg', 12)."""
    parts = spec.split(":")
    if len(parts) >= 3 and parts[-1].lstrip("-").isdigit():
        return ":".join(parts[:-1]), int(parts[-1])
    return spec, 0


def parse_lang(text):
    """key=value lines of a .lang file, or S:key=value lines of a Forge-config lang (GregTech.lang)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//", "{", "}", "languagefile")):
            continue
        if line.startswith("S:"):
            line = line[2:]
        key, sep, value = line.partition("=")
        if sep and key:
            out[key.strip().strip('"')] = value.strip()
    return out


# Chunking

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def markdown_spans(text):
    lines = text.split("\n")
    spans, crumbs, start, title, fence = [], [], 0, "", False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if not m:
            continue
        if i > start:
            spans.append((start, i, title))
        level = len(m.group(1))
        crumbs = crumbs[: level - 1] + [m.group(2)]
        title, start = " > ".join(c for c in crumbs if c), i
    spans.append((start, len(lines), title))
    return spans


def pack_lines(lines, start, end, limit=MAX_CHARS):
    pieces, s, size = [], start, 0
    for i in range(start, end):
        n = len(lines[i]) + 1
        if size and size + n > limit:
            pieces.append((s, i))
            s, size = i, 0
        size += n
    if s < end:
        pieces.append((s, end))
    return pieces


def finish(kind, doc, lines, spans):
    """Merges small spans, splits large ones, and returns chunk dicts with 1-based inclusive line ranges."""
    merged = []
    for start, end, title in spans:
        size = sum(len(l) + 1 for l in lines[start:end])
        if merged:
            ps, pe, pt, psize = merged[-1]
            if pe == start and (psize < MIN_CHARS or size < MIN_CHARS) and psize + size <= MAX_CHARS:
                merged[-1] = (ps, end, pt or title, psize + size)
                continue
        merged.append((start, end, title, size))
    chunks = []
    for start, end, title, size in merged:
        pieces = [(start, end)] if size <= MAX_CHARS else pack_lines(lines, start, end)
        for s, e in pieces:
            text = "\n".join(lines[s:e]).strip("\n")
            if not text.strip():
                continue
            chunks.append({
                "kind": kind, "source": doc["key"], "start": s + 1, "end": e,
                "title": join_title(doc["title"], title), "text": text[:MAX_CHARS], "meta": doc.get("meta") or {},
            })
    for c in chunks:
        c["id"] = hashlib.sha256((c["kind"] + "\0" + embed_text(c)).encode("utf-8")).hexdigest()[:32]
    return chunks


def join_title(doc_title, section):
    """Doc title plus the section's heading path, without repeating the page title when the page's H1 matches it."""
    if not doc_title:
        return section
    short = doc_title.split(": ", 1)[-1].split(" > ")[-1]
    for t in (doc_title, short):
        if section == t or section.startswith(t + " > "):
            section = section[len(t):].lstrip(" >")
            break
    return doc_title + (" > " + section if section else "")


def chunk_markdown(kind, doc):
    return finish(kind, doc, doc["text"].split("\n"), markdown_spans(doc["text"]))


def chunk_whole(kind, doc):
    lines = doc["text"].split("\n")
    return finish(kind, doc, lines, [(0, len(lines), "")])


def embed_text(chunk):
    head = "[%s] %s" % (chunk["kind"], chunk["title"]) if chunk["title"] else "[%s]" % chunk["kind"]
    return head + "\n\n" + chunk["text"]


def corpus_chunks(ctx, kinds=None, log=lambda s: None):
    """Chunks of every kind, in the profile's order. lang loads first and item names are rebuilt for each pass, so
    quests and guide pages re-rendered in a long-lived process use the current names, not those of its first pass."""
    ctx._names = None
    ctx.extracted = {}
    kinds = list(kinds or PROFILES[DEFAULT_PROFILE]["kinds"])
    by_kind = {}
    for kind in sorted(kinds, key=lambda k: k != "lang"):
        by_kind[kind] = load_docs(ctx, kind, log=log)
    chunks = []
    for kind in kinds:
        src = SOURCES[kind]
        for doc in by_kind[kind]:
            chunks.extend(src.chunk(kind, doc))
    return chunks


# Item and fluid names. Order: an items.tsv overlay (generated later from the recipe database), GregTech's generated
# items worked out from its source, then the en_US.lang keys an item's registry name usually maps to.

# Fallback when the source has no metaitem.01 prefix list.
GT_PREFIXES_01 = [
    "Tiny Pile of %s Dust", "Small Pile of %s Dust", "%s Dust", "Impure Pile of %s Dust", "Purified Pile of %s Dust",
    "Crushed %s Ore", "Purified %s Ore", "Centrifuged %s Ore", "%s", "%s Nugget", None, "%s Ingot", "Hot %s Ingot",
    None, None, None, None, "%s Plate", "Double %s Plate", "Triple %s Plate", "Quadruple %s Plate",
    "Quintuple %s Plate", "Dense %s Plate", "%s Rod", "%s Lens", "%s Round", "%s Bolt", "%s Screw", "%s Ring",
    "%s Foil", "%s Cell", "%s Plasma Cell",
]
VOLTAGES = ["ULV", "LV", "MV", "HV", "EV", "IV", "LuV", "ZPM", "UV", "UHV", "UEV", "UIV", "UMV", "UXV", "MAX"]
COMMENT = r"(?:\s*//[^\n]*)*\s*"
ENUM_ID = re.compile(r"^\s*([A-Za-z0-9_]+)\(\s*(\d+)\s*\)\s*[,;]", re.M)
MTE_REG = re.compile(r"(?:\b([A-Za-z0-9_]+)\.ID|\b(\d{2,5}))\s*\)?" + COMMENT + r"(?:\.setName\(|,)" + COMMENT
                     + r"\"([\w.\-]+)\"\s*," + COMMENT + r"\"([^\"\n]*)\"")
ITEM_REG = re.compile(r"\b([A-Za-z0-9_]+)\.ID\s*," + COMMENT + r"\"([^\"\n]+)\"")
MAT_ID = re.compile(r"\br\(\s*(\d+)\s*,\s*Materials\.(\w+)\s*\)")
MAT_NAME = re.compile(r"setName\(\"(\w+)\"\)\s*\.setDefaultLocalName\(\"([^\"]+)\"\)")
PREFIX_DEF = re.compile(r"OrePrefixes (\w+) = new OrePrefixBuilder\(\"\w+\"\)(.*?)\.build\(\)", re.S)
META_SUPER = re.compile(r"super\(\s*\"metaitem\.(0\d)\"\s*,(.*?)\);", re.S)


def gt_root_names(ctx, roots):
    """The GregTech source roots as recorded in gregtech.json: relative to the repo root when under it, so the cache,
    which is committed to a public repo, never records a local home path."""
    out = []
    for p in roots:
        try:
            out.append(Path(p).resolve().relative_to(Path(ctx.root).resolve()).as_posix())
        except ValueError:
            out.append(str(p))
    return out


def gt_tables(ctx):
    """Names for GregTech's generated items, parsed (never run) from its source: material ids, the ore prefix list of
    each gt.metaitem.0N, the special items in those metaitems, and machine meta ids. Cached in names/gregtech.json."""
    cache = ctx.corpus / "names" / "gregtech.json"
    roots = [p for p in ctx.gtsrc if p.is_dir()]
    fp = fingerprint(gt_source_files(ctx)) if roots else None
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
        except (OSError, ValueError):
            cached = None
        if cached is not None and (ctx.readonly or not roots or (
                cached.get("roots") == gt_root_names(ctx, roots) and cached.get("v") == EXTRACT_VERSION
                and cached.get("fp") == fp)):
            return cached
    materials, mat_names, enum_ids, item_enums, regs, prefixes, lists, items = {}, {}, {}, {}, [], {}, {}, {}
    for root in roots:
        for f in root.rglob("*.java"):
            name = f.name
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if name == "MaterialsIDMap.java":
                materials.update({int(i): m for i, m in MAT_ID.findall(text)})
            if name == "OrePrefixes.java":
                for pname, body in PREFIX_DEF.findall(text):
                    pre = re.search(r"withPrefix\(\"([^\"]*)\"\)", body)
                    suf = re.search(r"withSuffix\(\"([^\"]*)\"\)", body)
                    prefixes[pname] = (pre.group(1) if pre else "") + "%s" + (suf.group(1) if suf else "")
            m = re.match(r"IDMetaItem(0\d)\.java$", name)
            if m:
                item_enums[m.group(1)] = {n: int(i) for n, i in ENUM_ID.findall(text)}
            m = re.match(r"MetaGeneratedItem(0\d)\.java$", name)
            if m:
                for num, body in META_SUPER.findall(text):
                    lists[num] = [None if x.strip() == "null" else x.strip().split(".")[-1] for x in body.split(",") if x.strip()]
                items.setdefault(m.group(1), []).extend(ITEM_REG.findall(text))
            if "setDefaultLocalName" in text:
                mat_names.update(dict(MAT_NAME.findall(text)))
            if name.endswith(("IDs.java", "ID.java", "Ids.java")):
                for n, i in ENUM_ID.findall(text):
                    enum_ids.setdefault(n, int(i))
            if '"' in text and ("MTE" in text or "MetaTileEntity" in text):
                regs.extend(MTE_REG.findall(text))
        if materials:
            break  # the first root that has GregTech wins; the second is only a fallback
    machines = {}
    for enum, num, key, english in regs:
        mid = enum_ids.get(enum) if enum else int(num)
        if mid is not None and "%" not in english:
            machines.setdefault(str(mid), [key, english])
    metaitems = {}
    for num, regs_n in items.items():
        ids = item_enums.get(num, {})
        table = metaitems.setdefault(num, {})
        for enum, label in regs_n:
            if enum in ids:
                table.setdefault(str(ids[enum]), label)
    out = {
        "v": EXTRACT_VERSION, "roots": gt_root_names(ctx, roots),
        "materials": {str(i): mat_names.get(m, camel_words(m)) for i, m in materials.items()},
        "prefixes": {num: [prefixes.get(p) if p and not p.startswith("___") else None for p in lst] for num, lst in lists.items()},
        "metaitems": metaitems, "machines": machines,
    }
    out["fp"] = fp
    if not ctx.readonly and roots:
        with atomic_file(cache) as f:
            f.write(json.dumps(out))
    return out


def gt_source_files(ctx):
    """The GregTech source gt_tables() parses: a regenerated gtnh-src (new pack) invalidates the names cache and every
    extraction that rendered item names."""
    return [f for p in ctx.gtsrc if p.is_dir() for f in p.rglob("*.java")]


class Names:
    def __init__(self, ctx):
        self.lang, self.lower = {}, {}
        for doc in load_docs(ctx, "lang"):
            if doc["meta"].get("format") == "lang":
                self.lang.update(parse_lang(doc["text"]))
        self.lower = {k.lower(): v for k, v in self.lang.items()}
        self.overlay = {}
        tsv = ctx.corpus / "names" / "items.tsv"
        if tsv.is_file():
            for line in tsv.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t")
                if len(parts) >= 3 and not line.startswith("#"):
                    self.overlay[(parts[0], parts[1])] = parts[2]
        gt = gt_tables(ctx)
        self.materials, self.machines = gt.get("materials", {}), gt.get("machines", {})
        self.prefixes, self.metaitems = gt.get("prefixes", {}), gt.get("metaitems", {})
        if not self.prefixes.get("01"):
            self.prefixes["01"] = GT_PREFIXES_01

    def tiered(self, key):
        """A lang value with one %s placeholder, filled with the voltage tier named in the key (…tier.03 -> HV)."""
        m = re.search(r"\.tier\.(\d+)", key)
        if not m or int(m.group(1)) >= len(VOLTAGES):
            return None
        for k in (key, key.replace(m.group(0), "")):
            v = self.lang.get(k) or self.lower.get(k.lower())
            if v and len(re.findall(r"%(?:1\$)?s", v)) == 1:
                return clean(re.sub(r"%(?:1\$)?s", VOLTAGES[int(m.group(1))], v))
        return None

    def _get(self, key):
        v = self.lang.get(key) or self.lower.get(key.lower())
        if v and "%" not in v:
            return clean(v)
        return None

    def item(self, reg, damage=0):
        """Display name of an item, or None when no source knows it."""
        for k in ((reg, str(damage)), (reg, "*")):
            if k in self.overlay:
                return self.overlay[k]
        m = re.match(r"gregtech:gt\.metaitem\.(0\d)$", reg)
        if m:
            num = m.group(1)
            label = self.metaitems.get(num, {}).get(str(damage - 32000)) if damage >= 32000 else None
            if label:
                return self._get(label) if re.fullmatch(r"[\w.]+", label) and "." in label else label
            table = self.prefixes.get(num) or []
            fmt = table[damage // 1000] if damage < 32000 and damage // 1000 < len(table) else None
            mat = self.materials.get(str(damage % 1000))
            if fmt and mat:
                return fmt % mat
        if reg == "gregtech:gt.blockframes" and self.materials.get(str(damage)):
            return self.materials[str(damage)] + " Frame Box"
        if re.match(r"gregtech:gt\.blockores\d*$", reg) and self.materials.get(str(damage % 1000)):
            return self.materials[str(damage % 1000)] + " Ore"
        if reg == "gregtech:gt.blockmachines" and str(damage) in self.machines:
            key, english = self.machines[str(damage)]
            k = "gt.blockmachines.%s.name" % key
            return self._get(k) or english or self.tiered(k)
        mod, _, name = reg.partition(":")
        bare = re.sub(r"^(item|tile)\.", "", name)
        keys = []
        for n in dict.fromkeys((name, bare, mod + "." + bare)):
            keys += ["%s.%d.name" % (n, damage), "item.%s.%d.name" % (n, damage), "tile.%s.%d.name" % (n, damage)]
        if not damage:
            for n in dict.fromkeys((name, bare, mod + "." + bare)):
                keys += ["%s.name" % n, "item.%s.name" % n, "tile.%s.name" % n]
        for key in keys:
            v = self._get(key)
            if v:
                return v
        return None

    def item_label(self, spec):
        reg, damage = parse_spec(spec)
        return self.item(reg, damage) or spec

    def fluid(self, name):
        for key in (name, "fluid." + name, "fluid." + name + ".name", name + ".name"):
            v = self._get(key)
            if v:
                return v
        return name

    def entity(self, name):
        return self._get("entity.%s.name" % name) or self._get("entity.%s.name" % name.split(".")[-1]) or camel_words(name.split(".")[-1])


# quest: the BetterQuesting quest book. In 2.9.0 the text is inline in each quest's JSON (name:8 / desc:8), not in a
# lang file: config/betterquesting/DefaultQuests/Quests/<line>/<Name>-<id>.json, with chapter membership in
# QuestLines/<line>/<Name>-<id>.json and QuestLines/<line>/QuestLine.json.

def bq_dir(ctx):
    cfg = ctx.config_dir()
    d = cfg / "betterquesting" / "DefaultQuests" if cfg else None
    return d if d and d.is_dir() else None


def quest_inputs(ctx):
    d = bq_dir(ctx)
    if not d:
        return []
    return list(d.rglob("*.json")) + list(d.glob("*.txt"))


def quest_name_inputs(ctx):
    """Item names come from the lang cache, the overlay and GregTech's source, so a change there re-renders quests and
    guide pages too (deps, not primary inputs: see source())."""
    return [p for p in (ctx.corpus / "lang" / "docs.jsonl", ctx.corpus / "names" / "items.tsv") if p.is_file()] + \
        gt_source_files(ctx)


def bq_id(obj, prefix="questID"):
    high, low = obj.get(prefix + "High:4", 0), obj.get(prefix + "Low:4", 0)
    return base64.urlsafe_b64encode(struct.pack(">qq", int(high), int(low))).decode("ascii")


def nbt_list(obj, key):
    v = obj.get(key) or {}
    return [v[k] for k in sorted(v, key=lambda s: int(s.split(":")[0]))] if isinstance(v, dict) else []


def bq_props(obj):
    return (obj.get("properties:10") or {}).get("betterquesting:10") or {}


def bq_text(s):
    return BQ_TAG.sub("", clean(s))


def stack_text(names, st):
    reg, dmg, count = st.get("id:8", "?"), int(st.get("Damage:2", 0)), int(st.get("Count:3", 1))
    ore = st.get("OreDict:8") or ""
    label = names.item(reg, dmg) or item_spec(reg, dmg)
    if ore:
        label += " (any %s)" % ore
    return ("%d × %s" % (count, label)) if count > 1 else label, item_spec(reg, dmg)


TASK_VERBS = {
    "bq_standard:retrieval": "Retrieve", "bq_standard:optional_retrieval": "Retrieve (optional)",
    "bq_standard:crafting": "Craft", "bq_standard:fluid": "Submit fluid", "bq_standard:hunt": "Kill",
    "bq_standard:meeting": "Meet", "bq_standard:location": "Visit", "bq_standard:checkbox": "Tick the checkbox",
}


@source("quest", quest_inputs, cache=True, deps=quest_name_inputs,
        doc="BetterQuesting quest book from the pack's config/: one doc per quest.")
def discover_quests(ctx):
    d = bq_dir(ctx)
    if not d:
        return
    names = ctx.names()
    lines, line_order = {}, []
    order_file = d / "QuestLinesOrder.txt"
    if order_file.is_file():
        line_order = [l.split(":", 1)[0].strip() for l in order_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    member = {}
    for ql in sorted((d / "QuestLines").glob("*/QuestLine.json")):
        data = json.loads(ql.read_text(encoding="utf-8"))
        lid = bq_id(data, "questLineID")
        lines[lid] = clean(bq_props(data).get("name:8", ql.parent.name))
        for entry in ql.parent.glob("*.json"):
            if entry.name != "QuestLine.json":
                member.setdefault(bq_id(json.loads(entry.read_text(encoding="utf-8"))), []).append(lid)
    rank = {lid: i for i, lid in enumerate(line_order)}
    quests = {}
    for f in sorted((d / "Quests").rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        quests[bq_id(data)] = (f, data)
    titles = {qid: bq_text(bq_props(q).get("name:8", "")) or qid for qid, (_, q) in quests.items()}
    unlocks = {}
    for qid, (_, q) in quests.items():
        for p in nbt_list(q, "preRequisites:9"):
            unlocks.setdefault(bq_id(p), []).append(qid)
    for qid, (f, q) in sorted(quests.items(), key=lambda kv: str(kv[1][0])):
        props = bq_props(q)
        title = titles[qid]
        chapters = [lines[l] for l in sorted(member.get(qid, []), key=lambda l: rank.get(l, 999)) if l in lines]
        out = ["Quest: " + title]
        if chapters:
            out.append("Quest line: " + "; ".join(chapters))
        desc = bq_text(props.get("desc:8", ""))
        if desc:
            out += ["", desc, ""]
        item_ids, tasks = [], []
        for t in nbt_list(q, "tasks:9"):
            tid = t.get("taskID:8", "")
            verb = TASK_VERBS.get(tid, tid.split(":")[-1])
            if "requiredItems:9" in t:
                parts = []
                for st in nbt_list(t, "requiredItems:9"):
                    label, spec = stack_text(names, st)
                    parts.append(label)
                    item_ids.append(spec)
                tasks.append("%s: %s" % (verb, "; ".join(parts)))
            elif "requiredFluids:9" in t:
                tasks.append("%s: %s" % (verb, "; ".join(
                    "%d L %s" % (int(fl.get("Amount:3", 0)), names.fluid(fl.get("FluidName:8", "?")))
                    for fl in nbt_list(t, "requiredFluids:9"))))
            elif tid in ("bq_standard:hunt", "bq_standard:meeting"):
                n = int(t.get("required:3", t.get("amount:3", 1)))
                tasks.append("%s: %s%s" % (verb, ("%d × " % n) if n > 1 else "", names.entity(t.get("target:8", "?"))))
            elif tid == "bq_standard:location":
                tasks.append("%s: %s (dimension %s)" % (verb, clean(t.get("name:8", "")) or "a location", t.get("dimension:3", "?")))
            else:
                tasks.append(verb)
        if tasks:
            out.append("Tasks:")
            out += ["- " + t for t in tasks]
        rewards = []
        for r in nbt_list(q, "rewards:9"):
            rid = r.get("rewardID:8", "")
            if rid == "bq_standard:choice":
                rewards.append("choose one of: " + "; ".join(stack_text(names, st)[0] for st in nbt_list(r, "choices:9")))
            elif rid == "bq_standard:item":
                rewards += [stack_text(names, st)[0] for st in nbt_list(r, "rewards:9")]
            elif rid == "bq_standard:questcompletion":
                rewards.append("completes quest " + titles.get(r.get("questID:8", ""), r.get("questID:8", "?")))
            elif rid == "bq_standard:xp":
                rewards.append("%s XP" % r.get("amount:3", "?"))
        if rewards:
            out.append("Rewards: " + "; ".join(rewards))
        pre = [titles.get(bq_id(p), bq_id(p)) for p in nbt_list(q, "preRequisites:9")]
        if pre:
            out.append("Prerequisites: " + "; ".join(pre))
        nxt = [titles[u] for u in unlocks.get(qid, []) if u in titles]
        if nxt:
            out.append("Unlocks: " + "; ".join(nxt))
        icon = props.get("icon:10") or {}
        meta = {"quest_id": qid, "quest_lines": chapters, "file": str(f.relative_to(d))}
        if item_ids:
            meta["item_ids"] = list(dict.fromkeys(item_ids))
        if icon.get("id:8"):
            meta["icon"] = item_spec(icon["id:8"], int(icon.get("Damage:2", 0)))
        yield {"key": "quest:" + qid, "title": " > ".join(([chapters[0]] if chapters else []) + [title]),
               "text": "\n".join(out), "meta": meta}


SOURCES["quest"].chunk = chunk_whole


# guide: GuideNH pages. 2.9.0 ships them in config/guidenh/DefaultGuide.zip (the GTNH Guide Pack resource pack,
# CC BY-NC-SA 4.0), laid out as assets/<namespace>/guidenh/_<lang>/<page>.md. Mod jars and resource packs may add
# more pages in the same layout; GuideNH's own welcome page sits in its jar.

GUIDE_PATH = re.compile(r"^assets/([^/]+)/guidenh/(.+\.md)$")


def guide_archives(ctx):
    out = []
    if ctx.pack:
        for d in (ctx.pack / "config" / "guidenh", ctx.pack / "resourcepacks"):
            if d.is_dir():
                out += sorted(d.glob("*.zip"))
    cfg = ctx.config_dir()
    if cfg and not out and (cfg / "guidenh").is_dir():
        out += sorted((cfg / "guidenh").glob("*.zip"))
    return out


def guide_inputs(ctx):
    return guide_archives(ctx) + ctx.jars() + ctx.extra_inputs()


MODID = re.compile(r'"modid"\s*:\s*"([^"]+)"')


def jar_modids(path):
    """The mod ids a jar's mcmod.info declares, lowercased. The jar is only read as a zip."""
    try:
        with zipfile.ZipFile(path) as z:
            if "mcmod.info" not in z.namelist():
                return set()
            return {m.lower() for m in MODID.findall(z.read("mcmod.info").decode("utf-8", "replace"))}
    except (zipfile.BadZipFile, OSError, KeyError):
        return set()


def mod_jars(ctx):
    """The jars the jar-reading sources read: [(path, extra)], the GTNH pack's first (extra None), then the tuxmine
    packs' (extra = {"pack": "tuxmine server+client", "jar": name}, merged into each doc's meta). A tuxmine jar
    replaces a GTNH one with the same file name or a shared mod id (our JourneyMap Unlimited over GTNH's fairplay
    JourneyMap), so a mod is never read twice. Tuxmine URL mods not downloaded yet are skipped; their fingerprint
    token says "missing", and pack_identity() refuses to stamp such a corpus."""
    extras = [e for e in ctx.extra_jars() if e["path"]]
    if not extras:
        return [(p, None) for p in ctx.jars()]
    names = {Path(e["path"]).name.lower() for e in extras} | {e["name"].lower() for e in extras}
    ids = set().union(*(jar_modids(e["path"]) for e in extras))
    out = [(p, None) for p in ctx.jars() if p.name.lower() not in names and not (jar_modids(p) & ids)]
    for e in extras:
        out.append((Path(e["path"]), {"pack": "tuxmine " + "+".join(e["packs"]), "jar": e["name"]}))
    return out


def replaced_jars(ctx):
    """The GTNH jars mod_jars() leaves out in favour of a tuxmine jar."""
    kept = {p for p, extra in mod_jars(ctx) if extra is None}
    return [p for p in ctx.jars() if p not in kept]


def guide_pages(names_in_zip):
    """Picks English pages: _en_us/ first, then pages with no language folder."""
    pages = {}
    for n in names_in_zip:
        m = GUIDE_PATH.match(n)
        if not m:
            continue
        ns, rel = m.groups()
        if rel.startswith("_"):
            lang, _, rest = rel.partition("/")
            if lang.lower() != "_en_us":
                continue
            pages[(ns, rest)] = n
        else:
            pages.setdefault((ns, rel), n)
    return pages


FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def frontmatter(text):
    """A small YAML subset: top-level scalars, '- item' lists, and one level of nesting (navigation.title)."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta, key, sub = {}, None, None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- ") and key:
            target, name = (meta[key], sub) if sub and isinstance(meta.get(key), dict) and indent > 2 else (meta, key)
            if not isinstance(target.get(name), list):
                target[name] = []
            target[name].append(line[2:].strip().strip("'\""))
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            v = v.strip("'\"")
        if indent == 0:
            key, sub = k, None
            meta[k] = v
        elif key:
            if not isinstance(meta.get(key), dict):
                meta[key] = {}
            sub = k
            meta[key][k] = v
    return meta, text[m.end():]


ATTR_ID = re.compile(r"\bid=[\"']([^\"']+)[\"']")


def guide_to_text(md, names):
    """GuideNH markdown to plain markdown: item tags become item names, scenes and recipe widgets are dropped."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"<GameScene\b.*?</GameScene>", "", md, flags=re.S)
    md = re.sub(r"<(?:ItemLink|ItemImage|BlockImage|ItemIcon)\b([^>]*)/>", lambda m: label_of(m.group(1), names), md)
    md = re.sub(r"<ItemLink\b([^>]*)>(.*?)</ItemLink>",
                lambda m: m.group(2).strip() or label_of(m.group(1), names), md, flags=re.S)
    md = re.sub(r"<RecipesFor\b([^>]*)/>", lambda m: "(recipes for %s)" % label_of(m.group(1), names), md)
    md = re.sub(r"</?[A-Za-z][\w.-]*(?:\s[^<>]*)?/?>", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def label_of(attrs, names):
    m = ATTR_ID.search(attrs)
    return names.item_label(m.group(1)) if m else ""


def guide_doc(ns, rel, raw, names, origin):
    meta, body = frontmatter(raw)
    nav = meta.get("navigation") if isinstance(meta.get("navigation"), dict) else {}
    text = guide_to_text(body, names)
    first = next((HEADING.match(l).group(2) for l in text.split("\n") if HEADING.match(l)), "")
    title = clean(nav.get("title") or first or rel.rsplit("/", 1)[-1][:-3].replace("_", " "))
    out = {"page": "%s/%s" % (ns, rel), "origin": origin}
    for k in ("item_ids", "quest_ids"):
        if isinstance(meta.get(k), list) and meta[k]:
            out[k] = meta[k]
    if out.get("quest_ids"):  # pages often drop the base64 padding; quests keep it
        out["quest_ids"] = [q + "=" * (-len(q) % 4) for q in out["quest_ids"]]
    return {"key": "guide:%s/%s" % (ns, rel), "title": "%s guide: %s" % (ns, title), "text": text, "meta": out}


@source("guide", guide_inputs, cache=True, deps=quest_name_inputs,
        doc="GuideNH pages (DefaultGuide.zip, resource packs, mod jars, the tuxmine packs' jars).")
def discover_guides(ctx):
    names = ctx.names()
    seen = set()
    jars = mod_jars(ctx)
    # Resource packs first (they override jars in game), then our tuxmine jars, which win over the GTNH pack's.
    for path, extra in [(p, None) for p in guide_archives(ctx)] + [j for j in jars if j[1]] + [j for j in jars if not j[1]]:
        try:
            z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            continue
        with z:
            listing = z.namelist()
            pages = guide_pages(listing)
            if path.name.lower().startswith("guidenh") and "assets/guidenh/welcome/en_us.md" in listing:
                pages[("guidenh", "welcome.md")] = "assets/guidenh/welcome/en_us.md"
            for (ns, rel), name in sorted(pages.items()):
                if (ns, rel) in seen:
                    continue
                seen.add((ns, rel))
                raw = z.read(name).decode("utf-8", "replace")
                doc = guide_doc(ns, rel, raw, names, path.name)
                if extra:
                    doc["meta"].update(extra)
                yield doc


# lang: en_US.lang from every mod jar (and vanilla's from the server jar), plus GregTech's markdown multiblock
# tooltips (assets/gregtech/lang/en_US/tooltip/*.md) and a runtime GregTech.lang when one is available.

LANG_PATH = re.compile(r"(?:^|/)assets/([^/]+)/lang/en_us\.lang$", re.I)
TOOLTIP_PATH = re.compile(r"^assets/([^/]+)/lang/en_US/tooltip/(.+)\.md$")


def lang_extra(ctx):
    return lang_pack_extra(ctx) + lang_corpus_extra(ctx)


def lang_pack_extra(ctx):
    out = []
    if ctx.pack:
        if (ctx.pack / "GregTech.lang").is_file():
            out.append(ctx.pack / "GregTech.lang")
        out += sorted(ctx.pack.glob("minecraft_server*.jar"))
    return out


def lang_corpus_extra(ctx):
    """Runtime lang files dropped into <corpus>/lang/extra/. They travel with the corpus (and its cache), so they are
    deps, not primary inputs: without the pack the cache that already holds them is used."""
    extra = ctx.corpus / "lang" / "extra"
    return sorted(extra.glob("*.lang")) if extra.is_dir() else []


def lang_inputs(ctx):
    return ctx.jars() + lang_pack_extra(ctx) + ctx.extra_inputs()


def clean_lang(text):
    seen, out = set(), []
    for line in text.splitlines():
        line = clean(line)
        if not line or line.startswith("#") or "=" not in line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return "\n".join(out)


def clean_tooltip(md):
    md = re.sub(r"\{[\w\-]+:", "", md)
    return re.sub(r"[{}]", "", md).strip()


@source("lang", lang_inputs, cache=True, deps=lang_corpus_extra,
        doc="en_US.lang player text from every jar (the tuxmine packs' too), split per mod by size.")
def discover_lang(ctx):
    by_ns, tooltips = {}, set()
    for path, extra in mod_jars(ctx) + [(p, None) for p in lang_extra(ctx) if p.suffix == ".jar"]:
        try:
            z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            continue
        jar = extra["jar"] if extra else path.name
        with z:
            for name in z.namelist():
                m = LANG_PATH.search(name)
                if m:
                    text = clean_lang(z.read(name).decode("utf-8", "replace"))
                    if text:
                        by_ns.setdefault(m.group(1), []).append((jar, text, extra))
                    continue
                m = TOOLTIP_PATH.match(name)
                if m and m.groups() not in tooltips:
                    tooltips.add(m.groups())
                    meta = {"mod": m.group(1), "jar": jar, "format": "md"}
                    yield {"key": "lang:%s/tooltip/%s" % m.groups(), "title": "%s multiblock tooltip: %s" % (m.group(1), m.group(2)),
                           "text": clean_tooltip(z.read(name).decode("utf-8", "replace")), "meta": dict(meta, **(extra or {}))}
    for ns in sorted(by_ns):
        # Keys of the GTNH pack's docs depend only on the GTNH jars, so adding our jars never renames them; one of
        # ours is lang:<ns> when it alone has that namespace, else lang:<ns>@<jar>.
        gtnh = sum(1 for _, _, extra in by_ns[ns] if not extra)
        for jar, text, extra in by_ns[ns]:
            alone = gtnh == 1 if not extra else len(by_ns[ns]) == 1
            key = "lang:" + ns if alone else "lang:%s@%s" % (ns, jar)
            meta = {"mod": ns, "jar": jar, "format": "lang"}
            yield {"key": key, "title": "%s en_US.lang" % ns, "text": text, "meta": dict(meta, **(extra or {}))}
    for path in lang_extra(ctx):
        if path.suffix == ".lang":
            text = clean_lang("\n".join("%s=%s" % kv for kv in parse_lang(path.read_text(encoding="utf-8", errors="replace")).items()))
            yield {"key": "lang:" + path.name, "title": "%s (runtime lang)" % path.name, "text": text,
                   "meta": {"mod": path.stem, "file": path.name, "format": "lang"}}


def chunk_lang(kind, doc):
    if doc["meta"].get("format") == "md":
        return chunk_whole(kind, doc)
    lines = doc["text"].split("\n")
    return finish(kind, doc, lines, [(s, e, "") for s, e in pack_lines(lines, 0, len(lines))])


SOURCES["lang"].chunk = chunk_lang


# wiki: the offline copy written by mirror_wiki.py (<corpus>/wiki/manifest.json plus text/<file>.txt).

def wiki_inputs(ctx):
    m = live_dir(ctx.wiki_dir) / "manifest.json"
    return [m] if m.is_file() else []


@source("wiki", wiki_inputs, cache=False, doc="Offline wiki.gtnewhorizons.com pages from mirror_wiki.py, split at headings.")
def discover_wiki(ctx):
    base = live_dir(ctx.wiki_dir)
    if not (base / "manifest.json").is_file():
        return
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    for title, page in sorted(manifest.get("pages", {}).items()):
        f = base / "text" / page["file"]
        if not f.is_file():
            continue
        meta = {"title": title, "revid": page.get("revid"), "url": page.get("url")}
        for k in ("categories", "edited_by_dave", "dave_lines", "dave_reason", "local"):
            if page.get(k):
                meta[k] = page[k]
        yield {"key": "wiki:" + title, "title": title, "text": f.read_text(encoding="utf-8"), "meta": meta}


DAVE_META = ("edited_by_dave", "dave_lines", "dave_reason")


def chunk_wiki(kind, doc):
    """Markdown chunks; a chunk overlapping lines Dave changed (living-wiki metadata) keeps edited_by_dave and the
    reason, other chunks of the page drop them. Metadata only: it never changes the embedded text."""
    chunks = chunk_markdown(kind, doc)
    lines = doc["meta"].get("dave_lines")
    if not doc["meta"].get("edited_by_dave"):
        return chunks
    for c in chunks:
        local = doc["meta"].get("local") or any(a <= c["end"] and b >= c["start"] for a, b in lines or [])
        meta = {k: v for k, v in c["meta"].items() if k not in DAVE_META}
        if local:
            meta["edited_by_dave"] = doc["meta"]["edited_by_dave"]
            if doc["meta"].get("dave_reason"):
                meta["dave_reason"] = doc["meta"]["dave_reason"]
        c["meta"] = meta
    return chunks


SOURCES["wiki"].chunk = chunk_wiki


# item: stub. Item cards will be generated from the recipe database (data/recipes.sqlite, Stage 2 of
# docs/plans/recipe-knowledge.md): one doc per item or fluid, keyed "item:<mod:reg:damage>", whose text holds the
# display name, aliases, ore dictionary names, mod, tooltip, the machine types that make it and its top uses, and
# whose meta holds {"item_ids": [...]}. Until that database exists this source returns nothing.

def item_inputs(ctx):
    db = ctx.root / "data" / "recipes.sqlite"
    return [db] if db.is_file() else []


@source("item", item_inputs, cache=False, doc="Item cards from the recipe database (not built yet).")
def discover_items(ctx):
    return iter(())


# playbook and memory: Dave's own Markdown memories under data/memory/, one file per memory with a frontmatter block.
# playbook = data/memory/playbook/; memory = data/memory/server/ and data/memory/lessons/. data/memory/players/ is
# never indexed. Memories whose status is archived or superseded are skipped.

MEMORY_DIRS = {"playbook": ("playbook",), "memory": ("server", "lessons")}


def memory_docs(ctx, kind):
    for sub in MEMORY_DIRS[kind]:
        d = ctx.memory / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if any(part.startswith(".") for part in f.relative_to(d).parts):
                continue  # the memory store's temporary and hidden files
            try:
                raw = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # vanished between the listing and the read (a rename by the store), or not text
            meta, body = frontmatter(raw)
            if str(meta.get("status", "")).lower() in SKIP_MEMORY_STATUS:
                continue
            first = next((HEADING.match(l).group(2) for l in body.split("\n") if HEADING.match(l)), "")
            title = str(meta.get("title") or first or f.stem.replace("-", " "))
            rel = str(f.relative_to(ctx.memory))
            keep = {k: v for k, v in meta.items() if isinstance(v, (str, list)) and k != "title" and len(str(v)) < 300}
            keep["path"] = rel
            text = body.strip()
            if not text.startswith("#"):
                text = "# %s\n\n%s" % (title, text)
            yield {"key": "%s:%s" % (kind, rel), "title": title, "text": text, "meta": keep}


@source("playbook", lambda ctx: [], cache=False, doc="Saved answers and solved chains in data/memory/playbook/.")
def discover_playbook(ctx):
    return memory_docs(ctx, "playbook")


@source("memory", lambda ctx: [], cache=False, doc="Server facts and lessons in data/memory/server/ and lessons/.")
def discover_memory(ctx):
    return memory_docs(ctx, "memory")


# Embedding

def model_options(model):
    for prefix, opts in MODEL_OPTIONS.items():
        if model.startswith(prefix):
            return opts
    return {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect: urllib would replay the Authorization header to the new location, and the key may only
    ever go to OpenRouter. A redirect surfaces as an HTTP error instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)
# Transient transport failures worth another try: connection resets, truncated or garbled bodies, timeouts.
TRANSIENT = (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError, RuntimeError)


class OpenRouter:
    def __init__(self, key, model=PROFILES[DEFAULT_PROFILE]["model"]):
        self.key, self.model, self.cost, self.tokens = key, model, 0.0, 0
        self.opts = model_options(model)
        self.open, self.sleep = OPENER.open, time.sleep

    def _post(self, inputs, input_type, attempts=DOC_ATTEMPTS, timeout=DOC_TIMEOUT):
        payload = {"model": self.model, "input": inputs, "provider": {"data_collection": "deny"}}
        if self.opts.get("input_type", True):
            payload["input_type"] = input_type
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(attempts):
            last = attempt == attempts - 1
            req = urllib.request.Request(API_URL, data=body, headers={
                "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                "X-Title": "Dave GTNH search",
            })
            try:
                with self.open(req, timeout=timeout) as f:
                    data = json.load(f)
                if not isinstance(data, dict) or "data" not in data or len(data["data"]) != len(inputs):
                    raise RuntimeError("bad embedding response: " + json.dumps(data)[:300])
                usage = data.get("usage") or {}
                self.cost += usage.get("cost") or 0.0
                self.tokens += usage.get("total_tokens") or 0
                rows = sorted(data["data"], key=lambda d: d["index"])
                return [r["embedding"] for r in rows]
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except (OSError, http.client.HTTPException):
                    detail = ""
                if e.code not in (408, 429, 500, 502, 503, 504, 524, 529) or last:
                    raise RuntimeError("OpenRouter HTTP %d: %s" % (e.code, detail)) from None
            except TRANSIENT:
                if last:
                    raise
            self.sleep(min(60, 2 ** attempt))

    def documents(self, texts):
        batches, cur, size = [], [], 0
        for t in texts:
            if cur and (len(cur) >= BATCH_INPUTS or size + len(t) > BATCH_CHARS):
                batches.append(cur)
                cur, size = [], 0
            cur.append(t)
            size += len(t)
        if cur:
            batches.append(cur)
        with ThreadPoolExecutor(WORKERS) as pool:
            results = list(pool.map(lambda b: self._post(b, "document"), batches))
        return [v for r in results for v in r]

    def query(self, text):
        """One short, quickly retried request: a player is waiting, and the MCP call must not hang for minutes."""
        return self._post([self.opts.get("query_prefix", "") + text], "query", QUERY_ATTEMPTS, QUERY_TIMEOUT)[0]


def normalize(m):
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


# Index

def _json_array(obj):
    return np.frombuffer(json.dumps(obj).encode("utf-8"), dtype=np.uint8)


def save_index(path, chunks, vectors, meta):
    with atomic_file(path, "wb") as f:
        np.savez(f, vectors=vectors.astype(np.float32), chunks=_json_array(chunks), meta=_json_array(meta))


def load_index(path):
    if not path.is_file():
        return None
    with open(path, "rb") as fh, np.load(fh, allow_pickle=False) as z:
        return {
            "vectors": z["vectors"],
            "chunks": json.loads(z["chunks"].tobytes().decode("utf-8")),
            "meta": json.loads(z["meta"].tobytes().decode("utf-8")),
        }


def read_index(path, log=lambda s: None):
    """load_index, but an unreadable file (a crash or a full disk mid-write) gives None instead of an exception."""
    try:
        return load_index(path)
    except Exception as e:  # zipfile, numpy and json all raise their own types for a damaged file
        log("index %s is unreadable: %s" % (path, e))
        return None


def set_aside(path, log=lambda s: None):
    """Moves a damaged file to <name>.corrupt (kept for inspection), so the next build starts clean."""
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
        log("moved the damaged %s to %s.corrupt" % (path.name, path.name))
    except OSError:
        pass


def partial_path(path):
    """Vectors a failed build already paid for, picked up by the next build of the same index file (same model)."""
    return path.with_name(path.stem + ".partial.npz")


def save_partial(path, model, vectors_by_id):
    ids = list(vectors_by_id)
    vectors = np.stack([vectors_by_id[i] for i in ids]) if ids else np.zeros((0, 1), np.float32)
    with atomic_file(partial_path(path), "wb") as f:
        np.savez(f, vectors=vectors.astype(np.float32), ids=_json_array(ids), meta=_json_array({"model": model}))


def load_partial(path, model, log=lambda s: None):
    p = partial_path(path)
    if not p.is_file():
        return {}
    try:
        with open(p, "rb") as fh, np.load(fh, allow_pickle=False) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            ids = json.loads(z["ids"].tobytes().decode("utf-8"))
            vectors = z["vectors"]
    except Exception as e:  # a damaged checkpoint is only a lost saving
        log("ignoring unreadable checkpoint %s: %s" % (p.name, e))
        return {}
    if meta.get("model") != model or len(ids) != len(vectors):
        return {}
    return dict(zip(ids, vectors))


def count_by_kind(chunks):
    out = {}
    for c in chunks:
        out[c["kind"]] = out.get(c["kind"], 0) + 1
    return out


def build(ctx, embedder, path, profile=DEFAULT_PROFILE, chunks=None, log=lambda s: None):
    """Re-chunks the corpus and embeds only chunks whose text changed. Returns the new index, or None when another
    build holds the lock or the index is read-only."""
    if not ctx.writable():
        log("index directory is read-only; build skipped")
        return None
    with file_lock(path.with_suffix(".lock")) as held:
        if not held:
            log("another build is running; skipped")
            return None
        t0 = time.time()
        model = getattr(embedder, "model", PROFILES[profile]["model"])
        old = read_index(path, log)
        if old is None and path.is_file():
            set_aside(path, log)
        known = {}
        if old:
            for c, v in zip(old["chunks"], old["vectors"]):
                known[c["id"]] = v
        saved = load_partial(path, model, log)
        if saved:
            log("resuming with %d vectors from %s" % (len(saved), partial_path(path).name))
        known.update(saved)
        extracted = {}
        if chunks is None:
            chunks = corpus_chunks(ctx, PROFILES[profile]["kinds"], log)
            extracted = ctx.extracted  # which packs each kind's docs came from (only known for chunks built here)
        need, seen = [], set()
        for c in chunks:
            if c["id"] not in known and c["id"] not in seen:
                seen.add(c["id"])
                need.append(c)
        log("%d chunks, %d to embed" % (len(chunks), len(need)))
        fresh = dict(saved)
        for i in range(0, len(need), CHECKPOINT_CHUNKS):
            group = need[i:i + CHECKPOINT_CHUNKS]
            for c, v in zip(group, embedder.documents([embed_text(c) for c in group])):
                known[c["id"]] = fresh[c["id"]] = np.asarray(v, dtype=np.float32)
            if i + CHECKPOINT_CHUNKS < len(need):
                save_partial(path, model, fresh)
        vectors = normalize(np.stack([known[c["id"]] for c in chunks])) if chunks else np.zeros((0, 1), np.float32)
        meta = {
            "profile": profile, "model": model,
            "built_at": int(time.time()), "pack": ctx.pack.parent.name if ctx.pack else None,
            "chunks": len(chunks), "sources": len({c["source"] for c in chunks}), "kinds": count_by_kind(chunks),
            "embedded": len(need), "cost": round(getattr(embedder, "cost", 0.0), 6),
            "seconds": round(time.time() - t0, 1),
            # The packstate fingerprint each pack kind's docs were extracted from (None: unknown or not a full pack).
            "corpus_pack": {k: (extracted.get(k) or {}).get("pack") for k in pack_kinds(profile)},
        }
        labels = {(extracted.get(k) or {}).get("pack_label") for k in pack_kinds(profile)}
        if len(labels) == 1 and None not in labels:
            meta["corpus_pack_label"] = labels.pop()
        index = {"vectors": vectors, "chunks": chunks, "meta": meta}
        save_index(path, chunks, vectors, meta)
        if partial_path(path).exists():
            partial_path(path).unlink()
        log("saved %s (%d embedded, $%.4f)" % (path, len(need), meta["cost"]))
        return index


def search(index, qvec, k=8, kind=None, per_source=3):
    """Top k chunks by cosine, at most per_source from one doc. In a mixed search, kinds in MIXED_SHARE get at most
    1/share of the slots."""
    chunks, vectors = index["chunks"], index["vectors"]
    if not chunks:
        return []
    scores = vectors @ normalize(qvec)
    mixed = not kind or kind == "any"
    caps = {kd: max(1, -(-k // share)) for kd, share in MIXED_SHARE.items()} if mixed else {}
    picked, per, per_kind = [], {}, {}
    for i in np.argsort(-scores):
        if len(picked) >= k:
            break
        c = chunks[i]
        if not mixed and c["kind"] != kind:
            continue
        if per.get(c["source"], 0) >= per_source or per_kind.get(c["kind"], 0) >= caps.get(c["kind"], k):
            continue
        per[c["source"]] = per.get(c["source"], 0) + 1
        per_kind[c["kind"]] = per_kind.get(c["kind"], 0) + 1
        picked.append(i)
    return [dict(chunks[i], score=float(scores[i])) for i in picked]


ID_FIELDS = ("quest_id", "quest_ids", "item_ids", "page", "url", "path", "mod", "pack")


def hit_ids(meta, limit=8):
    parts = []
    for k in ID_FIELDS:
        v = meta.get(k)
        if not v:
            continue
        if isinstance(v, list):
            v = ", ".join(v[:limit]) + (" (+%d more)" % (len(v) - limit) if len(v) > limit else "")
        parts.append("%s: %s" % (k, v))
    if meta.get("pack") and meta.get("jar"):  # our extra mods: name the jar a hit came from
        parts.append("jar: %s" % meta["jar"])
    return " · ".join(parts)


def format_hits(hits, snippet=SNIPPET_CHARS):
    if not hits:
        return "No matches."
    out = []
    for n, h in enumerate(hits, 1):
        text = h["text"]
        if len(text) > snippet:
            text = text[:snippet].rstrip() + "\n[… truncated]"
        loc = h["source"] + (":%d-%d" % (h["start"], h["end"]) if h["kind"] in ("lang", "wiki", "guide") else "")
        meta = h.get("meta") or {}
        local = " · locally edited %s" % meta["edited_by_dave"] if meta.get("edited_by_dave") else ""
        head = "[%d] %s · %s · score %.3f%s\n    %s" % (n, h["kind"], h["title"], h["score"], local, loc)
        ids = hit_ids(h.get("meta") or {})
        out.append(head + ("\n    " + ids if ids else "") + "\n" + text)
    return "\n\n---\n\n".join(out)
