"""Offline tests for the GTNH search tool: sources, chunking, incremental builds, ranking, the MCP protocol, the wiki
converter, the weekly wiki job, seeding and the eval scorer. No API calls and no downloads: urlopen is replaced with
a function that fails the test, and the wiki job gets a stub HTTP client."""

import gzip
import hashlib
import http.client
import io
import json
import os
import shutil
import struct
import base64
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from email.message import Message
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import semsearch as s  # noqa: E402
import server  # noqa: E402
import mirror_wiki  # noqa: E402
import eval as ev  # noqa: E402
import update_wiki as uw  # noqa: E402


def no_network(*a, **k):
    raise AssertionError("tests must not touch the network")


urllib.request.urlopen = no_network
# The tests set every path themselves; a developer's environment must not redirect them.
for _var in ("GTNH_SEARCH_STATE", "GTNH_SEARCH_DATA", "GTNH_SEARCH_INDEX_DIR", "GTNH_SEARCH_READONLY", "GTNH_SEARCH_ROOT",
             "GTNH_MEMORY_DIR", "GTNH_PACK_DIR", "OPENROUTER_API_KEY_FILE"):
    os.environ.pop(_var, None)


class FakeEmbedder:
    """Deterministic bag-of-words vectors, so related texts land close together."""

    model = "fake/model"

    def __init__(self):
        self.calls = 0
        self.embedded = 0

    @staticmethod
    def vec(text):
        v = np.zeros(64, np.float32)
        for w in text.lower().split():
            v[int(hashlib.md5(w.strip(".,:;()?").encode()).hexdigest(), 16) % 64] += 1
        return v

    def documents(self, texts):
        self.calls += 1
        self.embedded += len(texts)
        return [self.vec(t) for t in texts]

    def query(self, text):
        return self.vec(text)


def qid(high, low):
    return base64.urlsafe_b64encode(struct.pack(">qq", high, low)).decode()


def quest(high, low, name, desc, items=(), prereqs=()):
    return {
        "preRequisites:9": {"%d:10" % i: {"questIDHigh:4": h, "questIDLow:4": l} for i, (h, l) in enumerate(prereqs)},
        "properties:10": {"betterquesting:10": {"name:8": "§6§l" + name, "desc:8": desc,
                                                "icon:10": {"id:8": "testmod:widget", "Damage:2": 0}}},
        "questIDHigh:4": high, "questIDLow:4": low,
        "rewards:9": {"0:10": {"rewardID:8": "bq_standard:item", "rewards:9": {"0:10": {"id:8": "testmod:widget", "Damage:2": 0, "Count:3": 3}}}},
        "tasks:9": {"0:10": {"taskID:8": "bq_standard:retrieval", "requiredItems:9": {
            "%d:10" % i: {"id:8": reg, "Damage:2": d, "Count:3": c, "OreDict:8": ""} for i, (reg, d, c) in enumerate(items)}}},
    }


GUIDE_PAGE = """---
item_ids:
  - gregtech:gt.blockmachines:1000
quest_ids:
  - AAAAAAAAAAAAAAAAAAAATQ
navigation:
  title: Electric Blast Furnace
  parent: ./index.md
---
# Electric Blast Furnace
<GameScene interactive={true}>
  <ImportStructureLib controller="gregtech:gt.blockmachines:1000" />
</GameScene>

The <ItemLink id="gregtech:gt.blockmachines:1000" /> smelts aluminium with <ItemLink id="testmod:widget">widgets</ItemLink>.
""" + "Heat matters a lot for the furnace.\n" * 20 + """
## Coils

Coils set the heat. <RecipesFor id="testmod:widget" />
""" + "Upgrade coils for hotter recipes.\n" * 20


