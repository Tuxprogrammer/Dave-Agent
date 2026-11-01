"""Offline tests for the living wiki: git layout, Dave's edits and their trailers, merging official updates (stub merger,
validation, fallback, deleted pages), seeding, the weekly job, the MCP server, and the Claude merger's command and
environment. No network, no embedding API, no claude calls."""

import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gtnh-search"))
sys.path.insert(0, str(HERE))
import test_semsearch as base  # noqa: E402  (blocks the network and clears GTNH_* variables)
import living_wiki as lw_mod  # noqa: E402
import merger as mg  # noqa: E402
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("living_wiki_server", HERE / "server.py")
lw_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lw_server)
import mirror_wiki  # noqa: E402
import semsearch as s  # noqa: E402
import update_wiki as uw  # noqa: E402

os.environ.pop("GTNH_WIKI_GIT", None)

A0 = "# Alpha\n\nAlpha intro.\n\n## Usage\n\nPut it in a machine.\n\n## Notes\n\nIt is blue.\n"
A1 = "# Alpha\n\nAlpha intro.\n\n## Usage\n\nPut it in an LV machine.\n\n## Notes\n\nIt is blue.\n"
B0 = "# Beta\n\nBeta needs 4 plates.\n\n## Tips\n\nUse a bender.\n"
B1 = "# Beta\n\nBeta needs 6 plates.\n\n## Tips\n\nUse a bender.\n\n## Automation\n\nAE2 works.\n"
C0 = "# Gamma\n\nGamma is old content.\n"
D0 = "# Delta\n\nDelta is old content too.\n"
E0 = "# Epsilon\n\nNever changes.\n"
F1 = "# Phi\n\nA new official page.\n"


def snapshot(d, date, pages):
    d = Path(d)
    store = mirror_wiki.Store(d)
    for title, text in pages.items():
        name = mirror_wiki.safe_name(title)
        for sub, ext, body in (("text", ".txt", text), ("raw", ".wiki", "raw " + text)):
            (d / sub).mkdir(parents=True, exist_ok=True)
            (d / sub / (name + ext)).write_text(body)
        store.manifest["pages"][title] = {"file": name + ".txt", "revid": len(text), "url": "u/" + title, "categories": []}
    store.manifest["source"] = "archive:miraheze-wiki-gtnhwiki-%s/gtnhwiki-%s.xml.gz" % (date, date)
    store.save()
    return d


OLD = {"Alpha": A0, "Beta": B0, "Gamma": C0, "Delta": D0, "Epsilon": E0}
NEW = {"Alpha": A1, "Beta": B1, "Epsilon": E0, "Phi": F1}


class WikiFixture:
    def __enter__(self):
        self.f = base.Fixture().__enter__()
        self.ctx = self.f.ctx
        self.tmp = self.f.root
        if self.ctx.wiki_dir.exists():
            import shutil
            shutil.rmtree(self.ctx.wiki_dir)
        snapshot(self.ctx.wiki_dir, "20260806", OLD)
        self.wiki, created = lw_mod.ensure(self.ctx)
        assert created
        self.new = snapshot(self.tmp / "new-snap", "20260904", NEW)
        return self

    def edit(self, page, text, section=None, reason="fix from recipe data", evidence="recipe 1234", asked_by="Alex"):
        return self.wiki.edit(page, text, reason, evidence, asked_by, section)

    def __exit__(self, *exc):
        self.f.__exit__(*exc)


