"""Builds or queries the GTNH search index from the command line.

  python3 -I tools/gtnh-search/index.py --extract      re-read the packs into data/corpus/<kind>/ (no embedding calls)
  python3 -I tools/gtnh-search/index.py --stats        chunk counts per kind and an estimated full-build cost, no API calls
  python3 -I tools/gtnh-search/index.py --check        are the corpus and index built from the current packs?
  python3 -I tools/gtnh-search/index.py --seed         copy the baked corpus and index into GTNH_SEARCH_STATE if needed
  python3 -I tools/gtnh-search/index.py                incremental build (embeds only changed chunks)
  python3 -I tools/gtnh-search/index.py --query "best nitrogen source at HV" [-k 8] [--kind quest]

The packs are the GTNH server pack plus our tuxmine packwiz packs (tuxmine/server, tuxmine/client); see
tools/packstate.py. --extract and a full build first download the tuxmine URL mods into the jar cache, then stamp
"corpus" (and a build "index") in data/packstate only when every pack kind was extracted from the current packs.

Exit codes:
  --extract  0 extracted and stamped, or extracted with no pack here (nothing to stamp, as in the image);
             1 read-only, the tuxmine jars could not be fetched, or not stamped (the reason is printed)
  (build)    0 built and stamped, or built with no pack here; 1 build failed or not stamped; 2 no OPENROUTER_API_KEY
  --check    0 corpus and index are current; 1 stale, unstamped or unknown (every problem is printed)
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semsearch as s  # noqa: E402

# USD per million input tokens for each profile's model, from openrouter.ai/api/v1/embeddings/models on 2026-10-31.
# Update this together with PROFILES in semsearch.py once eval.py has picked a model.
PRICE_PER_MTOK = {"prose": 0.06}
CHARS_PER_TOKEN = 3.5


def estimate(chars, profile):
    return chars / CHARS_PER_TOKEN / 1e6 * PRICE_PER_MTOK.get(profile, 0.0)


def stamp_current(ctx, profile, extracted, components, log):
    """Stamps components when every pack kind was extracted from the current packs. Returns the exit code."""
    if not ctx.has_pack():
        print("not stamped: no GTNH pack here (nothing to stamp)", file=sys.stderr)
        return 0
    if ctx.readonly:
        print("not stamped: read-only mode", file=sys.stderr)
        return 1
    ident, why = s.pack_identity(ctx)
    if ident is None:
        print("not stamped: %s" % why, file=sys.stderr)
        return 1
    stale = s.stale_kinds(extracted, ident["fingerprint"], profile)
    if stale:
        print("not stamped: %s not extracted from the current packs (%s)" % (", ".join(stale), ident["label"]), file=sys.stderr)
        return 1
    for c in components:
        if s.stamp_pack(ctx, c, ident["fingerprint"], "tools/gtnh-search/index.py") is None:
            print("not stamped: the packs changed during the run; run it again", file=sys.stderr)
            return 1
    print("stamped %s: %s (%s)" % (" and ".join(components), ident["label"], ident["fingerprint"]))
    return 0


def check(ctx, profile, path, log):
    """packstate's check of corpus and index, plus what the data itself records: each pack kind's docs.jsonl header
    and the index's meta must name the current packs. Returns the problems as (component, text)."""
    ps = s.load_packstate()
    if ps is None:
        return [("*", "tools/packstate.py could not be loaded (it needs Python 3.11 or newer)")]
    bad = ps.check(["corpus", "index"])
    fp = ps.state()["fingerprints"]["corpus"]
    for kind in s.pack_kinds(profile):
        cache = ctx.corpus / kind / "docs.jsonl"
        try:
            header, _ = s.read_jsonl(cache)
        except (OSError, ValueError):
            header = {}
        if header.get("pack") != fp:
            bad.append(("corpus", "%s: %s" % (cache, "extracted from other packs" if header.get("pack") else "packs unknown or missing")))
    index = s.read_index(path, log)
    if not index:
        bad.append(("index", "no index at %s" % path))
    else:
        stale = s.stale_kinds(index["meta"].get("corpus_pack"), fp, profile)
        if stale:
            bad.append(("index", "%s embeds %s docs not extracted from the current packs" % (path.name, ", ".join(stale))))
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(s.PROFILES), default=s.DEFAULT_PROFILE)
    ap.add_argument("--extract", action="store_true", help="re-read the pack even if its files look unchanged")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 unless the corpus and index are from the current packs")
    ap.add_argument("--seed", action="store_true", help="container start-up: fill the writable state directory")
    ap.add_argument("--force", action="store_true", help="with --seed: copy even if the state directory is current")
    ap.add_argument("--query")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--kind", choices=("any",) + s.KINDS, default="any")
    a = ap.parse_args()

    ctx = s.Context()
    # packstate (stamps, the tuxmine jar list) must see the same repository as the corpus.
    os.environ.setdefault("DAVE_AGENT_ROOT", str(ctx.root))
    profile = s.PROFILES[a.profile]
    path = s.index_path(ctx, a.profile)
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731

    if a.seed:
        if not ctx.state:
            print("GTNH_SEARCH_STATE is not set; nothing to seed", file=sys.stderr)
            return 1
        done = s.seed(ctx, force=a.force, log=log)
        print({True: "seeded %s" % ctx.state, False: "%s is current" % ctx.state, None: "seed did not run"}[done])
        living = Path(__file__).resolve().parents[1] / "living-wiki"
        if done is not None and (living / "living_wiki.py").is_file():
            sys.path.insert(0, str(living))
            import living_wiki  # noqa: E402  (creates the volume's living wiki only when it has none)
            wiki, created = living_wiki.ensure(ctx, log)
            print("living wiki created at %s" % wiki.dir if created else "living wiki: %s" % ("present" if wiki.exists() else "none (no wiki snapshot)"))
        return 1 if done is None else 0

    if a.extract:
        if ctx.readonly:
            print("read-only mode (GTNH_SEARCH_READONLY); nothing extracted", file=sys.stderr)
            return 1
        print("pack: %s" % (ctx.pack or "not found"), file=sys.stderr)
        err = s.fetch_extras(ctx, log)
        if err:
            print(err, file=sys.stderr)
            return 1
        # Under the build lock, so a running server's refresh never rewrites the same caches at the same time.
        with s.corpus_lock(ctx, a.profile):
            ctx.extracted = {}
            # lang first: quests and guide pages resolve item names from it.
            for kind in sorted(profile["kinds"], key=lambda k: k != "lang"):
                docs = s.load_docs(ctx, kind, force=True, log=log)
                print("%-9s %6d docs" % (kind, len(docs)))
            extracted = {k: v.get("pack") for k, v in ctx.extracted.items()}
        extras = ctx.extra_jars()
        if extras:
            print("tuxmine jars: %d read (%s)" % (sum(1 for e in extras if e["path"]), ", ".join(e["name"] for e in extras)))
            for p in s.replaced_jars(ctx):
                print("  replaces GTNH jar %s" % p.name)
        return stamp_current(ctx, a.profile, extracted, ["corpus"], log)

    if a.check:
        bad = check(ctx, a.profile, path, log)
        for c, why in bad:
            print("STALE %s: %s" % (c, why), file=sys.stderr)
        if not bad:
            print("corpus and index are current")
        return 1 if bad else 0

    if a.stats:
        with s.corpus_lock(ctx, a.profile):
            chunks = s.corpus_chunks(ctx, profile["kinds"], log)
        print("profile %s, model %s, $%.3f per M tokens (PRICE_PER_MTOK in index.py)"
              % (a.profile, profile["model"], PRICE_PER_MTOK.get(a.profile, 0.0)))
        print("%-9s %8s %8s %11s %9s" % ("kind", "docs", "chunks", "chars", "est. $"))
        total_chars = 0
        for kind in profile["kinds"]:
            cs = [c for c in chunks if c["kind"] == kind]
            chars = sum(len(s.embed_text(c)) for c in cs)
            total_chars += chars
            print("%-9s %8d %8d %11d %9.3f" % (kind, len({c["source"] for c in cs}), len(cs), chars, estimate(chars, a.profile)))
        print("%-9s %8d %8d %11d %9.3f" % ("total", len({c["source"] for c in chunks}), len(chunks), total_chars,
                                          estimate(total_chars, a.profile)))
        print("(tokens estimated at %.1f characters each)" % CHARS_PER_TOKEN)
        index = s.read_index(path, log)
        print("index:", index["meta"] if index else "none (or unreadable) at %s" % path)
        return 0

    key = s.load_key(ctx.root)
    if not key:
        print("OPENROUTER_API_KEY is not set (environment or .env at the repository root)", file=sys.stderr)
        return 2
    api = s.OpenRouter(key, profile["model"])

    if a.query:
        index = s.read_index(path, log)
        if not index:
            print("no index yet; run without --query first", file=sys.stderr)
            return 1
        print(s.format_hits(s.search(index, api.query(a.query), a.k, a.kind)))
        return 0

    if ctx.has_pack() and not ctx.readonly:
        err = s.fetch_extras(ctx, log)  # before any embedding, so a failed download costs nothing
        if err:
            print(err, file=sys.stderr)
            return 1
    index = s.build(ctx, api, path, a.profile, log=log)
    if not index:
        return 1
    return stamp_current(ctx, a.profile, index["meta"].get("corpus_pack"), ["corpus", "index"], log)


if __name__ == "__main__":
    sys.exit(main())