class Fixture:
    """A miniature pack, GregTech source tree, memory store and wiki mirror in a temporary directory."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.root = Path(self.tmp.name)
        pack = r / ".work" / "gtnh-2.9.0" / "pack"
        bq = pack / "config" / "betterquesting" / "DefaultQuests"
        self.write(bq / "QuestLinesOrder.txt", "%s: Tier 1 - LV\n" % qid(0, 3))
        self.write(bq / "QuestLines" / ("Tier1LV-" + qid(0, 3)) / "QuestLine.json", json.dumps(
            {"properties:10": {"betterquesting:10": {"name:8": "Tier 1 - LV"}}, "questLineIDHigh:4": 0, "questLineIDLow:4": 3}))
        for h, l in ((0, 77), (-5, 9)):
            self.write(bq / "QuestLines" / ("Tier1LV-" + qid(0, 3)) / ("Q-%s.json" % qid(h, l)), json.dumps({"questIDHigh:4": h, "questIDLow:4": l}))
        self.write(bq / "Quests" / ("Tier1LV-" + qid(0, 3)) / ("EBFTime-%s.json" % qid(0, 77)), json.dumps(quest(
            0, 77, "EBF-Time", "In order to get aluminium ingots, you need an Electric Blast Furnace. [warn]Power hungry![/warn]",
            items=[("gregtech:gt.blockmachines", 1000, 1), ("gregtech:gt.metaitem.01", 30013, 6), ("gregtech:gt.blockmachines", 91, 1),
                   ("mystery:thing", 4, 2)], prereqs=[(-5, 9)])))
        self.write(bq / "Quests" / ("Tier1LV-" + qid(0, 3)) / ("Coils-%s.json" % qid(-5, 9)), json.dumps(quest(
            -5, 9, "Cupronickel Coils", "Heating coils for the furnace.", items=[("testmod:widget", 0, 16)])))
        with zipfile.ZipFile(self.mkdir(pack / "mods") / "testmod-1.0.jar", "w") as z:
            z.writestr("assets/testmod/lang/en_US.lang", "item.widget.name=§eWidget\ntile.shinyOre.name=Shiny Ore\n"
                       + "".join("testmod.filler.%d=Filler line number %d with words\n" % (i, i) for i in range(400)))
            z.writestr("assets/testmod/lang/de_DE.lang", "item.widget.name=Ding\n")
            z.writestr("assets/gregtech/lang/en_US.lang", "gt.blockmachines.multimachine.blastfurnace.name=Electric Blast Furnace\n"
                       "gt.blockmachines.hatch.muffler.name=Muffler Hatch (%s)\n")
            z.writestr("assets/gregtech/lang/en_US/tooltip/cleanroom.md", "Machines inside have a chance to {color_warn:void outputs}\n")
            z.writestr("assets/testmod/guidenh/_en_us/widgets.md", "# Widgets\n\nWidgets are made in the widget press.\n")
        with zipfile.ZipFile(self.mkdir(pack / "config" / "guidenh") / "DefaultGuide.zip", "w") as z:
            z.writestr("assets/gregtech/guidenh/_en_us/multiblocks/electric_blast_furnace.md", GUIDE_PAGE)
            z.writestr("assets/gregtech/guidenh/_zh_cn/multiblocks/electric_blast_furnace.md", "# 电力高炉\n")
        gt = self.mkdir(r / "gtnh-src" / "mods" / "gregtech")
        self.write(gt / "MaterialsIDMap.java", "r( 13, Materials.Oxygen);\nr( 305, Materials.StainlessSteel);\n")
        self.write(gt / "MaterialsInit.java", 'return new MaterialBuilder().setName("StainlessSteel")\n  .setDefaultLocalName("Stainless Steel")\n')
        self.write(gt / "MetaTileEntityIDs.java", "enum X {\n    EBF_CONTROLLER(1000),\n    MUFFLER_HATCH_LV(91),\n}\n")
        self.write(gt / "LoaderMetaTileEntities.java",
                   'set(new MTEElectricBlastFurnace(EBF_CONTROLLER.ID, "multimachine.blastfurnace", "Electric Blast Furnace"));\n'
                   'set(new MTEHatchMuffler(MUFFLER_HATCH_LV.ID, "hatch.muffler.tier.01", "", 1));\n')
        mem = r / "data" / "memory"
        self.write(mem / "playbook" / "hv-nitrogen.md", "---\ntitle: Nitrogen at HV\nstatus: active\npack: 2.9.0\nasked-by: Alex\n---\n"
                   "Centrifuge liquid air from the vacuum freezer for nitrogen.\n")
        self.write(mem / "playbook" / "old.md", "---\nstatus: superseded\n---\n# Old answer\n\nstale\n")
        self.write(mem / "server" / "rules.md", "# Server rules\n\nNo lag machines in spawn chunks.\n")
        self.write(mem / "players" / "alex.md", "# Alex\n\nprivate notes about a player\n")
        self.ctx = s.Context(root=r, pack=pack, corpus=r / "data" / "corpus", index=r / "data" / "index",
                             memory=mem, gtsrc=[gt], readonly=False)
        store = mirror_wiki.Store(self.ctx.corpus / "wiki")
        store.put("Vacuum Freezer", 1, 100, "2026-01-01T00:00:00Z",
                  "{{Infobox\n|name=Vacuum Freezer\n|tier=HV\n}}\nThe '''Vacuum Freezer''' cools [[Hot Ingot|hot ingots]].\n"
                  "== Liquid air ==\nIt makes [[Liquid Air]] from air.[[Category:Multiblocks]]\n")
        store.save()
        return self

    def mkdir(self, p):
        p.mkdir(parents=True, exist_ok=True)
        return p

    def write(self, p, text):
        self.mkdir(p.parent)
        p.write_text(text, encoding="utf-8")

    def __exit__(self, *exc):
        self.tmp.cleanup()


class ChunkingTest(unittest.TestCase):
    def test_markdown_breadcrumbs_and_fences(self):
        text = "# Top\n\nintro\n\n## A\n\n```\n# not a heading\n```\n\n### A1\n\nx\n\n## B\n\ny\n"
        self.assertEqual([t for _, _, t in s.markdown_spans(text)], ["Top", "Top > A", "Top > A > A1", "Top > B"])

    def test_chunks_cover_lines_once_and_respect_size(self):
        doc = {"key": "guide:x/big.md", "title": "Big", "meta": {},
               "text": "# Big\n\n" + "\n".join("line %d with some words" % i for i in range(2000))}
        chunks = s.chunk_markdown("guide", doc)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c["text"]) <= s.MAX_CHARS for c in chunks))
        covered = [n for c in chunks for n in range(c["start"], c["end"] + 1)]
        self.assertEqual(len(covered), len(set(covered)))

    def test_small_sections_merge_and_titles_do_not_repeat(self):
        doc = {"key": "guide:x/a.md", "title": "gregtech guide: A", "meta": {}, "text": "# A\n\none\n\n## B\n\ntwo\n"}
        chunks = s.chunk_markdown("guide", doc)
        self.assertEqual([c["title"] for c in chunks], ["gregtech guide: A"])

    def test_frontmatter(self):
        meta, body = s.frontmatter(GUIDE_PAGE)
        self.assertEqual(meta["item_ids"], ["gregtech:gt.blockmachines:1000"])
        self.assertEqual(meta["navigation"]["title"], "Electric Blast Furnace")
        self.assertTrue(body.startswith("# Electric"))
        meta, _ = s.frontmatter("---\ntags: [a, b]\nstatus: 'active'\n---\nx")
        self.assertEqual(meta, {"tags": ["a", "b"], "status": "active"})


class SourceTest(unittest.TestCase):
    def test_quests(self):
        with Fixture() as f:
            docs = {d["meta"]["quest_id"]: d for d in s.load_docs(f.ctx, "quest")}
            ebf = docs[qid(0, 77)]
            self.assertEqual(ebf["key"], "quest:" + qid(0, 77))
            self.assertEqual(ebf["title"], "Tier 1 - LV > EBF-Time")
            self.assertIn("Quest line: Tier 1 - LV", ebf["text"])
            self.assertIn("Power hungry!", ebf["text"])
            self.assertNotIn("[warn]", ebf["text"])
            self.assertIn("Retrieve: Electric Blast Furnace; 6 × Oxygen Cell; Muffler Hatch (LV); 2 × mystery:thing:4", ebf["text"])
            self.assertIn("Prerequisites: Cupronickel Coils", ebf["text"])
            self.assertIn("Rewards: 3 × Widget", ebf["text"])
            self.assertIn("gregtech:gt.blockmachines:1000", ebf["meta"]["item_ids"])
            self.assertIn("Unlocks: EBF-Time", docs[qid(-5, 9)]["text"])
            self.assertTrue((f.ctx.corpus / "quest" / "docs.jsonl").is_file())

    def test_quest_id_matches_file_suffix(self):
        self.assertEqual(s.bq_id({"questIDHigh:4": 0, "questIDLow:4": 852}), "AAAAAAAAAAAAAAAAAAADVA==")
        self.assertNotIn("+", qid(-5, 9) + qid(1 << 62, -1))

    def test_guide_pages(self):
        with Fixture() as f:
            docs = {d["key"]: d for d in s.load_docs(f.ctx, "guide")}
            self.assertEqual(sorted(docs), ["guide:gregtech/multiblocks/electric_blast_furnace.md", "guide:testmod/widgets.md"])
            ebf = docs["guide:gregtech/multiblocks/electric_blast_furnace.md"]
            self.assertEqual(ebf["title"], "gregtech guide: Electric Blast Furnace")
            self.assertIn("The Electric Blast Furnace smelts aluminium with widgets.", ebf["text"])
            self.assertIn("(recipes for Widget)", ebf["text"])
            self.assertNotIn("GameScene", ebf["text"])
            self.assertEqual(ebf["meta"]["quest_ids"], ["AAAAAAAAAAAAAAAAAAAATQ=="])
            titles = [c["title"] for c in s.chunk_markdown("guide", ebf)]
            self.assertEqual(titles, ["gregtech guide: Electric Blast Furnace", "gregtech guide: Electric Blast Furnace > Coils"])

    def test_lang(self):
        with Fixture() as f:
            docs = {d["key"]: d for d in s.load_docs(f.ctx, "lang")}
            self.assertIn("item.widget.name=Widget", docs["lang:testmod"]["text"])
            self.assertNotIn("Ding", json.dumps(list(docs.values())))
            self.assertEqual(docs["lang:gregtech/tooltip/cleanroom"]["text"], "Machines inside have a chance to void outputs")
            chunks = s.chunk_lang("lang", docs["lang:testmod"])
            self.assertGreater(len(chunks), 1)
            self.assertTrue(all(c["title"] == "testmod en_US.lang" and len(c["text"]) <= s.MAX_CHARS for c in chunks))

    def test_memory_and_playbook(self):
        with Fixture() as f:
            pb = s.load_docs(f.ctx, "playbook")
            self.assertEqual([d["key"] for d in pb], ["playbook:playbook/hv-nitrogen.md"])
            self.assertEqual(pb[0]["title"], "Nitrogen at HV")
            self.assertEqual(pb[0]["meta"]["asked-by"], "Alex")
            self.assertTrue(pb[0]["text"].startswith("# Nitrogen at HV"))
            mem = s.load_docs(f.ctx, "memory")
            self.assertEqual([d["key"] for d in mem], ["memory:server/rules.md"])
            everything = json.dumps(s.corpus_chunks(f.ctx))
            self.assertNotIn("private notes", everything)
            self.assertNotIn("stale", everything)

    def test_memory_tolerates_missing_dir(self):
        with Fixture() as f:
            f.ctx.memory = f.root / "nowhere"
            self.assertEqual(s.load_docs(f.ctx, "playbook"), [])

    def test_wiki(self):
        with Fixture() as f:
            docs = s.load_docs(f.ctx, "wiki")
            self.assertEqual(docs[0]["key"], "wiki:Vacuum Freezer")
            self.assertEqual(docs[0]["meta"]["categories"], ["Multiblocks"])
            chunks = s.chunk_markdown("wiki", docs[0])
            self.assertIn("cools hot ingots", chunks[0]["text"])

    def test_item_stub_is_empty(self):
        with Fixture() as f:
            self.assertEqual(s.load_docs(f.ctx, "item"), [])

    def test_docs_cache_and_readonly(self):
        with Fixture() as f:
            first = s.load_docs(f.ctx, "lang")
            calls = []
            orig = s.SOURCES["lang"].discover
            s.SOURCES["lang"].discover = lambda ctx: calls.append(1) or orig(ctx)
            try:
                self.assertEqual(s.load_docs(f.ctx, "lang"), first)
                self.assertEqual(calls, [])
                ro = s.Context(root=f.root, pack=f.root / "missing", corpus=f.ctx.corpus, readonly=True)
                self.assertEqual(s.load_docs(ro, "lang"), first)
                self.assertEqual(calls, [])
            finally:
                s.SOURCES["lang"].discover = orig

    def test_env_overrides(self):
        keys = ("GTNH_SEARCH_DATA", "GTNH_SEARCH_INDEX_DIR", "GTNH_SEARCH_READONLY", "GTNH_SEARCH_ROOT")
        old = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update({"GTNH_SEARCH_DATA": "/srv/corpus", "GTNH_SEARCH_INDEX_DIR": "/srv/index",
                               "GTNH_SEARCH_READONLY": "1", "GTNH_SEARCH_ROOT": "/srv/root"})
            ctx = s.Context(pack="/nonexistent")
            self.assertEqual((str(ctx.root), str(ctx.corpus), str(ctx.index)), ("/srv/root", "/srv/corpus", "/srv/index"))
            self.assertTrue(ctx.readonly)
            self.assertFalse(ctx.writable())
            self.assertEqual(s.index_path(ctx).parent, Path("/srv/index"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_load_key(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text("# c\nexport OPENROUTER_API_KEY='abc'\n")
            old = os.environ.pop("OPENROUTER_API_KEY", None)
            try:
                self.assertEqual(s.load_key(d), "abc")
                os.environ["OPENROUTER_API_KEY"] = "from-env"
                self.assertEqual(s.load_key(d), "from-env")
            finally:
                os.environ.pop("OPENROUTER_API_KEY", None)
                if old is not None:
                    os.environ["OPENROUTER_API_KEY"] = old


class WikiTest(unittest.TestCase):
    def test_wikitext_to_text(self):
        wt = ("{{Infobox machine\n|name=Vacuum Freezer\n|image=vf.png\n|tier=HV\n}}\n'''Bold''' and [[Target|label]] "
              "and [[Plain]].<ref>cite</ref> {{inline|x}}\n== Section ==\n* item\n** sub\n{| class=\"wikitable\"\n! A !! B\n|-\n"
              "| 1 || 2\n|}\n[[File:x.png|thumb|caption]] [https://example.com site] [[Category:Machines]]<!-- hidden -->")
        text, cats = mirror_wiki.wikitext_to_text(wt)
        self.assertIn("tier: HV", text)
        self.assertNotIn("image", text)
        self.assertIn("Bold and label and Plain.", text)
        self.assertIn("## Section", text)
        self.assertIn("- item\n  - sub", text)
        self.assertIn("A | B\n1 | 2", text)
        self.assertIn("site", text)
        for gone in ("cite", "inline", "x.png", "hidden", "[[", "{{"):
            self.assertNotIn(gone, text)
        self.assertEqual(cats, ["Machines"])

    def test_infobox_field_with_piped_link(self):
        wt = ("{{Infobox Multiblock\n|name=Purification Unit\n|tier=[[Extremely Ultimate Voltage (UEV)|UEV]]\n"
              "|machine=[[Electric Blast Furnace]]\n|size=17 x 17 x 17\n}}")
        text, _ = mirror_wiki.wikitext_to_text(wt)
        self.assertIn("tier: UEV\n", text)
        self.assertIn("machine: Electric Blast Furnace", text)
        self.assertIn("size: 17 x 17 x 17", text)
        self.assertNotIn("[[", text)

    def test_dump_import(self):
        xml = ('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/"><page><title>EBF</title><ns>0</ns><id>5</id>'
               '<revision><id>42</id><timestamp>2026-01-01T00:00:00Z</timestamp><text>== Heat ==\nCoils.</text></revision></page>'
               '<page><title>Talk:EBF</title><ns>1</ns><id>6</id><revision><id>43</id><text>chat</text></revision></page>'
               '<page><title>Old</title><ns>0</ns><id>7</id><redirect title="EBF"/><revision><id>44</id><text>#REDIRECT</text></revision></page></mediawiki>')
        with tempfile.TemporaryDirectory() as d:
            Path(d, "dump.xml").write_text(xml)
            store = mirror_wiki.Store(Path(d) / "wiki")
            mirror_wiki.import_dump(store, Path(d, "dump.xml"), (0,), lambda m: None)
            self.assertEqual(list(store.manifest["pages"]), ["EBF"])
            self.assertEqual(store.manifest["pages"]["EBF"]["revid"], 42)


class IndexTest(unittest.TestCase):
    def test_incremental_build_and_search(self):
        with Fixture() as f:
            path = s.index_path(f.ctx)
            fake = FakeEmbedder()
            first = s.build(f.ctx, fake, path)
            self.assertEqual(fake.embedded, first["meta"]["chunks"])
            self.assertEqual(set(first["meta"]["kinds"]), {"quest", "guide", "lang", "wiki", "playbook", "memory"})

            again = FakeEmbedder()
            s.build(f.ctx, again, path)
            self.assertEqual(again.embedded, 0)

            f.write(f.ctx.memory / "playbook" / "new.md", "# Steel early\n\nUse the bricked blast furnace.\n")
            third = FakeEmbedder()
            index = s.build(f.ctx, third, path)
            self.assertEqual(third.embedded, 1)

            hits = s.search(index, FakeEmbedder.vec("In order to get aluminium ingots, you need an Electric Blast Furnace"), k=3)
            self.assertEqual(hits[0]["source"], "quest:" + qid(0, 77))
            self.assertTrue(all(h["kind"] == "guide" for h in s.search(index, FakeEmbedder.vec("coils"), kind="guide")))
            text = s.format_hits(hits)
            self.assertIn("quest_id: " + qid(0, 77), text)
            self.assertIn("item_ids: gregtech:gt.blockmachines:1000", text)

    def test_readonly_build_is_skipped_without_lock(self):
        with Fixture() as f:
            f.ctx.readonly = True
            path = s.index_path(f.ctx)
            self.assertIsNone(s.build(f.ctx, FakeEmbedder(), path))
            self.assertFalse(path.with_suffix(".lock").exists())

    def test_per_source_cap_and_lang_share(self):
        chunks = [{"source": "lang:a", "kind": "lang", "text": str(i)} for i in range(6)] + \
                 [{"source": "lang:b", "kind": "lang", "text": "b"}] + \
                 [{"source": "quest:%d" % i, "kind": "quest", "text": "q"} for i in range(6)]
        vectors = np.array([[1.0, 0.0]] * 7 + [[0.8, 0.6]] * 6, np.float32)
        index = {"chunks": chunks, "vectors": s.normalize(vectors)}
        hits = s.search(index, np.array([1.0, 0.0]), k=6)
        self.assertEqual(sum(h["kind"] == "lang" for h in hits), 2)
        self.assertEqual([h["score"] for h in hits], sorted((h["score"] for h in hits), reverse=True))
        only = s.search(index, np.array([1.0, 0.0]), k=6, kind="lang", per_source=2)
        self.assertEqual([h["source"] for h in only], ["lang:a", "lang:a", "lang:b"])


class ServerTest(unittest.TestCase):
    def test_protocol(self):
        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            svc = server.Service(f.ctx, FakeEmbedder(), path)
            svc.last_refresh = 1e12
            init = server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
            self.assertIn("never decides which recipes exist", init["result"]["instructions"])
            self.assertIsNone(server.handle(svc, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
            names = [t["name"] for t in server.handle(svc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
            self.assertEqual(names, ["gtnh_search", "gtnh_search_status", "gtnh_reindex"])
            res = server.handle(svc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "gtnh_search", "arguments": {"query": "Nitrogen at HV: centrifuge for nitrogen", "k": 2}}})["result"]
            self.assertFalse(res["isError"])
            self.assertTrue(res["content"][0]["text"].startswith("[1] playbook · Nitrogen at HV"))
            bad = server.handle(svc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "gtnh_search", "arguments": {"query": "x", "kind": "recipes"}}})["result"]
            self.assertTrue(bad["isError"])
            status = server.handle(svc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                         "params": {"name": "gtnh_search_status", "arguments": {}}})["result"]
            self.assertIn("Per kind:", status["content"][0]["text"])
            self.assertIn("error", server.handle(svc, {"jsonrpc": "2.0", "id": 6, "method": "bogus"}))

    def test_readonly_serves_without_refresh(self):
        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            f.ctx.readonly = True
            svc = server.Service(f.ctx, FakeEmbedder(), path)
            self.assertFalse(svc.can_refresh())
            text, err = svc.call("gtnh_search", {"query": "vacuum freezer liquid air"})
            self.assertFalse(err)
            self.assertFalse(svc.refreshing)
            self.assertIn("Read-only mode", svc.status())
            self.assertTrue(svc.call("gtnh_reindex", {})[1])

    def test_no_key_reports_cleanly(self):
        with Fixture() as f:
            svc = server.Service(f.ctx, None, f.root / "missing.npz")
            text, is_error = svc.call("gtnh_search", {"query": "x"})
            self.assertTrue(is_error)
            self.assertIn("OPENROUTER_API_KEY", text)


class EvalTest(unittest.TestCase):
    def test_questions_file_is_well_formed(self):
        qs = ev.load_questions()
        self.assertGreaterEqual(len(qs), 30)
        self.assertEqual(len({q["id"] for q in qs}), len(qs))
        self.assertTrue(all(q["question"] and q["expect"] for q in qs))

    def test_score_and_check(self):
        with Fixture() as f:
            index = s.build(f.ctx, FakeEmbedder(), s.index_path(f.ctx))
            qs = [{"id": "a", "question": "In order to get aluminium ingots, you need an Electric Blast Furnace",
                   "expect": ["quest:" + qid(0, 77)]},
                  {"id": "b", "question": "zzz unrelated", "expect": ["wiki:Nowhere"]}]
            self.assertEqual(ev.check(index["chunks"], qs), [("b", "wiki:Nowhere")])
            metrics, rows = ev.score(index, FakeEmbedder.vec, qs)
            self.assertEqual(rows[0]["rank"], 1)
            self.assertIsNone(rows[1]["rank"])
            self.assertEqual(metrics["recall@1"], 0.5)
            self.assertEqual(metrics["mrr"], 0.5)
            sub = ev.subset(index["chunks"], qs, 2)
            self.assertIn("quest:" + qid(0, 77), {c["source"] for c in sub})


def dump_xml(pages):
    """A MediaWiki export; pages is [(title, [(revid, text), ...])], oldest revision first as in a full-history dump."""
    out = ['<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">']
    for i, (title, revs) in enumerate(pages, 1):
        out.append("<page><title>%s</title><ns>0</ns><id>%d</id>" % (title, i))
        for revid, text in revs:
            out.append("<revision><id>%d</id><timestamp>2026-10-01T00:00:00Z</timestamp><contributor><id>9</id></contributor>"
                       "<text>%s</text></revision>" % (revid, text))
        out.append("</page>")
    return ("".join(out) + "</mediawiki>").encode()


class FakeHttp:
    """Stands in for archive.org: the search API, the metadata API and the file download."""

    def __init__(self, items, payload, md5=None):
        self.items, self.payload, self.downloads = items, payload, []
        self.md5 = md5 or hashlib.md5(payload).hexdigest()

    def get_json(self, url):
        if "advancedsearch" in url:
            return {"response": {"docs": [{"identifier": i, "publicdate": "2026-10-04T00:00:00Z"} for i in self.items]}}
        if "/metadata/" in url:
            item = url.split("/metadata/")[1].split("/")[0]
            date = uw.item_date(item)
            return {"result": [{"name": "gtnhwiki-%s-images.tar.gz" % date, "md5": "x"},
                               {"name": "gtnhwiki-%s.xml.gz" % date, "md5": self.md5, "size": str(len(self.payload))}]}
        raise AssertionError(url)

    def download(self, url, dest, max_bytes=uw.MAX_BYTES):
        self.downloads.append(url)
        Path(dest).write_bytes(self.payload)
        return hashlib.md5(self.payload).hexdigest()


class FailingEmbedder(FakeEmbedder):
    def documents(self, texts):
        raise RuntimeError("embedding service down")


NEW_DUMP = gzip.compress(dump_xml([
    ("Vacuum Freezer", [(100, "old text"), (200, "The Vacuum Freezer cools hot ingots and makes liquid air.")]),
    ("Cleanroom", [(201, "== Purpose ==\nA cleanroom keeps circuit recipes clean.")]),
]))
OLD_ITEM, NEW_ITEM = "miraheze-wiki-gtnhwiki-20260904", "miraheze-wiki-gtnhwiki-20261004"


class DumpTest(unittest.TestCase):
    """The weekly job itself (update_wiki.py) is tested with the living wiki in tools/living-wiki/test_living_wiki.py."""

    def test_discovery_picks_newest_dump(self):
        http = FakeHttp(["miraheze-wiki-gtnhwiki-20260801", NEW_ITEM, "miraheze-wiki-gtnhwiki-images-20261104", OLD_ITEM], b"")
        self.assertEqual(uw.newest_item(http), NEW_ITEM)
        self.assertEqual(uw.dump_file(http, NEW_ITEM)["name"], "gtnhwiki-20261004.xml.gz")
        self.assertIsNone(uw.newest_item(FakeHttp([], b"")))

    def test_gz_full_history_import(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "w.xml.gz").write_bytes(NEW_DUMP)
            store = mirror_wiki.Store(Path(d) / "wiki")
            self.assertEqual(mirror_wiki.import_dump(store, Path(d, "w.xml.gz"), (0,), lambda m: None), 2)
            self.assertEqual(store.manifest["pages"]["Vacuum Freezer"]["revid"], 200)

    def test_interrupted_swap_is_readable_and_recovers(self):
        with Fixture() as f:
            wiki = f.ctx.wiki_dir
            old = s.staged(wiki, "old")
            os.rename(wiki, old)
            self.assertEqual([d["key"] for d in s.load_docs(f.ctx, "wiki")], ["wiki:Vacuum Freezer"])
            s.recover_dir(wiki)
            self.assertTrue((wiki / "manifest.json").is_file())
            self.assertFalse(old.exists())

    def test_wiki_chunks_carry_dave_metadata(self):
        doc = {"key": "wiki:P", "title": "P", "text": "# P\n\n" + "official line\n" * 300 + "## Local\n\nDave line\n" + "more\n" * 300,
               "meta": {"title": "P", "edited_by_dave": "2026-10-31", "dave_lines": [[305, 305]], "dave_reason": "fix"}}
        chunks = s.chunk_wiki("wiki", doc)
        marked = [c for c in chunks if c["meta"].get("edited_by_dave")]
        self.assertTrue(marked and len(marked) < len(chunks))
        self.assertIn("Dave line", marked[0]["text"])
        hit = dict(marked[0], score=0.9)
        self.assertIn("locally edited 2026-10-31", s.format_hits([hit]).split("\n")[0])


class SeedTest(unittest.TestCase):
    def test_seed_copies_once_and_again_after_image_change(self):
        with Fixture() as f:
            s.build(f.ctx, FakeEmbedder(), s.index_path(f.ctx))
            state = f.root / "volume"
            ctx = s.Context(root=f.root, pack=f.root / "nopack", corpus=f.ctx.corpus, index=f.ctx.index,
                            memory=f.ctx.memory, gtsrc=[], readonly=False, state=state)
            self.assertEqual(ctx.corpus, state / "corpus")
            self.assertTrue(s.seed(ctx))
            self.assertTrue((state / "corpus" / "quest" / "docs.jsonl").is_file())
            self.assertTrue(s.index_path(ctx).is_file())
            self.assertFalse(list((state / "index").glob("*.lock")))
            self.assertFalse(s.seed(ctx))
            # The volume serves without the pack: quests come from the copied cache.
            self.assertTrue(s.load_docs(ctx, "quest"))
            # Writes go to the volume only.
            f.write(f.ctx.memory / "playbook" / "new.md", "# New\n\nfresh answer\n")
            seed_bytes = s.index_path(f.ctx).read_bytes()
            fake = FakeEmbedder()
            s.build(ctx, fake, s.index_path(ctx))
            self.assertEqual(fake.embedded, 1)
            self.assertEqual(s.index_path(f.ctx).read_bytes(), seed_bytes)
            # A new image (different seed files) re-seeds.
            (f.ctx.corpus / "lang" / "docs.jsonl").write_text((f.ctx.corpus / "lang" / "docs.jsonl").read_text() + "\n")
            self.assertTrue(s.seed(ctx))

    def test_seed_without_state_does_nothing(self):
        with Fixture() as f:
            self.assertIsNone(s.seed(f.ctx))

    def test_key_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "key").write_text("sk-from-file\n")
            old = {k: os.environ.pop(k, None) for k in ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FILE")}
            try:
                os.environ["OPENROUTER_API_KEY_FILE"] = str(Path(d, "key"))
                self.assertEqual(s.load_key(d), "sk-from-file")
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v


class ReloadTest(unittest.TestCase):
    def test_server_reloads_when_index_file_changes(self):
        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            svc = server.Service(f.ctx, FakeEmbedder(), path)
            svc.last_refresh = 1e12
            before = svc.index["meta"]["chunks"]
            self.assertFalse(svc.maybe_reload())
            f.write(f.ctx.memory / "playbook" / "new.md", "# New answer\n\nfresh\n")
            s.build(f.ctx, FakeEmbedder(), path)
            st = path.stat()
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
            text, _ = svc.call("gtnh_search_status", {})
            self.assertIn("%d chunks" % (before + 1), text)
            self.assertFalse(svc.maybe_reload())


def wait_until(cond, timeout=10):
    deadline = time.time() + timeout
    while not cond():
        if time.time() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


def rewrite_jar(jar, name, text):
    """Replaces one entry of a test jar and moves its mtime forward, as a pack update would."""
    with zipfile.ZipFile(jar) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    entries[name] = text.encode("utf-8")
    with zipfile.ZipFile(jar, "w") as z:
        for n, data in entries.items():
            z.writestr(n, data)
    bump(jar)


def bump(p):
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10 ** 9))


class ImageWithoutPackTest(unittest.TestCase):
    """Review #1: a corpus without its pack (the baked image, the volume) is served from its caches, never re-extracted
    from fallbacks or derived files."""

    def test_volume_keeps_guides_and_lang_extras(self):
        with Fixture() as f:
            f.write(f.ctx.corpus / "lang" / "extra" / "GregTech.lang", "S:gt.extra.thing=Extra Thing\n")
            dev = s.build(f.ctx, FakeEmbedder(), s.index_path(f.ctx))
            counts = {k: len(s.load_docs(f.ctx, k)) for k in ("quest", "guide", "lang")}
            self.assertIn("lang:GregTech.lang", [d["key"] for d in s.load_docs(f.ctx, "lang")])
            # A baked gtnh-src with a guide zip but no mod jars must not replace the pack's extraction either.
            f.write(f.root / "gtnh-src" / "config" / "guidenh" / "placeholder", "")
            shutil.copy(f.ctx.pack / "config" / "guidenh" / "DefaultGuide.zip", f.root / "gtnh-src" / "config" / "guidenh")
            for root, gtsrc, vol in ((f.root / "image", [], "vol1"), (f.root, None, "vol2")):
                ctx = s.Context(root=root, pack=f.root / "nopack", corpus=f.ctx.corpus, index=f.ctx.index,
                                memory=f.ctx.memory, gtsrc=gtsrc, readonly=False, state=f.root / vol)
                self.assertTrue(s.seed(ctx))
                index = s.build(ctx, FakeEmbedder(), s.index_path(ctx))
                self.assertEqual({k: len(s.load_docs(ctx, k)) for k in counts}, counts)
                self.assertIn("lang:GregTech.lang", [d["key"] for d in s.load_docs(ctx, "lang")])
                self.assertEqual(index["meta"]["kinds"], dev["meta"]["kinds"])
                self.assertEqual(index["meta"]["embedded"], 0)

    def test_empty_extraction_never_replaces_a_cache(self):
        with Fixture() as f:
            first = s.load_docs(f.ctx, "guide")
            cache = f.ctx.corpus / "guide" / "docs.jsonl"
            before = cache.read_bytes()
            orig = s.SOURCES["guide"].discover
            s.SOURCES["guide"].discover = lambda ctx: iter(())
            try:
                self.assertEqual(s.load_docs(f.ctx, "guide", force=True), first)
            finally:
                s.SOURCES["guide"].discover = orig
            self.assertTrue(first)
            self.assertEqual(cache.read_bytes(), before)


class NameFreshnessTest(unittest.TestCase):
    def test_gregtech_source_change_renames_items(self):
        """Review #5: a regenerated gtnh-src invalidates gregtech.json and the quests that used its names."""
        with Fixture() as f:
            quest_text = lambda ctx: next(d["text"] for d in s.load_docs(ctx, "quest") if d["text"].startswith("Quest: EBF-Time"))
            s.corpus_chunks(f.ctx)
            self.assertIn("Oxygen Cell", quest_text(f.ctx))
            idmap = f.ctx.gtsrc[0] / "MaterialsIDMap.java"
            idmap.write_text("r( 13, Materials.Nitrogen);\nr( 305, Materials.StainlessSteel);\n")
            bump(idmap)
            fresh = s.Context(root=f.root, pack=f.ctx.pack, corpus=f.ctx.corpus, index=f.ctx.index,
                              memory=f.ctx.memory, gtsrc=f.ctx.gtsrc, readonly=False)
            s.corpus_chunks(fresh)
            self.assertIn("Nitrogen Cell", quest_text(fresh))

    def test_long_lived_context_uses_current_names(self):
        """Review #6: one Context (the server's) re-renders quests with the new lang after a pack change."""
        with Fixture() as f:
            chunks = s.corpus_chunks(f.ctx)
            coils = lambda cs: next(c["text"] for c in cs if "Cupronickel" in c["text"] and c["kind"] == "quest")
            self.assertIn("Widget", coils(chunks))
            jar = f.ctx.pack / "mods" / "testmod-1.0.jar"
            with zipfile.ZipFile(jar) as z:
                lang = z.read("assets/testmod/lang/en_US.lang").decode()
            rewrite_jar(jar, "assets/testmod/lang/en_US.lang", lang.replace("§eWidget", "Gizmo"))
            self.assertIn("Gizmo", coils(s.corpus_chunks(f.ctx)))


