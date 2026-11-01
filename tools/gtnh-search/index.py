"""Builds or queries the GTNH search index from the command line.

  python3 -I tools/gtnh-search/index.py --extract      re-read the pack into data/corpus/<kind>/ (no API calls)
  python3 -I tools/gtnh-search/index.py --stats        chunk counts per kind and an estimated full-build cost, no API calls
  python3 -I tools/gtnh-search/index.py --seed         copy the baked corpus and index into GTNH_SEARCH_STATE if needed
  python3 -I tools/gtnh-search/index.py                incremental build (embeds only changed chunks)
  python3 -I tools/gtnh-search/index.py --query "best nitrogen source at HV" [-k 8] [--kind quest]
"""

import argparse
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(s.PROFILES), default=s.DEFAULT_PROFILE)
    ap.add_argument("--extract", action="store_true", help="re-read the pack even if its files look unchanged")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--seed", action="store_true", help="container start-up: fill the writable state directory")
    ap.add_argument("--force", action="store_true", help="with --seed: copy even if the state directory is current")
    ap.add_argument("--query")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--kind", choices=("any",) + s.KINDS, default="any")
    a = ap.parse_args()

    ctx = s.Context()
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
        # Under the build lock, so a running server's refresh never rewrites the same caches at the same time.
        with s.corpus_lock(ctx, a.profile):
            # lang first: quests and guide pages resolve item names from it.
            for kind in sorted(profile["kinds"], key=lambda k: k != "lang"):
                docs = s.load_docs(ctx, kind, force=True, log=log)
                print("%-9s %6d docs" % (kind, len(docs)))
        return 0

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

    index = s.build(ctx, api, path, a.profile, log=log)
    return 0 if index else 1


if __name__ == "__main__":
    sys.exit(main())