class RepoTest(unittest.TestCase):
    def test_layout_and_seed_only_if_empty(self):
        with WikiFixture() as w:
            g = w.wiki.git
            self.assertEqual(g.rev("official"), g.rev("living"))
            self.assertEqual(w.wiki.official_item(), ("miraheze-wiki-gtnhwiki-20260806", "20260806"))
            self.assertEqual(sorted(w.wiki.pages()), sorted(OLD))
            self.assertEqual(g.out("rev-parse", "--abbrev-ref", "HEAD").strip(), "living")
            man = json.loads((w.ctx.wiki_dir / "manifest.json").read_text())
            self.assertEqual(man["living_commit"], g.rev("living"))
            # A second ensure, or an init over an existing repo, changes nothing.
            w.edit("Epsilon", "# Epsilon\n\nStill never changes.\n")
            head = g.rev("living")
            self.assertFalse(lw_mod.ensure(w.ctx)[1])
            self.assertFalse(w.wiki.init_from(w.new, "miraheze-wiki-gtnhwiki-20260904", "x", lambda m: None))
            self.assertEqual(g.rev("living"), head)

    def test_refuses_foreign_directory(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = s.Context(root=d, pack=Path(d) / "p", corpus=Path(d) / "corpus", index=Path(d) / "index",
                            memory=Path(d) / "m", gtsrc=[], readonly=False)
            (Path(d) / "wiki-git").mkdir()
            (Path(d) / "wiki-git" / "notes.txt").write_text("not ours")
            with self.assertRaises(RuntimeError):
                lw_mod.LivingWiki(ctx).init_from(snapshot(Path(d) / "snap", "20260806", OLD), "i", "f")


class EditTest(unittest.TestCase):
    def test_edit_trailers_round_trip(self):
        with WikiFixture() as w:
            title, sha = w.wiki.edit("beta", "Beta needs 5 plates on this server.", "pack recipe differs",
                                     "recipe_get gt.assembler 0xbeef", "Alex", "Beta", "needs 4 plates")
            self.assertEqual(title, "Beta")
            msg = w.wiki.git.out("log", "-1", "--format=%B", sha)
            t = lw_mod.parse_trailers(msg)
            self.assertEqual((t["Reason"], t["Evidence"], t["Asked-by"], t["Supersedes"], t["Dave-edit"]),
                             ("pack recipe differs", "recipe_get gt.assembler 0xbeef", "Alex", "needs 4 plates", "true"))
            _, hist = w.wiki.history("Beta")
            self.assertEqual(hist[0]["kind"], "dave")
            self.assertEqual(hist[0]["evidence"], "recipe_get gt.assembler 0xbeef")
            self.assertEqual(hist[-1]["kind"], "official")
            text = w.wiki.text("Beta")[1]
            self.assertTrue(text.startswith("# Beta\n\nBeta needs 5 plates on this server.\n\n## Tips"))  # H1 = intro only
            w.wiki.edit("Beta", "Beta is a plate.", "whole page", "e")
            self.assertEqual(w.wiki.text("Beta")[1], "Beta is a plate.\n")

    def test_section_edit_and_errors(self):
        with WikiFixture() as w:
            w.edit("Alpha", "## Notes\n\nIt is red here.", section="notes")
            text = w.wiki.text("Alpha")[1]
            self.assertIn("## Notes\n\nIt is red here.\n", text)
            self.assertIn("## Usage\n\nPut it in a machine.", text)
            with self.assertRaises(KeyError):
                w.edit("Alpha", "x", section="Nope")
            with self.assertRaises(KeyError):
                w.edit("Missing page", "x")
            with self.assertRaises(ValueError):
                w.wiki.edit("Alpha", "y", "reason", "  ")
            with self.assertRaises(ValueError):
                w.edit("Alpha", "## Notes\n\nIt is red here.", section="notes")  # no change

    def test_create_revert_and_export(self):
        with WikiFixture() as w:
            title, sha = w.wiki.create("GregGuns Rifle", "The rifle fires GT bullets.", "server mod", "GregGuns source")
            self.assertIn("GregGuns Rifle", w.wiki.pages())
            self.assertTrue(w.wiki.pages()["GregGuns Rifle"]["local"])
            rsha = w.wiki.revert(sha, "created by mistake")
            self.assertNotIn("GregGuns Rifle", w.wiki.pages())
            self.assertEqual(lw_mod.parse_trailers(w.wiki.git.out("log", "-1", "--format=%B", rsha))["Reverts"],
                             w.wiki.git.rev(sha))
            with self.assertRaises(ValueError):
                w.wiki.revert(w.wiki.git.rev("official"), "no")
            bundle = w.wiki.export(w.tmp / "out.bundle")
            self.assertEqual(w.wiki.git.run("bundle", "verify", "-q", str(bundle), check=False).returncode, 0)
            clone = w.tmp / "clone"
            subprocess.run(["git", "clone", "-q", "-b", "living", str(bundle), str(clone)], check=True, capture_output=True)
            self.assertTrue((clone / "manifest.json").is_file())


class MergeRulesTest(unittest.TestCase):
    def test_section_merge(self):
        base_t = "# T\n\nintro\n\n## A\n\na0\n\n## B\n\nb0\n\n## C\n\nc0\n"
        new_t = "# T\n\nintro\n\n## A\n\na1\n\n## B\n\nb1\n\n## D\n\nd1\n"
        living = "# T\n\nintro\n\n## A\n\na0\n\n## B\n\nb-dave\n\n## C\n\nc-dave\n\n## Local\n\nours\n"
        r = mg.merge_sections(base_t, new_t, living)
        t = r["merged_text"]
        self.assertIn("a1", t)            # official change where Dave did nothing
        self.assertIn("b-dave", t)        # contradiction: Dave's evidence-backed version
        self.assertNotIn("b1", t)
        self.assertIn("c-dave", t)        # Dave-edited section that official removed
        self.assertIn("## D\n\nd1", t)    # new official section
        self.assertIn("## Local\n\nours", t)
        self.assertTrue(r["flag"])
        self.assertIn("b1", r["losing_text"])
        self.assertEqual(mg.validate(r, base_t, new_t, living), [])
        self.assertIn("a1\n\n## B", t)  # one blank line before every heading

    def test_validation(self):
        new_t, living = "# T\n\n## Keep\n\n" + "x " * 100, "# T\n\n## Keep\n\n" + "y " * 100
        ok = {"merged_text": "# T\n\n## Keep\n\n" + "z " * 100}
        self.assertEqual(mg.validate(ok, "", new_t, living), [])
        self.assertTrue(mg.validate({"merged_text": "  "}, "", new_t, living))
        self.assertTrue(mg.validate("nope", "", new_t, living))
        bad = {"merged_text": ok["merged_text"] + "\n<<<<<<< ours\n"}
        self.assertIn("conflict markers", mg.validate(bad, "", new_t, living)[0])
        self.assertTrue(any("length" in p for p in mg.validate({"merged_text": "# T\n\n## Keep\n\nz"}, "", new_t, living)))
        no_head = {"merged_text": "# T\n\n" + "z " * 100}
        self.assertTrue(any("Keep" in p for p in mg.validate(no_head, "", new_t, living)))
        dropped = dict(no_head, dropped_headings=[{"heading": "Keep", "reason": "folded into the intro"}])
        self.assertEqual(mg.validate(dropped, "", new_t, living), [])
        history = {"merged_text": ok["merged_text"] + "\nThis was previously wrong."}
        self.assertTrue(any("history" in p for p in mg.validate(history, "", new_t, living)))

    def test_fallback_keeps_everything_out_of_the_page(self):
        r = mg.fallback("# T\n\n## A\n\na0\n", "# T\n\n## A\n\na1\n\n## B\n\nb1\n", "# T\n\n## A\n\na-dave\n", "bad output")
        self.assertTrue(r["flag"])
        self.assertIn("bad output", r["flag_reason"])
        self.assertIn("a-dave", r["merged_text"])
        self.assertIn("## B", r["merged_text"])
        self.assertEqual(r["losing_text"].strip(), "## A\n\na1")
        for leak in ("needs review", "Server corrections", "official update", "a1\n"):
            self.assertNotIn(leak, r["merged_text"])

    def test_history_lint(self):
        self.assertEqual(lw_mod.history_warnings("The EBF needs 2 hatches."), [])
        warned = lw_mod.history_warnings("The guide used to say 4; previously wrong.")
        self.assertIn("previously", warned)
        self.assertTrue(any("used to" in x for x in warned))


class BadMerger:
    name = "bad"

    def merge(self, page, base_t, new_t, living, edits):
        return {"merged_text": "<<<<<<< ours\nbroken\n>>>>>>> theirs\n"}


class RaisingMerger:
    name = "raising"

    def merge(self, *a):
        raise RuntimeError("model unavailable")


class SpyMerger(mg.StubMerger):
    def __init__(self):
        self.calls = []

    def merge(self, page, base_t, new_t, living, edits):
        self.calls.append((page, base_t, new_t, living, edits))
        return super().merge(page, base_t, new_t, living, edits)


class UpgradeTest(unittest.TestCase):
    def dave_edits(self, w):
        w.edit("Alpha", "## Notes\n\nIt is red on this server.", section="Notes")              # non-overlapping with official
        w.edit("Beta", "# Beta\n\nBeta needs 5 plates.\n\n## Tips\n\nUse a bender.\n")          # same line as official
        w.edit("Delta", "# Delta\n\nDelta is still used here.\n")                               # deleted officially

    def test_upgrade_with_stub(self):
        with WikiFixture() as w:
            self.dave_edits(w)
            spy = SpyMerger()
            index_path = s.index_path(w.ctx)
            fake = base.FakeEmbedder()
            rep = w.wiki.upgrade(w.new, "miraheze-wiki-gtnhwiki-20260904", "gtnhwiki-20260904.xml.gz", spy, fake)
            p = rep["pages"]
            self.assertEqual(p["clean"], ["Phi"])
            self.assertEqual(p["auto_merged"], ["Alpha"])
            self.assertEqual(p["llm_merged"], ["Beta"])
            self.assertEqual(p["deleted"], ["Gamma"])
            self.assertEqual(p["kept_deleted"], ["Delta"])
            self.assertEqual(sorted(f["page"] for f in p["flagged"]), ["Beta", "Delta"])
            # The merger saw base, new official, living and Dave's trailers for the conflicted page only.
            self.assertEqual([c[0] for c in spy.calls], ["Beta"])
            self.assertEqual(spy.calls[0][4][0]["evidence"], "recipe 1234")
            g = w.wiki.git
            self.assertEqual(g.rev("living"), rep["merged"])
            self.assertEqual(len(g.log("official")), 2)
            pages = w.wiki.pages()
            self.assertNotIn("Gamma", pages)
            self.assertIn("Delta", pages)
            self.assertIn("Phi", pages)
            alpha = w.wiki.text("Alpha")[1]
            self.assertIn("LV machine", alpha)
            self.assertIn("red on this server", alpha)
            beta = w.wiki.text("Beta")[1]
            self.assertIn("5 plates", beta)
            self.assertIn("## Automation", beta)
            for leak in ("6 plates", "previously", "needs review", "official"):
                self.assertNotIn(leak, beta)
            # Report in the tree and outside it; review queue outside the page tree.
            self.assertIn("reports/merge-miraheze-wiki-gtnhwiki-20260904.json", g.out("ls-tree", "-r", "--name-only", "living"))
            queue = [json.loads(l) for l in w.wiki.review_path.read_text().splitlines()]
            beta_flag = next(q for q in queue if q["page"] == "Beta")
            self.assertIn("6 plates", beta_flag["losing_text"])
            self.assertEqual(len(w.wiki.open_reviews("Beta")), 1)
            msg = g.out("log", "-1", "--format=%B", "living")
            self.assertIn("Page: Beta", msg)
            # Search corpus: materialized from living, with Dave-edit metadata; index rebuilt.
            man = json.loads((w.ctx.wiki_dir / "manifest.json").read_text())
            self.assertEqual(man["living_commit"], g.rev("living"))
            self.assertTrue(man["pages"]["Beta"]["edited_by_dave"])
            self.assertNotIn("edited_by_dave", man["pages"]["Phi"])
            idx = s.load_index(index_path)
            self.assertIn("wiki:Phi", {c["source"] for c in idx["chunks"]})
            self.assertNotIn("wiki:Gamma", {c["source"] for c in idx["chunks"]})
            beta_chunks = [c for c in idx["chunks"] if c["source"] == "wiki:Beta"]
            self.assertTrue(any(c["meta"].get("edited_by_dave") for c in beta_chunks))
            self.assertEqual([x.name for x in w.ctx.corpus.iterdir() if x.name.startswith(".")], [])
            # Resolving the review flag.
            w.wiki.edit("Beta", "Beta needs 5 plates.", "checked again", "recipe 1234", "Alex", None, None, True)
            self.assertEqual(w.wiki.open_reviews("Beta"), [])

    def test_bad_or_failing_merger_uses_fallback(self):
        for m in (BadMerger(), RaisingMerger()):
            with WikiFixture() as w:
                self.dave_edits(w)
                rep = w.wiki.upgrade(w.new, "miraheze-wiki-gtnhwiki-20260904", "f", m, None)
                self.assertEqual(rep["pages"]["fallback"], ["Beta"])
                self.assertIn("Beta", [f["page"] for f in rep["pages"]["flagged"]])
                beta = w.wiki.text("Beta")[1]
                self.assertNotIn("<<<<<<<", beta)
                self.assertIn("5 plates", beta)

    def test_failed_build_changes_nothing(self):
        with WikiFixture() as w:
            self.dave_edits(w)
            s.build(w.ctx, base.FakeEmbedder(), s.index_path(w.ctx))
            g = w.wiki.git
            before = (g.rev("official"), g.rev("living"), (w.ctx.wiki_dir / "manifest.json").read_text(),
                      s.index_path(w.ctx).read_bytes())
            with self.assertRaises(RuntimeError):
                w.wiki.upgrade(w.new, "miraheze-wiki-gtnhwiki-20260904", "f", mg.StubMerger(), base.FailingEmbedder())
            after = (g.rev("official"), g.rev("living"), (w.ctx.wiki_dir / "manifest.json").read_text(),
                     s.index_path(w.ctx).read_bytes())
            self.assertEqual(before, after)
            self.assertFalse(g.out("status", "--porcelain"))
            self.assertFalse(w.wiki.review_path.exists())

    def test_untouched_wiki_fast_forwards_everything(self):
        with WikiFixture() as w:
            rep = w.wiki.upgrade(w.new, "miraheze-wiki-gtnhwiki-20260904", "f", RaisingMerger(), None)
            self.assertEqual(rep["counts"]["conflicted"], 0)
            self.assertEqual(sorted(rep["pages"]["clean"]), ["Alpha", "Beta", "Phi"])
            self.assertEqual(sorted(rep["pages"]["deleted"]), ["Delta", "Gamma"])
            self.assertEqual(w.wiki.text("Beta")[1], B1)


def gz_dump(pages):
    return gzip.compress(base.dump_xml([(t, [(i + 1, x)]) for i, (t, x) in enumerate(pages.items())]))


class WeeklyJobTest(unittest.TestCase):
    def job(self, w, http, embedder="fake", merger=None, **kw):
        emb = base.FakeEmbedder() if embedder == "fake" else embedder
        return uw.run(w.ctx, http, lambda: emb, lambda: merger or mg.StubMerger(), **kw)

    def test_check_current_and_update(self):
        with WikiFixture() as w:
            w.edit("Epsilon", "# Epsilon\n\nOn this server it changes.\n")
            self.assertIn("up to date", self.job(w, base.FakeHttp([base.OLD_ITEM.replace("0904", "0806")], b""))[1])
            payload = gz_dump({"Alpha": "Alpha intro.", "Beta": "Beta needs 4 plates.", "Epsilon": "Never changes.",
                               "Zeta": "== Info ==\nNew page."})
            http = base.FakeHttp([base.NEW_ITEM], payload)
            code, summary = self.job(w, http, check=True)
            self.assertEqual((code, http.downloads), (0, []))
            self.assertTrue(summary.startswith("update available"))
            code, summary = self.job(w, http)
            self.assertEqual(code, 0, summary)
            self.assertTrue(summary.startswith("living wiki miraheze-wiki-gtnhwiki-20261004:"), summary)
            self.assertEqual(w.wiki.official_item()[1], "20261004")
            self.assertIn("On this server it changes.", w.wiki.text("Epsilon")[1])
            self.assertIn("Zeta", w.wiki.pages())
            self.assertEqual([x.name for x in w.ctx.corpus.iterdir() if x.name.startswith(".")], [])

    def test_md5_mismatch_and_no_key_keep_state(self):
        with WikiFixture() as w:
            g = w.wiki.git
            before = (g.rev("official"), g.rev("living"))
            payload = gz_dump({"Epsilon": "x"})
            code, summary = self.job(w, base.FakeHttp([base.NEW_ITEM], payload, md5="0" * 32))
            self.assertEqual(code, 1)
            self.assertIn("md5 mismatch", summary)
            code, _ = self.job(w, base.FakeHttp([base.NEW_ITEM], payload), embedder=None)
            self.assertEqual(code, 2)
            code, summary = self.job(w, base.FakeHttp([base.NEW_ITEM], gzip.compress(b"<mediawiki><page><title>x")))
            self.assertEqual(code, 1)
            self.assertEqual((g.rev("official"), g.rev("living")), before)
            with s.file_lock(w.ctx.jobs_lock()):
                self.assertTrue(self.job(w, base.FakeHttp([base.NEW_ITEM], payload))[1].startswith("skipped"))
            self.assertEqual([x.name for x in w.ctx.corpus.iterdir() if x.name.startswith(".")], [])

    def test_shrunken_dump_refused(self):
        with WikiFixture() as w:
            code, summary = self.job(w, base.FakeHttp([base.NEW_ITEM], gz_dump({"Only": "one page"})))
            self.assertEqual(code, 1)
            self.assertIn("refusing", summary)


class SeedTest(unittest.TestCase):
    def state_ctx(self, w):
        return s.Context(root=w.tmp, pack=w.tmp / "nopack", corpus=w.ctx.corpus, index=w.ctx.index,
                         memory=w.ctx.memory, gtsrc=[], readonly=False, state=w.tmp / "volume")

    def test_volume_wiki_survives_new_image_and_newer_image_dump_merges(self):
        with base.Fixture() as f:
            import shutil
            shutil.rmtree(f.ctx.wiki_dir)
            snapshot(f.ctx.wiki_dir, "20260806", OLD)
            s.build(f.ctx, base.FakeEmbedder(), s.index_path(f.ctx))

            class W:
                tmp, ctx = f.root, f.ctx
            vol = self.state_ctx(W)
            self.assertTrue(s.seed(vol))
            wiki, created = lw_mod.ensure(vol)
            self.assertTrue(created)
            self.assertEqual(wiki.dir, f.root / "volume" / "wiki-git")
            wiki.edit("Beta", "# Beta\n\nBeta needs 5 plates.\n\n## Tips\n\nUse a bender.\n", "differs", "recipe 1", "Alex")
            wiki.sync()
            # A new image with a newer official dump: the re-seed keeps the volume's wiki ...
            shutil.rmtree(f.ctx.wiki_dir)
            snapshot(f.ctx.wiki_dir, "20260904", NEW)
            self.assertTrue(s.seed(vol))
            self.assertFalse(lw_mod.ensure(vol)[1])
            self.assertIn("5 plates", (vol.wiki_dir / "text" / (mirror_wiki.safe_name("Beta") + ".txt")).read_text())
            self.assertEqual(wiki.official_item()[1], "20260806")
            # ... and the weekly job merges the image's dump instead of copying it.
            self.assertEqual(uw.seed_candidate(vol)[0], "miraheze-wiki-gtnhwiki-20260904")
            code, summary = uw.run(vol, base.FakeHttp([base.OLD_ITEM], b""), lambda: base.FakeEmbedder(),
                                   lambda: mg.StubMerger())
            self.assertEqual(code, 0, summary)
            self.assertEqual(wiki.official_item()[1], "20260904")
            beta = wiki.text("Beta")[1]
            self.assertIn("5 plates", beta)
            self.assertIn("## Automation", beta)

    def test_living_snapshot_is_never_an_official_seed(self):
        with WikiFixture() as w:
            vol = SeedTest.state_ctx(self, w)
            vol.seed_corpus = w.ctx.corpus  # its wiki is materialized from living
            self.assertIsNone(uw.seed_candidate(vol))


class ServerTest(unittest.TestCase):
    def call(self, svc, name, **args):
        r = lw_server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return r["result"]["content"][0]["text"], r["result"]["isError"]

    def test_tools(self):
        with WikiFixture() as w:
            requests = []

            class R:
                def request(self):
                    requests.append(1)
            svc = lw_server.Service(w.ctx, R())
            names = [t["name"] for t in lw_server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
            self.assertEqual(names, ["wiki_get", "wiki_search_titles", "wiki_edit", "wiki_create", "wiki_history", "wiki_revert"])
            init = lw_server.handle(svc, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})["result"]
            self.assertIn("WHAT IS TRUE NOW", init["instructions"])
            self.assertEqual(self.call(svc, "wiki_search_titles", prefix="e")[0].split("\n")[0], "Epsilon")
            text, err = self.call(svc, "wiki_edit", page="Alpha", section="Notes", new_text="It used to be blue.",
                                  reason="r", evidence="e")
            self.assertTrue(err)
            self.assertIn("narrates history", text)
            self.assertEqual(requests, [])
            text, err = self.call(svc, "wiki_edit", page="Alpha", section="Notes", new_text="It is red.",
                                  reason="pack texture differs", evidence="assets/x.png", asked_by="Sam")
            self.assertFalse(err, text)
            self.assertEqual(requests, [1])
            text, _ = self.call(svc, "wiki_get", page="alpha")
            self.assertIn("locally edited", text)
            self.assertIn("pack texture differs (asked by Sam)", text)
            self.assertIn("It is red.", text)
            hist = json.loads(self.call(svc, "wiki_history", page="Alpha")[0])
            self.assertEqual(hist["history"][0]["asked_by"], "Sam")
            text, err = self.call(svc, "wiki_create", page="GregGuns", text="Guns.", reason="server mod", evidence="jar")
            self.assertFalse(err, text)
            self.assertIn("GregGuns", json.loads((w.ctx.wiki_dir / "manifest.json").read_text())["pages"])
            self.assertTrue(self.call(svc, "wiki_edit", page="Nope", new_text="x", reason="r", evidence="e")[1])
            commit = hist["history"][0]["commit"]
            self.assertFalse(self.call(svc, "wiki_revert", commit=commit, reason="wrong")[1])
            self.assertIn("It is blue.", self.call(svc, "wiki_get", page="Alpha")[0])

ITEM2, ITEM3 = "miraheze-wiki-gtnhwiki-20260904", "miraheze-wiki-gtnhwiki-20261004"


class FixedMerger:
    """Returns a fixed reply built from the inputs."""
    name = "fixed"

    def __init__(self, reply):
        self.reply = reply

    def merge(self, page, base_t, new_t, living, edits):
        return self.reply(base_t, new_t, living)


class ReviewFixesTest(unittest.TestCase):
    """One test per finding of the 2026-11-01 review."""

    def test_moved_page_dave_edited_is_kept_and_flagged(self):  # 1
        with WikiFixture() as w:
            w.edit("Alpha", "Put it in a steam machine.", section="Usage")
            moved = dict(OLD)
            moved["Alpha (item)"] = moved.pop("Alpha").replace("a machine.", "an MV machine.")
            snap = snapshot(w.tmp / "moved", "20260904", moved)
            rep = w.wiki.upgrade(snap, ITEM2, "f", SpyMerger(), None)
            self.assertEqual(rep["pages"]["kept_deleted"], ["Alpha"])
            self.assertIn("Alpha (item)", rep["pages"]["flagged"][0]["reason"])
            self.assertIn("steam machine", w.wiki.text("Alpha")[1])
            self.assertIn("MV machine", w.wiki.text("Alpha (item)")[1])
            self.assertEqual(rep["counts"]["llm_merged"], 0)
            self.assertEqual(len(w.wiki.open_reviews("Alpha")), 1)

    def test_conflicts_are_read_from_stage_blobs(self):  # 1
        with WikiFixture() as w:
            w.edit("Beta", "Beta needs 5 plates.", section="Beta")
            spy = SpyMerger()
            rep = w.wiki.upgrade(w.new, ITEM2, "f", spy, None)
            page, base_t, new_t, living, _ = spy.calls[0]
            self.assertEqual((page, base_t, new_t), ("Beta", B0, B1))
            self.assertIn("5 plates", living)
            c = rep["conflicts"]["Beta"]
            self.assertEqual(w.wiki.git.cat(c["living_blob"]), living)
            self.assertEqual(c["living_text"], living)

    def test_audit_catches_dropped_text(self):  # 2
        base_t = "# T\n\nIt needs 4 plates.\n\n## Use\n\nPut it in a machine.\n"
        living = "# T\n\nIt needs 5 plates.\n\n## Use\n\nPut it in a machine.\n\n## GregGuns\n\nFires GT bullets.\n"
        new_t = "# T\n\nIt needs 6 plates.\n\n## Use\n\nPut it in an LV machine.\n"
        # Official verbatim drops Dave's number and section without saying so: rejected, so the fallback keeps them.
        problems = mg.check({"merged_text": new_t, "flag": False}, base_t, new_t, living)
        self.assertTrue(problems and "dropped Dave's text" in problems[0], problems)
        # One number differs: no fuzzy match lets "6 plates" stand in for "5 plates".
        self.assertTrue(any(g["line"] == "It needs 5 plates." for g in mg.audit(new_t, base_t, new_t, living)))
        # Reported in losing_text: accepted, but always flagged.
        reported = {"merged_text": new_t + "\n## GregGuns\n\nFires GT bullets.\n", "flag": False,
                    "losing_text": "It needs 5 plates."}
        self.assertEqual(mg.check(reported, base_t, new_t, living), [])
        self.assertTrue(reported["flag"])
        self.assertIn("Dave's text replaced in T", reported["flag_reason"])
        # Official's change silently dropped: flagged, and the official line goes to losing_text.
        keeps_dave = {"merged_text": living, "flag": False}
        self.assertEqual(mg.check(keeps_dave, base_t, new_t, living), [])
        self.assertTrue(keeps_dave["flag"])
        self.assertIn("Put it in an LV machine.", keeps_dave["losing_text"])
        self.assertIn("official changes not used", keeps_dave["flag_reason"])

    def test_merger_dropping_dave_falls_back(self):  # 2
        with WikiFixture() as w:
            w.edit("Beta", "Beta needs 5 plates.", section="Beta")
            rep = w.wiki.upgrade(w.new, ITEM2, "f", FixedMerger(lambda b, n, l: {"merged_text": n, "flag": False}), None)
            self.assertEqual(rep["pages"]["fallback"], ["Beta"])
            self.assertIn("5 plates", w.wiki.text("Beta")[1])
            self.assertIn("dropped Dave's text", w.wiki.open_reviews("Beta")[0]["reason"])

    def test_ref_transaction_stale_locks_and_report_replay(self):  # 3
        with WikiFixture() as w:
            g = w.wiki.git
            w.edit("Beta", "Beta needs 5 plates.", section="Beta")
            (w.wiki.dir / ".git" / "index.lock").write_text("")  # a killed git process
            (w.wiki.dir / ".git" / "refs" / "heads" / "living.lock").write_text("")
            rep = w.wiki.upgrade(w.new, ITEM2, "f", mg.StubMerger(), None)
            self.assertEqual((g.rev("living"), w.wiki.official_item()[0]), (rep["merged"], ITEM2))
            self.assertFalse(g.out("status", "--porcelain"))
            # Both refs or neither: a stale old value for living refuses the whole transaction.
            off, liv = g.rev("official"), g.rev("living")
            with self.assertRaises(RuntimeError):
                w.wiki.commit_refs(off, g.rev("official~1"), g.rev("official~1"), liv)
            self.assertEqual((g.rev("official"), g.rev("living")), (off, liv))
            # Report and review rows lost to a crash after the transaction are replayed by sync, once.
            rows = w.wiki.review_rows()
            w.wiki.review_path.unlink()
            for f in w.wiki.reports_dir.iterdir():
                f.unlink()
            w.wiki.sync()
            self.assertEqual(w.wiki.review_rows(), rows)
            w.wiki.write_report(json.loads(g.show("living", "reports/merge-%s.json" % ITEM2)))
            self.assertEqual(len(w.wiki.review_rows()), len(rows))

    def test_resolving_settles_only_existing_flags(self):  # 4
        with WikiFixture() as w:
            w.edit("Beta", "Beta needs 5 plates.", section="Beta")
            w.wiki.upgrade(w.new, ITEM2, "f", mg.StubMerger(), None)
            self.assertEqual(len(w.wiki.open_reviews("Beta")), 1)
            w.wiki.edit("Beta", "Beta needs 5 plates here.", "settle", "recipe 9", section="Beta", resolves_review=True)
            self.assertEqual(w.wiki.open_reviews("Beta"), [])
            newer = snapshot(w.tmp / "newer", "20261004", dict(NEW, Beta=B1.replace("6 plates", "7 plates")))
            w.wiki.upgrade(newer, ITEM3, "f", mg.StubMerger(), None)
            self.assertEqual([r["item"] for r in w.wiki.open_reviews("Beta")], [ITEM3])

    def test_truncation_shaped_whole_page_edit_refused(self):  # 5
        with WikiFixture() as w:
            body = "\n".join("Line %d of a very long table." % i for i in range(3000))
            w.edit("Epsilon", "# Epsilon\n\n" + body + "\n")
            old = w.wiki.text("Epsilon")[1]
            self.assertGreater(len(old), lw_mod.VIEW_LIMIT)
            shown = old[:lw_mod.VIEW_LIMIT].replace("Line 7 of", "Line seven of")
            with self.assertRaises(ValueError):
                w.edit("Epsilon", shown)
            with self.assertRaises(ValueError):
                w.edit("Epsilon", shown + "\n" + lw_mod.TRUNCATED)
            self.assertEqual(w.wiki.text("Epsilon")[1], old)
            w.edit("Epsilon", old.replace("Line 7 of", "Line seven of"))  # the whole page: fine
            w.wiki.edit("Epsilon", "# Epsilon\n\nShort now.", "split the table out", "e", confirm_whole_page=True)
            self.assertEqual(w.wiki.text("Epsilon")[1], "# Epsilon\n\nShort now.\n")

    def test_sync_waits_for_the_lock(self):  # 6
        with WikiFixture() as w:
            w.edit("Epsilon", "# Epsilon\n\nChanged.\n")
            old_wait, lw_mod.LOCK_WAIT = lw_mod.LOCK_WAIT, 0
            try:
                with w.wiki.lock() as held:
                    self.assertTrue(held)
                    self.assertFalse(w.wiki.sync())
            finally:
                lw_mod.LOCK_WAIT = old_wait
            self.assertTrue(w.wiki.sync())

    def test_head_off_living_is_restored(self):  # 7
        with WikiFixture() as w:
            g = w.wiki.git
            off = g.rev("official")
            g.run("checkout", "-q", "official")
            w.edit("Epsilon", "# Epsilon\n\nChecked.\n")
            self.assertEqual(g.rev("official"), off)
            self.assertEqual(g.out("symbolic-ref", "HEAD").strip(), "refs/heads/living")
            self.assertIn("Checked.", g.show("living", "text/" + mirror_wiki.safe_name("Epsilon") + ".txt"))

    def test_merger_runs_outside_the_lock(self):  # 8
        with WikiFixture() as w:
            w.edit("Beta", "Beta needs 5 plates.", section="Beta")
            seen = []

            class EditingMerger(SpyMerger):
                def merge(inner, *a):
                    with s.file_lock(w.wiki.lock_path) as free:
                        seen.append(free)
                    if len(inner.calls) == 0:  # Dave edits another page while the model runs
                        w.edit("Epsilon", "# Epsilon\n\nEdited during the merge.\n")
                    return super().merge(*a)
            m = EditingMerger()
            rep = w.wiki.upgrade(w.new, ITEM2, "f", m, None)
            self.assertEqual(seen, [True])
            self.assertEqual([c[0] for c in m.calls], ["Beta"])  # replayed under the lock, not called again
            self.assertEqual(w.wiki.git.rev("living"), rep["merged"])
            self.assertIn("Edited during the merge.", w.wiki.text("Epsilon")[1])
            self.assertIn("5 plates", w.wiki.text("Beta")[1])

    def test_sync_failure_after_a_saved_edit_is_not_an_error(self):  # 9
        with WikiFixture() as w:
            class R:
                def request(self):
                    pass
            svc = lw_server.Service(w.ctx, R())

            def broken(log=None):
                raise OSError("disk full")
            svc.wiki.sync = broken
            r = lw_server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "wiki_edit", "arguments": {"page": "Epsilon", "new_text": "# Epsilon\n\nOk.", "reason": "r",
                                                   "evidence": "e"}}})["result"]
            self.assertFalse(r["isError"])
            self.assertIn("refresh failed: disk full", r["content"][0]["text"])

    def test_dotted_titles_reach_the_corpus(self):  # 10
        with WikiFixture() as w:
            w.wiki.create("Wait... what", "A page.", "server page", "jar")
            w.wiki.sync()
            self.assertIn("Wait... what", json.loads((w.ctx.wiki_dir / "manifest.json").read_text())["pages"])

    def test_bad_messages_do_not_kill_the_server(self):  # 11
        with WikiFixture() as w:
            svc = lw_server.Service(w.ctx, False)
            self.assertEqual(lw_server.handle(svc, [1, 2])["error"]["code"], -32600)
            r = lw_server.handle(svc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": [1]})
            self.assertTrue(r["result"]["isError"])
            r = lw_server.handle(svc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                       "params": {"name": "wiki_get", "arguments": "Alpha"}})
            self.assertTrue(r["result"]["isError"])

    def test_noop_revert(self):  # 12
        with WikiFixture() as w:
            _, c1 = w.edit("Alpha", "Put it in a steam machine.", section="Usage")
            w.edit("Alpha", "Put it in a machine.", section="Usage")
            with self.assertRaisesRegex(ValueError, "already undone"):
                w.wiki.revert(c1, "undo")
            self.assertFalse((w.wiki.dir / ".git" / "REVERT_HEAD").exists())

    def test_section_edit_ignores_headings_in_code(self):  # 13
        text = "# T\n\n## Script\n\n```\n# not a heading\nrun()\n```\n\nafter code\n\n## Next\n\nn\n"
        out = lw_mod.replace_section(text, "Script", "new body")
        self.assertEqual(out, "# T\n\n## Script\n\nnew body\n\n## Next\n\nn\n")


