"""Offline tests for tools/recipes: the normalizer, the queries, the MCP server and the chain planner.

    python3 -I tools/recipes/test_recipes.py            (planner tests are skipped without highspy)

The fixture testdata/oracle-sample.json is cut from a REAL export of our pack (testdata/make_sample.py), so every
expected number below is a recipe the game registered. Tests marked "full DB" also run against data/recipes.sqlite
(or $DAVE_RECIPES_DB) when it exists, and are skipped otherwise.
"""

import io
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_db  # noqa: E402
import recipedb as R  # noqa: E402
import server  # noqa: E402

try:
    import planner
    HAVE_HIGHS = planner.highspy is not None
except ImportError:  # pragma: no cover
    HAVE_HIGHS = False

SAMPLE = HERE / "testdata" / "oracle-sample.json"
FULL_DB = R.default_db_path()

STEEL = "gregtech:gt.metaitem.01@11305"
NAND = "gregtech:gt.metaitem.03@32075"
NOR_WAFER = "gregtech:gt.metaitem.03@32042"


def load_sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


class SampleDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.tmp.name) / "recipes.sqlite"
        build_db.log = lambda msg: None
        cls.meta = build_db.build(load_sample(), cls.db, {"pack_version": "2.9.0"})
        cls.con = R.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def recipe(self, h):
        r = R.recipe_by_ref(self.con, h)
        self.assertIsNotNone(r, h)
        return r, R.io_rows(self.con, r["id"])


class NormalizerTests(SampleDB):
    def test_counts_and_meta(self):
        m = R.meta(self.con)
        self.assertEqual(m["pack_version"], "2.9.0")
        self.assertGreater(m["counts"]["recipes"], 250)
        self.assertEqual(set(m), set(self.meta))

    def test_content_hash_ignores_export_order(self):
        """Recipe ids are content hashes: a shuffled export gives the same ids (the oracle's own ids would not)."""
        data = load_sample()
        for m in data["domains"][1]["recipeMaps"]:
            random.Random(7).shuffle(m["recipes"])
            for r in m["recipes"]:
                r["id"] = "different-every-export"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.sqlite"
            build_db.build(data, p)
            with closing(sqlite3.connect(self.db)) as ca, closing(sqlite3.connect(p)) as cb:
                a = {r[0] for r in ca.execute("SELECT hash FROM recipes")}
                b = {r[0] for r in cb.execute("SELECT hash FROM recipes")}
        self.assertEqual(a, b)

    def test_ebf_steel_heat_circuit_chance(self):
        """EBF: Cast Iron Dust + 1000 L Oxygen, circuit 11 -> Steel Ingot + 11.11% Ashes, 120 EU/t, 100 ticks, 1000 K."""
        rows = self.con.execute(
            "SELECT r.* FROM recipes r JOIN recipe_io a ON a.recipe_id = r.id AND a.side = 'in' "
            "AND a.item_id = 'gregtech:gt.metaitem.01@2304' JOIN recipe_io b ON b.recipe_id = r.id AND b.side = 'out' "
            "AND b.item_id = ? WHERE r.map = 'gt.recipe.blastfurnace'", (STEEL,)).fetchall()
        self.assertEqual(len(rows), 1)
        r = dict(rows[0])
        self.assertEqual((r["eut"], r["ticks"], r["heat"], r["circuit"], r["tier"]), (120, 100, 1000, 11, 2))
        io_ = {x["item_id"]: x for x in R.io_rows(self.con, r["id"])}
        self.assertEqual(io_["gregtech:gt.integrated_circuit@11"]["consumed"], 0)
        self.assertEqual(io_["fluid:oxygen"]["amount"], 1000)
        self.assertAlmostEqual(io_["gregtech:gt.metaitem.01@2815"]["chance"], 0.1111)

    def test_cleanroom_from_metadata(self):
        """NAND chip cutting needs a cleanroom; the flag comes from the recipe metadata."""
        r = self.con.execute("SELECT r.* FROM recipes r JOIN recipe_io o ON o.recipe_id = r.id AND o.side = 'out' "
                             "WHERE o.item_id = ? AND r.map = 'gt.recipe.cuttingsaw'", (NAND,)).fetchall()
        self.assertTrue(r)
        self.assertTrue(all(x["cleanroom"] for x in r))
        self.assertIn('"cleanroom": true', r[0]["special"])

    def test_metadata_wins_over_special_value(self):
        """In 5.09.54 an explicit special value hides the cleanroom flag; the metadata keeps it."""
        data = load_sample()
        ebf = next(m for m in data["domains"][1]["recipeMaps"] if m["id"] == "gt.recipe.blastfurnace")
        r = json.loads(json.dumps(ebf["recipes"][0]))
        r["specialValue"], r["metadata"] = 3200, {"coil_heat": 3200, "cleanroom": True}
        r["durationTicks"] += 1          # a distinct recipe
        ebf["recipes"] = [r]
        data["domains"] = [d for d in data["domains"] if d["id"] == "gregtech"]
        data["domains"][0]["recipeMaps"] = [ebf]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.sqlite"
            build_db.build(data, p)
            with closing(sqlite3.connect(p)) as c:
                row = c.execute("SELECT heat, cleanroom FROM recipes").fetchone()
        self.assertEqual(row, (3200, 1))

    def test_bad_display_names_are_skipped(self):
        """GT renames stacks registered under a malformed ore dictionary tag; the wafer keeps its real name."""
        self.assertEqual(R.item(self.con, NOR_WAFER)["name"], "NOR Memory Chip (Wafer)")
        self.assertIsNone(self.con.execute("SELECT 1 FROM items WHERE name = 'Invalid OreDictionary Tag'").fetchone())

    def test_crafting_slots_aggregate_and_oredict(self):
        row = self.con.execute("SELECT io.* FROM recipe_io io JOIN recipes r ON r.id = io.recipe_id "
                               "WHERE r.source = 'crafting' AND io.side = 'in' AND io.item_id LIKE 'ore:%'").fetchone()
        if row:
            ore = R.item(self.con, row["item_id"])
            self.assertEqual(ore["kind"], "oredict")
            self.assertIn("names", json.loads(ore["members"]))

    def test_arcane_without_inputs_is_flagged(self):
        r = self.con.execute("SELECT special FROM recipes WHERE map = 'thaumcraft.arcane'").fetchone()
        self.assertIn("incomplete", json.loads(r["special"]))

    def test_raw_resources(self):
        cls = dict(self.con.execute("SELECT item_id, class FROM raw_resources").fetchall())
        self.assertEqual(cls["fluid:air"], "free")
        self.assertNotIn("fluid:nitrogen", cls)


