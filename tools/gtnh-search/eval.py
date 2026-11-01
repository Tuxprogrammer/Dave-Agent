"""Retrieval eval for picking the prose embedding model: recall@k and MRR over real player questions.

  python3 -I tools/gtnh-search/eval.py --check                  every expected source exists in the corpus (no API calls)
  python3 -I tools/gtnh-search/eval.py --dry-run [--models ...]  chunks and estimated cost per model (no API calls)
  python3 -I tools/gtnh-search/eval.py --models voyageai/voyage-4,openai/text-embedding-3-small,qwen/qwen3-embedding-8b

Each model embeds the whole prose corpus (cheap at today's size; see --dry-run), or with --sample N only the chunks
of every expected source plus N seeded random distractors. Vectors are cached per model in
<index>/eval/<model>.npz, so a rerun only embeds new chunks. Questions are in eval/questions.jsonl: {"id",
"question", "expect": [source keys]}; a source key is what hits show, e.g. quest:<id>, guide:<ns>/<page>.md,
wiki:<Title>, lang:gregtech/tooltip/cleanroom.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import semsearch as s  # noqa: E402

QUESTIONS = HERE / "eval" / "questions.jsonl"
# Candidates and their USD price per million input tokens on openrouter.ai/api/v1/embeddings/models, 2026-10-31.
MODEL_PRICES = {
    "voyageai/voyage-4": 0.06,
    "voyageai/voyage-4-lite": 0.02,
    "voyageai/voyage-4-large": 0.12,
    "openai/text-embedding-3-small": 0.02,
    "openai/text-embedding-3-large": 0.13,
    "qwen/qwen3-embedding-8b": 0.01,
    "google/gemini-embedding-001": 0.15,
}
DEFAULT_MODELS = ("voyageai/voyage-4", "openai/text-embedding-3-small", "qwen/qwen3-embedding-8b")
KS = (1, 3, 5, 10)


def load_questions(path=QUESTIONS):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def check(chunks, questions):
    """Expected sources missing from the corpus, as (question id, source)."""
    have = {c["source"] for c in chunks}
    return [(q["id"], src) for q in questions for src in q["expect"] if src not in have]


def subset(chunks, questions, distractors, seed=7):
    want = {src for q in questions for src in q["expect"]}
    keep = [c for c in chunks if c["source"] in want]
    rest = [c for c in chunks if c["source"] not in want]
    random.Random(seed).shuffle(rest)
    return keep + rest[:distractors]


def score(index, embed_query, questions, ks=KS):
    """Doc-level ranking (one slot per source): hit rate at each k, MRR within max(ks), and per-question ranks."""
    top = max(ks)
    rows = []
    for q in questions:
        hits = s.search(index, embed_query(q["question"]), top, None, per_source=1)
        ranked = [h["source"] for h in hits]
        rank = next((i + 1 for i, src in enumerate(ranked) if src in q["expect"]), None)
        found = sum(1 for src in q["expect"] if src in ranked)
        rows.append({"id": q["id"], "rank": rank, "found": found, "expected": len(q["expect"]), "top3": ranked[:3]})
    n = max(1, len(rows))
    out = {"recall@%d" % k: sum(1 for r in rows if r["rank"] and r["rank"] <= k) / n for k in ks}
    out["mrr"] = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    out["coverage@%d" % top] = sum(r["found"] / r["expected"] for r in rows) / n
    return out, rows


def cost(chunks, model):
    chars = sum(len(s.embed_text(c)) for c in chunks)
    return chars, chars / 3.5 / 1e6 * MODEL_PRICES.get(model, float("nan"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="embed expected sources plus N random distractors, not the whole corpus")
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("-v", "--verbose", action="store_true", help="print each question's rank and top hits")
    a = ap.parse_args()

    ctx = s.Context()
    questions = load_questions(Path(a.questions))
    with s.corpus_lock(ctx):  # may rewrite the extraction caches; never alongside a server refresh
        chunks = s.corpus_chunks(ctx, s.PROFILES[s.DEFAULT_PROFILE]["kinds"])
    missing = check(chunks, questions)
    print("%d questions, %d expected sources, %d missing from the corpus"
          % (len(questions), sum(len(q["expect"]) for q in questions), len(missing)))
    for qid, src in missing:
        print("  missing: %s %s" % (qid, src))
    if a.check:
        return 1 if missing else 0

    models = [m.strip() for m in a.models.split(",") if m.strip()]
    pool = subset(chunks, questions, a.sample) if a.sample else chunks
    if a.dry_run:
        print("%d chunks to embed per model (%s)" % (len(pool), "expected + %d distractors" % a.sample if a.sample else "full corpus"))
        for m in models:
            chars, usd = cost(pool, m)
            print("  %-34s %.1f M chars, about $%.3f" % (m, chars / 1e6, usd))
        return 0

    key = s.load_key(ctx.root)
    if not key:
        print("OPENROUTER_API_KEY is not set (environment or .env at the repository root)", file=sys.stderr)
        return 2
    results = {}
    for m in models:
        api = s.OpenRouter(key, m)
        path = ctx.index / "eval" / (m.replace("/", "_").replace(":", "_") + ".npz")
        index = s.build(ctx, api, path, chunks=pool, log=lambda msg: print("  [%s] %s" % (m, msg), file=sys.stderr))
        if index is None:
            print("  [%s] build skipped (locked or read-only)" % m, file=sys.stderr)
            continue
        metrics, rows = score(index, api.query, questions)
        metrics["embed_cost"] = round(api.cost, 4)
        results[m] = {"metrics": metrics, "rows": rows}
        if a.verbose:
            for r in rows:
                print("  %s rank %-4s %s" % (r["id"], r["rank"], " | ".join(r["top3"])))
    ks = ["recall@%d" % k for k in KS]
    print("\n%-34s %s %7s %12s %9s" % ("model", " ".join("%9s" % k for k in ks), "MRR", "coverage@%d" % max(KS), "cost $"))
    for m, r in results.items():
        mt = r["metrics"]
        print("%-34s %s %7.3f %12.3f %9.4f" % (m, " ".join("%9.3f" % mt[k] for k in ks), mt["mrr"], mt["coverage@%d" % max(KS)], mt["embed_cost"]))
    out = ctx.index / "eval" / ("results-%d.json" % int(time.time()))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1))
    print("\nresults: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