class EmbedClientTest(unittest.TestCase):
    """Reviews #2, #3, #7: the OpenRouter client, with its opener replaced (no network)."""

    @staticmethod
    def client(responses):
        api = s.OpenRouter("sk-test", "fake/model")
        api.calls = []

        def fake_open(req, timeout):
            api.calls.append(timeout)
            r = responses.pop(0)
            if isinstance(r, BaseException):
                raise r
            return io.BytesIO(json.dumps(r).encode())
        api.open, api.sleep = fake_open, lambda sec: None
        return api

    def test_query_is_short_and_documents_patient(self):
        api = self.client([urllib.error.URLError("down")] * 10)
        with self.assertRaises(urllib.error.URLError):
            api.query("x")
        self.assertEqual(api.calls, [s.QUERY_TIMEOUT] * s.QUERY_ATTEMPTS)
        self.assertLessEqual(s.QUERY_ATTEMPTS * s.QUERY_TIMEOUT, 60)
        api = self.client([urllib.error.URLError("down")] * 10)
        with self.assertRaises(urllib.error.URLError):
            api.documents(["a"])
        self.assertEqual(api.calls, [s.DOC_TIMEOUT] * s.DOC_ATTEMPTS)

    def test_connection_drops_are_retried(self):
        ok = {"data": [{"index": 0, "embedding": [1.0, 0.0]}], "usage": {"cost": 0.001}}
        for err in (ConnectionResetError("reset"), http.client.RemoteDisconnected("closed"),
                    http.client.IncompleteRead(b"x")):
            api = self.client([err, ok])
            self.assertEqual(api.documents(["a"]), [[1.0, 0.0]])
            self.assertEqual(len(api.calls), 2)

    def test_redirects_are_refused(self):
        api = s.OpenRouter("sk-test")
        self.assertIs(api.open.__self__, s.OPENER)
        handlers = [h for h in s.OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertTrue(handlers and all(isinstance(h, s.NoRedirect) for h in handlers))
        req = urllib.request.Request(s.API_URL, data=b"{}", headers={"Authorization": "Bearer sk-test"})
        headers = Message()
        headers["Location"] = "https://elsewhere.example/steal"
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(handlers[0].http_error_302(req, io.BytesIO(), code, "Moved", headers))


class FailAfter(FakeEmbedder):
    def __init__(self, ok_calls):
        super().__init__()
        self.ok_calls = ok_calls

    def documents(self, texts):
        if self.calls >= self.ok_calls:
            raise RuntimeError("embedding service down")
        return super().documents(texts)


class DurabilityTest(unittest.TestCase):
    def test_failed_build_keeps_paid_vectors(self):
        """Review #3: vectors embedded before a failure are checkpointed and reused by the next build."""
        with Fixture() as f:
            path = s.index_path(f.ctx)
            old = s.CHECKPOINT_CHUNKS
            s.CHECKPOINT_CHUNKS = 2
            try:
                with self.assertRaises(RuntimeError):
                    s.build(f.ctx, FailAfter(2), path)
                self.assertFalse(path.exists())
                self.assertTrue(s.partial_path(path).is_file())
                unique = len({c["id"] for c in s.corpus_chunks(f.ctx)})
                fake = FakeEmbedder()
                index = s.build(f.ctx, fake, path)
            finally:
                s.CHECKPOINT_CHUNKS = old
            self.assertEqual(fake.embedded, unique - 4)
            self.assertFalse(s.partial_path(path).exists())
            clean = s.build(f.ctx, FakeEmbedder(), s.index_path(f.ctx, model="fake/clean"))
            self.assertTrue(np.allclose(index["vectors"], clean["vectors"]))

    def test_damaged_index_is_served_as_missing_and_rebuilt(self):
        """Review #4: a truncated index neither kills the server nor blocks every later build."""
        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            path.write_bytes(path.read_bytes()[:100])
            svc = server.Service(f.ctx, FakeEmbedder(), path)
            self.assertIsNone(svc.index)
            self.assertIn("unreadable", svc.status())
            self.assertTrue(svc.refresh())
            self.assertIsNone(svc.last_error)
            self.assertTrue(svc.index["meta"]["chunks"])
            self.assertTrue(path.with_name(path.name + ".corrupt").is_file())
            self.assertEqual(s.load_index(path)["meta"]["chunks"], svc.index["meta"]["chunks"])

    def test_atomic_writes_leave_no_temp_files(self):
        """Reviews #4, #10: concurrent writers never share a temporary file; a failed write keeps the old file."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "docs.jsonl"
            errors = []

            def writer(n):
                try:
                    for i in range(30):
                        s.write_jsonl(path, {"writer": n, "i": i}, [{"x": "y" * 2000}] * 20)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
            threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(errors, [])
            header, rows = s.read_jsonl(path)
            self.assertEqual(len(rows), 20)
            with self.assertRaises(ValueError):
                with s.atomic_file(path) as fh:
                    fh.write("half")
                    raise ValueError("crash mid-write")
            self.assertEqual(s.read_jsonl(path)[0], header)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["docs.jsonl"])


class ServerConcurrencyTest(unittest.TestCase):
    """Review #2: a slow search or reindex never blocks other calls; review #9: bad messages never end the server."""

    class Out:
        def __init__(self):
            self.lines, self.cond = [], threading.Condition()

        def write(self, text):
            with self.cond:
                self.lines.append(json.loads(text))
                self.cond.notify_all()

        def flush(self):
            pass

        def wait_ids(self, ids, timeout=10):
            with self.cond:
                return self.cond.wait_for(lambda: set(ids) <= {m.get("id") for m in self.lines}, timeout)

    def test_slow_search_does_not_block_status_or_ping(self):
        class Blocking(FakeEmbedder):
            def __init__(self):
                super().__init__()
                self.entered, self.release = threading.Event(), threading.Event()

            def query(self, text):
                self.entered.set()
                self.release.wait(10)
                return self.vec(text)

        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            emb = Blocking()
            svc = server.Service(f.ctx, emb, path)
            svc.last_refresh = 1e12
            out = self.Out()

            def lines():
                yield json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "gtnh_search", "arguments": {"query": "liquid air"}}})
                self.assertTrue(emb.entered.wait(10))
                yield json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "gtnh_search_status", "arguments": {}}})
                yield json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"})
                self.assertTrue(out.wait_ids({2, 3}))
                emb.release.set()
            server.serve(svc, lines(), out)
            ids = [m["id"] for m in out.lines]
            self.assertEqual(ids[-1], 1)
            self.assertFalse(out.lines[-1]["result"]["isError"])

    def test_reindex_returns_while_the_refresh_runs(self):
        class SlowDocs(FakeEmbedder):
            def __init__(self):
                super().__init__()
                self.release = threading.Event()

            def documents(self, texts):
                self.release.wait(10)
                return super().documents(texts)

        with Fixture() as f:
            path = s.index_path(f.ctx)
            s.build(f.ctx, FakeEmbedder(), path)
            f.write(f.ctx.memory / "playbook" / "new.md", "# New answer\n\nfresh\n")
            emb = SlowDocs()
            svc = server.Service(f.ctx, emb, path)
            svc.last_refresh = 1e12
            old = server.REINDEX_WAIT
            server.REINDEX_WAIT = 0.2
            try:
                text, err = svc.call("gtnh_reindex", {})
            finally:
                server.REINDEX_WAIT = old
            self.assertFalse(err)
            self.assertIn("still running", text)
            self.assertFalse(svc.call("gtnh_search", {"query": "nitrogen"})[1])
            emb.release.set()
            wait_until(lambda: not svc.refreshing)
            self.assertIn("New answer", svc.call("gtnh_search", {"query": "New answer fresh", "kind": "playbook"})[0])

    def test_malformed_messages_get_errors_not_a_crash(self):
        with Fixture() as f:
            svc = server.Service(f.ctx, FakeEmbedder(), f.root / "missing.npz")
            out = self.Out()
            lines = ["[1, 2]", '"text"', "not json", json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": [1]}),
                     json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": "x"}),
                     json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})]
            server.serve(svc, iter(lines), out)
            by_id = {m["id"]: m for m in out.lines}
            self.assertEqual([m["error"]["code"] for m in out.lines if m["id"] is None], [-32600, -32600])
            self.assertTrue(by_id[7]["result"]["isError"])
            self.assertIn("tools", by_id[8]["result"])
            self.assertEqual(by_id[9]["result"], {})