class QueryTests(SampleDB):
    def test_resolve(self):
        self.assertEqual(R.resolve(self.con, "Nitrogen")[0], "fluid:nitrogen")
        self.assertEqual(R.resolve(self.con, "nitrogen")[0], "fluid:nitrogen")
        self.assertEqual(R.resolve(self.con, "steel ingot")[0], STEEL)
        self.assertEqual(R.resolve(self.con, STEEL)[0], STEEL)
        iid, err = R.resolve(self.con, "steel")
        self.assertIsNone(iid)
        self.assertIn("ambiguous", err)

    def test_find_fts(self):
        hits = R.find(self.con, "nand chi")
        self.assertIn(NAND, [h["id"] for h in hits])

    def test_parse(self):
        self.assertEqual(R.parse_tier("hv"), 3)
        self.assertEqual(R.parse_heat("kanthal", 3), 2801)
        self.assertEqual(R.parse_heat("1800K"), 1800)
        self.assertRaises(ValueError, R.parse_tier, "HVV")
        self.assertEqual(R.voltage_tier(120), 2)
        self.assertEqual(R.voltage_tier(512), 3)

    def test_producer_filters(self):
        _, all_ = R.recipes_touching(self.con, NAND, "out")
        _, lv = R.recipes_touching(self.con, NAND, "out", tier=1)
        _, noclean = R.recipes_touching(self.con, NAND, "out", cleanroom=False)
        self.assertGreater(all_, 0)
        self.assertEqual(noclean, 0)
        self.assertLessEqual(lv, all_)
        _, cold = R.recipes_touching(self.con, STEEL, "out", heat=999, machine="gt.recipe.blastfurnace")
        self.assertEqual(cold, 0)


class ServerTests(SampleDB):
    def call(self, svc, name, args):
        r = server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": args}})
        return r["result"]["content"][0]["text"], r["result"]["isError"]

    def test_protocol(self):
        svc = server.Service(self.db)
        init = server.handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "recipes")
        tools = server.handle(svc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools},
                         {"recipe_producers", "recipe_uses", "recipe_get", "item_find", "plan_chain"})
        self.assertIsNone(server.handle(svc, {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_producers_uses_get_find(self):
        svc = server.Service(self.db)
        text, err = self.call(svc, "recipe_producers", {"item": "NOR Memory Chip", "tier": "HV"})
        self.assertFalse(err, text)
        self.assertIn("Cutting Machine", text)
        self.assertIn("cleanroom", text)
        self.assertIn("NOR Memory Chip (Wafer)", text)
        h = text.split("#", 1)[1][:16]
        text, err = self.call(svc, "recipe_get", {"id": h})
        self.assertFalse(err)
        self.assertIn("map: gt.recipe.cuttingsaw", text)
        text, err = self.call(svc, "recipe_uses", {"item": "fluid:air"})
        self.assertFalse(err)
        self.assertIn("Centrifuge", text)
        text, err = self.call(svc, "item_find", {"name": "liquid air"})
        self.assertIn("fluid:liquidair", text)
        text, err = self.call(svc, "recipe_producers", {"item": "no such thing at all"})
        self.assertTrue(err)
        text, err = self.call(svc, "recipe_producers", {"item": "Nitrogen", "tier": "XV"})
        self.assertTrue(err)

    def test_stdio_loop(self):
        svc = server.Service(self.db)
        stdin = io.StringIO("\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "recipe_producers", "arguments": {"item": "Steel Ingot", "limit": 2}}},
            "not json"]) + "\n")
        out = io.StringIO()
        server.serve(svc, stdin, out, workers=1)
        replies = {r["id"]: r for r in map(json.loads, out.getvalue().splitlines())}
        self.assertIn("Steel Ingot", replies[2]["result"]["content"][0]["text"])

    def test_missing_db(self):
        svc = server.Service(Path(self.tmp.name) / "missing.sqlite")
        text, err = self.call(svc, "item_find", {"name": "x"})
        self.assertTrue(err)
        self.assertIn("not found", text)

    def test_db_path_from_env(self):
        old = dict(os.environ)
        try:
            os.environ["DAVE_RECIPES_DB"] = "/dave/ro/recipes.sqlite"
            self.assertEqual(str(R.default_db_path()), "/dave/ro/recipes.sqlite")
            del os.environ["DAVE_RECIPES_DB"]
            os.environ["DAVE_ROOT"] = "/somewhere"
            self.assertEqual(str(R.default_db_path()), "/somewhere/data/recipes.sqlite")
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