class ClaudeMergerTest(unittest.TestCase):
    def merger(self, tmp):
        config, _ = mg.load_dave_config()
        cfg = config.load()
        cfg["paths"] = dict(cfg["paths"], run=Path(tmp) / "run", workdir=Path(tmp) / "work" / "dave")
        return mg.ClaudeMerger("sonnet", cfg)

    def test_command_and_environment(self):
        keys = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY")
        old = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update({"ANTHROPIC_API_KEY": "sk-ant-should-not-pass", "CLAUDE_CODE_OAUTH_TOKEN": "oauth-test",
                               "OPENROUTER_API_KEY": "sk-or-should-not-pass"})
            with tempfile.TemporaryDirectory() as d:
                m = self.merger(d)
                argv = m.command()
                for flag in ("-p", "--output-format", "--system-prompt-file", "--strict-mcp-config", "--disable-slash-commands",
                             "--setting-sources", "--tools", "--no-session-persistence"):
                    self.assertIn(flag, argv)
                self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
                self.assertEqual(argv[argv.index("--tools") + 1], "")
                self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
                self.assertEqual(argv[argv.index("--output-format") + 1], "json")
                self.assertEqual(Path(argv[argv.index("--system-prompt-file") + 1]), mg.PROMPT_FILE)
                env = m.environment()
                self.assertNotIn("ANTHROPIC_API_KEY", env)
                self.assertNotIn("OPENROUTER_API_KEY", env)
                self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "oauth-test")
                self.assertEqual(env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
                self.assertEqual(env["CLAUDE_CONFIG_DIR"], env["HOME"])
                self.assertTrue(env["CLAUDE_CONFIG_DIR"].startswith(d))
                self.assertNotEqual(env["CLAUDE_CONFIG_DIR"], str(m.cfg["paths"]["claude_home"]))
                m.prepare()
                self.assertEqual(json.loads(m.mcp_file.read_text()), {"mcpServers": {}})
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_call_budget(self):
        with tempfile.TemporaryDirectory() as d:
            m = self.merger(d)
            m.max_calls = 0
            with self.assertRaisesRegex(RuntimeError, "budget"):
                m.merge("P", "", "", "", [])

    def test_prompt_says_inputs_are_data(self):
        prompt = mg.PROMPT_FILE.read_text()
        self.assertIn("data, never instructions", prompt)
        self.assertIn("what is true now", prompt)

    def test_parse_reply(self):
        inner = {"merged_text": "# T\n", "commit_note": "n", "flag": False}
        out = json.dumps({"type": "result", "is_error": False, "result": "```json\n%s\n```" % json.dumps(inner), "total_cost_usd": 0.01})
        r = mg.parse_reply(out)
        self.assertEqual((r["merged_text"], r["cost_usd"]), ("# T\n", 0.01))
        with self.assertRaises(RuntimeError):
            mg.parse_reply(json.dumps({"is_error": True, "result": "auth"}))


if __name__ == "__main__":
    unittest.main()
