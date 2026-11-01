"""Weekly job: brings the living wiki up to date with Miraheze's archive.org backups of wiki.gtnewhorizons.com.

  python3 -I tools/gtnh-search/update_wiki.py                       update when a newer dump exists
  python3 -I tools/gtnh-search/update_wiki.py --check               report only: no download, no API calls
  python3 -I tools/gtnh-search/update_wiki.py --force ITEM          import that archive.org item even if not newer
  python3 -I tools/gtnh-search/update_wiki.py --merger stub         merge conflicted pages without Sonnet (tests)

Miraheze publishes the wiki's XML backup to archive.org as items miraheze-wiki-gtnhwiki-YYYYMMDD holding
gtnhwiki-YYYYMMDD.xml.gz (about 35 MB, full history). The job downloads only that file and checks its md5 against
archive.org's metadata. It then hands it to the living wiki (tools/living-wiki): an `official` commit, a merge into
`living` (Sonnet merges only pages both sides changed), an incremental index build, and an atomic swap of the
branches, search corpus and index. Any failure leaves all of them untouched. If the image carries a newer official
dump than the volume has seen, that dump goes through the same merge, never a re-seed.

Safe for cron: a lock file stops overlapping runs, stdout gets one summary line, details go to stderr. Exit codes:
0 updated, up to date, or skipped because another job runs; 1 failure; 2 no OPENROUTER_API_KEY.
"""

import argparse
import hashlib
import http.client
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mirror_wiki as mw  # noqa: E402
import semsearch as s  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "living-wiki"))
import living_wiki as lw_mod  # noqa: E402
import merger as mg  # noqa: E402

ITEM_PREFIX = "miraheze-wiki-gtnhwiki-"
SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/%s/files"
DOWNLOAD_URL = "https://archive.org/download/%s/%s"
USER_AGENT = "Dave-Agent wiki updater (private, non-commercial)"
MAX_BYTES = 500 * 2 ** 20
# A dump with fewer than this share of the current pages is treated as broken rather than imported.
MIN_KEEP = 0.5


class Http:
    def _open(self, url, timeout):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return urllib.request.urlopen(req, timeout=timeout)

    def _retry(self, fn, url):
        for attempt in range(4):
            try:
                return fn()
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError("HTTP %d for %s" % (e.code, url)) from None
                wait = mw.backoff(e.headers.get("Retry-After") if e.headers else None, attempt)
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as e:
                if attempt == 3:
                    raise RuntimeError("%s for %s" % (e, url)) from None
                wait = mw.backoff(None, attempt)
            time.sleep(wait)

    def get_json(self, url):
        def go():
            with self._open(url, 60) as f:
                return json.load(f)
        return self._retry(go, url)

    def download(self, url, dest, max_bytes=MAX_BYTES):
        """Streams url to dest and returns its md5 hex digest."""
        def go():
            md5, size = hashlib.md5(), 0
            with self._open(url, 300) as f, open(dest, "wb") as out:
                while True:
                    block = f.read(1 << 20)
                    if not block:
                        break
                    size += len(block)
                    if size > max_bytes:
                        raise RuntimeError("download exceeds %d bytes" % max_bytes)
                    md5.update(block)
                    out.write(block)
            return md5.hexdigest()
        return self._retry(go, url)


def item_date(name):
    m = re.search(r"gtnhwiki-(\d{8})", name or "")
    return m.group(1) if m else None


def newest_item(http):
    params = [("q", "identifier:%s*" % ITEM_PREFIX), ("fl[]", "identifier"), ("fl[]", "publicdate"),
              ("sort[]", "publicdate desc"), ("rows", "20"), ("output", "json")]
    docs = (http.get_json(SEARCH_URL + "?" + urllib.parse.urlencode(params)).get("response") or {}).get("docs") or []
    items = [d["identifier"] for d in docs if re.fullmatch(re.escape(ITEM_PREFIX) + r"\d{8}", d.get("identifier") or "")]
    return max(items, key=item_date) if items else None


def dump_file(http, item):
    want = "gtnhwiki-%s.xml.gz" % item_date(item)
    for f in http.get_json(METADATA_URL % item).get("result") or []:
        if f.get("name") == want:
            return f
    raise RuntimeError("%s has no %s" % (item, want))


def cleanup(*paths):
    for p in paths:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


def seed_candidate(ctx):
    """(item, file, dir) when the image's baked wiki is an official dump snapshot, else None. A snapshot materialized
    from a living wiki (it records living_commit) is not official content and is never imported as such."""
    if not ctx.state:
        return None
    d = ctx.seed_corpus / "wiki"
    m = d / "manifest.json"
    if not m.is_file() or json.loads(m.read_text(encoding="utf-8")).get("living_commit"):
        return None
    item, file_name = lw_mod.snapshot_item(d)
    return (item, file_name, d) if item else None


def run(ctx, http, embedder_factory, merger_factory, check=False, force=None, profile=s.DEFAULT_PROFILE,
        log=lambda m: None):
    """Returns (exit code, one-line summary). --check and read-only mode write nothing: no seeding, no living wiki,
    no lock file."""
    readonly = check or not ctx.writable()
    if ctx.state and not readonly:
        s.seed(ctx, log=log)
    if readonly:
        return guarded(update, ctx, http, embedder_factory, merger_factory, check, force, profile, log)
    with s.file_lock(ctx.jobs_lock()) as held:
        if not held:
            return 0, "skipped: another corpus job is running (%s)" % ctx.jobs_lock()
        s.sweep_staged(ctx.wiki_dir)
        return guarded(update, ctx, http, embedder_factory, merger_factory, check, force, profile, log)