class WeeklyJobSafetyTest(unittest.TestCase):
    def test_check_and_readonly_write_nothing(self):
        """Review #8: --check and read-only mode neither seed the volume nor create the living wiki or a lock."""
        with Fixture() as f:
            state = f.root / "volume"
            for readonly, check in ((False, True), (True, False), (True, True)):
                ctx = s.Context(root=f.root, pack=f.root / "nopack", corpus=f.ctx.corpus, index=f.ctx.index,
                                memory=f.ctx.memory, gtsrc=[], readonly=readonly, state=state)
                code, summary = uw.run(ctx, FakeHttp([NEW_ITEM], NEW_DUMP), lambda: FakeEmbedder(), lambda: None, check=check)
                if check:
                    self.assertEqual(code, 0, summary)
                    self.assertTrue(summary.startswith("update available"), summary)
                else:
                    self.assertEqual(code, 1)
                    self.assertIn("read-only", summary)
                self.assertFalse(state.exists())
                self.assertFalse(f.ctx.index.joinpath("jobs.lock").exists())


class StagingTest(unittest.TestCase):
    def test_staged_dirs_are_unique_and_swept(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "wiki"
            a, b = s.staged(target, "new"), s.staged(target, "new")
            self.assertNotEqual(a, b)
            self.assertTrue(a.is_dir() and b.is_dir() and not list(a.iterdir()))
            self.assertTrue(a.name.startswith(".wiki.new."))
            self.assertEqual(s.staged(target, "old"), Path(d) / ".wiki.old")
            self.assertFalse((Path(d) / ".wiki.old").exists())
            old = s.staged(target, "import")
            os.utime(old, (time.time() - 10 * 3600,) * 2)
            s.sweep_staged(target)
            self.assertFalse(old.exists())
            self.assertTrue(a.is_dir() and b.is_dir())

    def test_seed_skips_staging_dirs_and_temp_files(self):
        with Fixture() as f:
            s.build(f.ctx, FakeEmbedder(), s.index_path(f.ctx))
            junk = s.staged(f.ctx.wiki_dir, "new")
            (junk / "manifest.json").write_text("{}")
            f.write(f.ctx.corpus / ".docs.jsonl.x1.tmp", "partial")
            ctx = s.Context(root=f.root, pack=f.root / "nopack", corpus=f.ctx.corpus, index=f.ctx.index,
                            memory=f.ctx.memory, gtsrc=[], readonly=False, state=f.root / "volume")
            self.assertTrue(s.seed(ctx))
            self.assertEqual([p.name for p in ctx.corpus.iterdir() if p.name.startswith(".")], [])


class WikiFilesTest(unittest.TestCase):
    def test_file_names_fit_and_ascii_names_are_unchanged(self):
        """Review #11: names are cut by bytes, so a long non-ASCII title can't abort an import."""
        long_cjk = "电力高炉" * 60
        name = mirror_wiki.safe_name(long_cjk) + ".wiki"
        self.assertLessEqual(len(name.encode("utf-8")), 255)
        with tempfile.TemporaryDirectory() as d:
            store = mirror_wiki.Store(Path(d) / "wiki")
            store.put(long_cjk, 1, 2, "t", "text")
            self.assertTrue((Path(d) / "wiki" / "text" / (mirror_wiki.safe_name(long_cjk) + ".txt")).is_file())
        title = "Vacuum Freezer/Tips & Tricks " * 5
        legacy = __import__("re").sub(r"[^\w.-]+", "_", title)[:100] + "-" + hashlib.sha1(title.encode()).hexdigest()[:8]
        self.assertEqual(mirror_wiki.safe_name(title), legacy)

    def test_mirror_refuses_over_a_living_wiki(self):
        with Fixture() as f:
            self.assertIsNone(mirror_wiki.living_wiki_refusal(f.ctx))
            (f.ctx.living_wiki() / ".git").mkdir(parents=True)
            self.assertIn("update_wiki.py", mirror_wiki.living_wiki_refusal(f.ctx))


class MemoryReaderTest(unittest.TestCase):
    def test_hidden_and_vanishing_files_are_skipped(self):
        with Fixture() as f:
            pb = f.ctx.memory / "playbook"
            f.write(pb / ".draft.md", "# Draft\n\nhalf written\n")
            f.write(pb / ".tmp" / "x.md", "# Temp\n\nmid-rename\n")
            f.write(pb / "gone.md", "# Gone\n\nremoved by the store\n")
            orig = Path.read_text

            def read_text(self, *a, **k):
                if self.name == "gone.md":
                    raise FileNotFoundError(self)
                return orig(self, *a, **k)
            with mock.patch.object(Path, "read_text", read_text):
                keys = [d["key"] for d in s.load_docs(f.ctx, "playbook")]
            self.assertEqual(keys, ["playbook:playbook/hv-nitrogen.md"])


class FailureStageTest(unittest.TestCase):
    """The weekly job's failure summary says whether the living wiki already moved (coordinator follow-up)."""

    class FakeWiki:
        def __init__(self, move):
            self.move, self.refs = move, {"official": "a1", "living": "b1"}
            self.git = self

        def rev(self, name):
            return self.refs[name]

        def exists(self):
            return True

        def official_item(self):
            return OLD_ITEM, "20260904"

        def official_manifest(self):
            return {"pages": {"Vacuum Freezer": {}, "Cleanroom": {}}}

        def upgrade(self, *a, **k):
            if self.move:
                self.refs = {"official": "a2", "living": "b2"}
            raise OSError("disk full")

    def run_job(self, move):
        with Fixture() as f, mock.patch.object(uw.lw_mod, "ensure", lambda ctx, log=None: (self.FakeWiki(move), False)):
            return uw.run(f.ctx, FakeHttp([NEW_ITEM], NEW_DUMP), lambda: FakeEmbedder(), lambda: None)

    def test_summary_reports_the_stage(self):
        code, summary = self.run_job(move=False)
        self.assertEqual(code, 1)
        self.assertIn("corpus, living wiki and index unchanged", summary)
        code, summary = self.run_job(move=True)
        self.assertEqual(code, 1)
        self.assertNotIn("unchanged", summary)
        self.assertIn("living wiki now holds " + NEW_ITEM, summary)
        self.assertIn("disk full", summary)


if __name__ == "__main__":
    unittest.main()