class AfterMove(Exception):
    """A failure after the living wiki's branches already moved: the wiki is updated, the corpus or index may lag."""


def guarded(fn, *args):
    log = args[-1]
    try:
        return fn(*args)
    except AfterMove as e:
        log("update failed after the branches moved: %r" % e.__cause__)
        return 1, "failed after the living wiki was updated: %s" % e
    except Exception as e:  # a cron job reports and exits; failures before the branch move leave no partial state
        log("update failed: %r" % e)
        return 1, "failed: %s; corpus, living wiki and index unchanged" % e


def wiki_refs(lw):
    try:
        return lw.git.rev(lw_mod.OFFICIAL), lw.git.rev(lw_mod.LIVING)
    except Exception:  # unreadable refs: report the stage as unknown rather than guess
        return None


def moved_failure(e, item, what):
    return AfterMove("%s (%s); the living wiki now holds %s, but %s may be stale until the server's next refresh or "
                     "`living_wiki.py sync`" % (e, type(e).__name__, item, what))


def update(ctx, http, embedder_factory, merger_factory, check, force, profile, log):
    if not check and not ctx.writable():
        return 1, "failed: %s is read-only; set GTNH_SEARCH_STATE to a writable directory" % ctx.index
    # Only a real run may create the living wiki; --check just reads what is there.
    lw = lw_mod.LivingWiki(ctx) if check else lw_mod.ensure(ctx, log)[0]
    current, current_date = lw.official_item() if lw.exists() else (None, None)
    seed = None if force else seed_candidate(ctx)
    item = force or newest_item(http)
    if not item or not item_date(item):
        return 1, "failed: no %s* item found on archive.org" % ITEM_PREFIX
    if seed and (item_date(seed[0]) or "") >= item_date(item):  # the image's copy needs no download
        item = seed[0]
    else:
        seed = None
    newer = not current_date or item_date(item) > current_date
    if not newer and not force:
        return 0, "wiki up to date: newest dump %s, official branch at %s" % (item, current or "nothing")
    if check:
        return 0, "update available: %s (official branch at %s)" % (item, current or "nothing")
    embedder = embedder_factory()
    if embedder is None:
        return 2, "failed: OPENROUTER_API_KEY is not set (environment, OPENROUTER_API_KEY_FILE or .env)"

    t0 = time.time()
    download_dir = s.staged(ctx.wiki_dir, "download")
    snapshot = s.staged(ctx.wiki_dir, "import")
    try:
        if seed:
            file_name = seed[1]
            cleanup(snapshot)
            shutil.copytree(seed[2], snapshot)
            count = len(json.loads((snapshot / "manifest.json").read_text(encoding="utf-8")).get("pages", {}))
            log("importing the image's baked dump %s" % item)
        else:
            meta = dump_file(http, item)
            file_name = meta["name"]
            cleanup(download_dir)
            download_dir.mkdir(parents=True)
            dump = download_dir / file_name
            log("downloading %s (%s bytes)" % (file_name, meta.get("size", "?")))
            digest = http.download(DOWNLOAD_URL % (item, urllib.parse.quote(file_name)), dump)
            if not meta.get("md5") or digest != meta["md5"]:
                raise RuntimeError("md5 mismatch for %s: got %s, archive.org says %s" % (file_name, digest, meta.get("md5")))
            cleanup(snapshot)
            count = mw.import_dump(mw.Store(snapshot), dump, mw.NAMESPACES, log,
                                   source="archive:%s/%s" % (item, file_name))
        before = len(lw.official_manifest().get("pages", {})) if lw.exists() else 0
        if count == 0 or count < MIN_KEEP * before:
            raise RuntimeError("%s has %d pages against %d now; refusing it" % (file_name, count, before))
        if not lw.exists():
            with lw.lock() as held:
                if not held:
                    raise RuntimeError("the living wiki is locked")
                lw.init_from(snapshot, item, file_name, log)
            try:
                lw.sync(log)
            except Exception as e:
                raise moved_failure(e, item, "the search corpus") from e
            return 0, "living wiki created from %s: %d pages; the server's refresh embeds them" % (item, count)
        refs = wiki_refs(lw)
        try:
            rep = lw.upgrade(snapshot, item, file_name, merger_factory(), embedder, profile, log)
        except Exception as e:
            now = wiki_refs(lw)
            if refs is None or now is None:
                raise AfterMove("%s (%s); could not tell whether the living wiki's branches moved: check "
                                "`living_wiki.py status`" % (e, type(e).__name__)) from e
            if now != refs:
                raise moved_failure(e, item, "the search corpus or index") from e
            raise
        idx = rep.get("index") or {}
        return 0, "%s; %d chunks embedded, $%.4f, %.0fs" % (rep["summary"], idx.get("embedded", 0), idx.get("cost", 0.0),
                                                          time.time() - t0)
    finally:
        cleanup(download_dir, snapshot)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", metavar="ITEM")
    ap.add_argument("--merger", choices=("claude", "stub"), default="claude",
                    help="who merges pages that both the dump and Dave changed (default: Sonnet via claude -p)")
    ap.add_argument("--merger-model", default=mg.DEFAULT_MODEL)
    ap.add_argument("--profile", choices=sorted(s.PROFILES), default=s.DEFAULT_PROFILE)
    a = ap.parse_args()
    ctx = s.Context()
    key = s.load_key(ctx.root)
    model = s.PROFILES[a.profile]["model"]
    code, summary = run(ctx, Http(), lambda: s.OpenRouter(key, model) if key else None,
                        lambda: mg.make(a.merger, a.merger_model), a.check, a.force, a.profile,
                        log=lambda m: print(m, file=sys.stderr, flush=True))
    print(summary, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
