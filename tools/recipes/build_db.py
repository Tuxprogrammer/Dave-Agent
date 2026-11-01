"""Normalizes a gtnh-calc-oracle export into Dave's recipe database (SQLite). Standard library only.

    python3 -I tools/recipes/build_db.py <oracle-export.json> [db] [--run-info run-info.json]

db defaults to $DAVE_RECIPES_DB, else <repo>/data/recipes.sqlite. The database is written to a temporary file next
to it and swapped in atomically, so a running MCP server keeps reading the old one until the new one is complete.

The rules are ported from jackwrichards/gtnh-factory-flow `normalize-oracle-export.mjs` (MIT), not rediscovered:
  - recipe ids are content hashes (map, sorted slots with stack amount / not-consumed / chance, ticks, EU/t, special
    value), never the exporter's id, which hashes a JVM identity and changes on every export;
  - a zero-sized input stack (the programmed circuit, molds, lenses) and mSpecialItems are present but not consumed;
  - the programmed circuit is `gregtech:gt.integrated_circuit@N` (N != 32767), and only that item counts;
  - an input chance (out of 10000) is a consume chance: the slot must be filled, a run uses it up that often;
  - ore dictionary membership belongs to the item; what a recipe SLOT accepts (mOreDictAlt, mAltFluidInputs, GT
    unification) belongs to the recipe and is stored with that slot as a ratio to the slot's own amount;
  - an oredict input is one node, `ore:<first name>`, with every name it was registered under;
  - zero-tick GT recipes are clamped to 1 tick; disabled recipes and recipes without outputs are dropped;
  - item ids are lowercased (`canonicalResourceId`); meta 0 is omitted, 32767 is a wildcard.
Added here (Dave): cleanroom / low gravity / coil heat come from the recipe METADATA first (5.09.54 only derives
mSpecialValue from it when no special value was set, so one EBF recipe carries coil heat in mSpecialValue and its
cleanroom flag only in metadata), with the old special-value codes (-100/-200/-300) as the fallback.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipedb  # noqa: E402

SCHEMA_VERSION = 1
CIRCUIT = "gregtech:gt.integrated_circuit"
WILDCARD = 32767
MAP_NAMES = {"gtpp.recipe.cokeoven": "Industrial Coke Oven"}
# Maps whose GTRecipe.mFakeRecipe entries still describe something a player can run: the assembly line's real
# recipes live in its "fake" display map, and the rock breaker / tree growth simulator list their real outputs.
REAL_FAKE_MAPS = {"gt.recipe.fakeAssemblylineProcess", "gt.recipe.rockbreaker", "gt.recipe.multiblockrockbreaker",
                  "gt.recipe.treefarm"}
OC_PROFILES = {"gt.recipe.blastfurnace": "ebf-heat", "gt.recipe.pyro": "pyrolyse-coil",
               "gt.recipe.craker": "oil-cracker-coil", "gt.recipe.cracker": "oil-cracker-coil",
               "gt.recipe.largechemicalreactor": "perfect-oc"}
THAUM_MAPS = {"infusion": "Thaumcraft Infusion", "crucible": "Thaumcraft Crucible",
              "arcane": "Thaumcraft Arcane Crafting", "essentiaSmelting": "Thaumcraft Essentia Smelting",
              "thaumcraft": "Thaumcraft"}

# Default raw-resource cost classes. Explicit entries win; every other item no recipe makes is classified by rule
# in classify_raw(). The planner reads these as import costs (free 0, cheap 1, costly 10, never = not importable).
RAW_SEED = {
    "fluid:water": ("free", "infinite water source / pump"),
    "fluid:air": ("free", "gas collector / compressor from the atmosphere"),
    "minecraft:cobblestone": ("free", "cobblestone generator / rock breaker"),
    "minecraft:stone": ("free", "rock breaker"),
    "fluid:lava": ("cheap", "nether lava / pump"),
    "minecraft:sand": ("cheap", "world"),
    "minecraft:gravel": ("cheap", "world"),
    "minecraft:dirt": ("cheap", "world"),
    "minecraft:netherrack": ("cheap", "world"),
    "minecraft:end_stone": ("cheap", "world"),
    "minecraft:obsidian": ("cheap", "world / water on lava"),
    "minecraft:clay_ball": ("cheap", "world"),
    "minecraft:snowball": ("cheap", "world"),
    "minecraft:log": ("cheap", "trees"),
    "minecraft:log2": ("cheap", "trees"),
    "minecraft:log@32767": ("cheap", "trees"),
    "minecraft:log2@32767": ("cheap", "trees"),
    "minecraft:sapling": ("cheap", "trees"),
    "minecraft:reeds": ("cheap", "farm"),
    "minecraft:wheat": ("cheap", "farm"),
    "minecraft:wheat_seeds": ("cheap", "farm"),
}


# Display names that are not the item's name. GT's OreDictRegistrationHandler renames the stacks it registers under
# a malformed ore dictionary tag to this (the NOR wafer is registered as "wafer"), and the oracle reads those stacks.
BAD_NAMES = {"Invalid OreDictionary Tag"}


def log(msg):
    print("[build_db] " + msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- ids and resources

def canonical_item_id(raw_id):
    """`canonicalResourceId`: lowercase namespace and name, keep the @meta suffix."""
    base, sep, meta = str(raw_id).rpartition("@")
    if not sep:
        base, meta = str(raw_id), None
    out = base.lower()
    return out + ("@" + meta if meta is not None else "")


def node_id(res):
    """Database item id for an oracle resource dict, or None."""
    kind = res.get("kind")
    if kind == "item":
        rid = str(res.get("id") or "").strip()
        return canonical_item_id(rid) if rid else None
    if kind == "fluid":
        rid = str(res.get("id") or "").strip()
        return "fluid:" + rid if rid else None
    if kind == "aspect":
        tag = res.get("tag") or str(res.get("id") or "").rsplit(":", 1)[-1]
        return "aspect:" + tag if tag else None
    if kind == "oreDictionary":
        names = [n for n in (res.get("names") or []) if n]
        return "ore:" + names[0] if names else None
    if kind == "choice":
        return res.get("id") or None
    return None


def amount_of(res, default=1):
    try:
        a = float(res.get("amount", default))
    except (TypeError, ValueError):
        return default
    return a if a > 0 else default


class Catalog:
    """Every item, fluid, aspect, oredict slot and choice node seen, with its best name."""

    def __init__(self):
        self.items = {}

    def add(self, res, nid=None):
        nid = nid or node_id(res)
        if not nid:
            return None
        e = self.items.get(nid)
        kind = {"item": "item", "fluid": "fluid", "aspect": "essentia", "oreDictionary": "oredict",
                "choice": "choice"}.get(res.get("kind"), "item")
        if kind == "item" and nid.endswith("@%d" % WILDCARD):
            kind = "wildcard"
        if e is None:
            e = self.items[nid] = {"id": nid, "kind": kind, "name": None, "mod": None, "registry": None,
                                   "meta": None, "tooltip": None, "members": None, "oredict": set()}
        name = res.get("displayName")
        if kind == "oredict":
            names = [n for n in (res.get("names") or []) if n]
            e["name"] = e["name"] or "Ore Dictionary: " + ", ".join(names)
            e["members"] = e["members"] or {"names": names}
        elif kind == "choice":
            e["name"] = e["name"] or (name if name and name != "Item Choice" else None)
            if not e["members"]:
                alts = [node_id(a) for a in res.get("alternatives") or []]
                e["members"] = {"items": [a for a in alts if a]}
                for a in res.get("alternatives") or []:
                    self.add(a)
                if not e["name"]:
                    e["name"] = "Any of: " + ", ".join(
                        (a.get("displayName") or node_id(a) or "?") for a in (res.get("alternatives") or [])[:4])
        elif name and name not in BAD_NAMES and (not e["name"] or e["name"] == nid):
            e["name"] = str(name)
        if res.get("modId") and not e["mod"]:
            e["mod"] = res["modId"]
        if res.get("registryId") and not e["registry"]:
            e["registry"] = res["registryId"]
        if res.get("meta") is not None and e["meta"] is None:
            e["meta"] = res["meta"]
        if res.get("tooltip") and not e["tooltip"]:
            tt = res["tooltip"]
            e["tooltip"] = "\n".join(tt) if isinstance(tt, list) else str(tt)
        return nid


# ---------------------------------------------------------------- recipes

def voltage_tier(eut):
    return recipedb.voltage_tier(eut)


def slot_key(row):
    """carry-recipe-ids / stableRecipeId slot key: kind|id|stack amount|nc|chance."""
    return "|".join([row["item"], fmt_num(row["stack"]), "" if row["consumed"] else "nc",
                     fmt_num(row["chance"]) if row["chance"] < 1 else ""])


def fmt_num(x):
    return ("%d" % x) if float(x).is_integer() else ("%.6g" % x)


def content_hash(map_id, ins, outs, ticks, eut, special):
    key = json.dumps({"map": map_id, "in": sorted(slot_key(r) for r in ins),
                      "out": sorted(slot_key(r) for r in outs), "ticks": ticks, "eut": eut, "special": special},
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


class Builder:
    def __init__(self):
        self.cat = Catalog()
        self.recipes = {}          # hash -> recipe dict
        self.maps = {}             # map id -> {name, source, count, oc_profile}
        self.machines = []
        self.stats = Counter()
        self.dupes = 0

    # ---- rows
    def io_row(self, res, side, slot, consumed=True, chance=None, stack=None):
        nid = self.cat.add(res)
        if not nid:
            self.stats["dropped-slot:" + str(res.get("kind"))] += 1
            return None
        amt = amount_of(res) if stack is None else stack
        if chance is None:
            c = res.get("chance")
            chance = float(c) if isinstance(c, (int, float)) and 0 <= c < 1 else 1.0
        row = {"item": nid, "side": side, "slot": slot, "stack": amt, "chance": chance,
               "consumed": bool(consumed and res.get("consumed") is not False), "alts": None}
        alts = res.get("alternatives") if res.get("kind") in ("item", "fluid") else None
        if alts and amt > 0:
            out = []
            for a in alts:
                aid = self.cat.add(a)
                if aid and aid != nid and all(aid != x[0] for x in out):
                    out.append([aid, round(amount_of(a) / amt, 6)])
            row["alts"] = out or None
        return row

    def add_recipe(self, map_id, ins, outs, ticks, eut, special_value=0, *, source, extra=None, fake=False,
                   hidden=False, heat=None, cleanroom=False, lowgrav=False, tier=None, incomplete=False):
        ins = [r for r in ins if r]
        outs = [r for r in outs if r]
        if not outs:
            self.stats["no-outputs:" + source] += 1
            return None
        h = content_hash(map_id, ins, outs, ticks, eut, special_value)
        if h in self.recipes:
            self.dupes += 1
            return None
        circuit = None
        for r in ins:
            base, _, meta = r["item"].rpartition("@")
            if base == CIRCUIT and meta.isdigit() and int(meta) != WILDCARD:
                circuit = int(meta)
        m = self.maps[map_id]
        special = dict(extra or {})
        if special_value:
            special["specialValue"] = special_value
        if incomplete:
            special["incomplete"] = True
        self.recipes[h] = {
            "hash": h, "map": map_id, "machine": m["name"], "source": source,
            # a GregTech recipe's tier is the voltage its EU/t needs; 0-EU recipes (fuels, primitive and special
            # multiblocks that bill power elsewhere) have none
            "tier": tier if tier is not None else (voltage_tier(eut) if source == "gregtech" and eut > 0 else None),
            "eut": int(eut), "ticks": int(ticks), "amps": 1, "circuit": circuit,
            "cleanroom": int(bool(cleanroom)), "lowgrav": int(bool(lowgrav)), "heat": heat,
            "fake": int(bool(fake)), "hidden": int(bool(hidden)),
            "recycle": int(bool((extra or {}).get("metadata", {}).get("recycle"))),
            "special": json.dumps(special, sort_keys=True) if special else None,
            "io": aggregate(ins, "in") + aggregate(outs, "out"),
        }
        m["count"] += 1
        return h

    def map(self, map_id, name, source, profile=None):
        if map_id not in self.maps:
            self.maps[map_id] = {"name": name, "source": source, "count": 0, "oc_profile": profile}
        return self.maps[map_id]

    # ---- domains
    def gregtech(self, dom):
        for m in dom.get("recipeMaps") or []:
            mid = m.get("id")
            name = MAP_NAMES.get(mid) or (m.get("name") if m.get("name") and m.get("name") != mid else mid)
            self.map(mid, name, "gregtech", OC_PROFILES.get(mid, "standard"))
            for c in m.get("catalysts") or []:
                res = c.get("resource") or {}
                iid = self.cat.add(res)
                cls = c.get("sourceClass") or ""
                multi = bool(c.get("multiblock"))
                self.machines.append({
                    "map": mid, "item_id": iid, "name": res.get("displayName"), "class": cls,
                    "family": res.get("displayName") if multi else cls.rsplit(".", 1)[-1] + ":" + mid,
                    "multiblock": int(multi), "tier": c.get("tier"), "priority": c.get("priority") or 0})
            for r in m.get("recipes") or []:
                if r.get("enabled") is False:
                    continue
                ticks = max(1, int(r.get("durationTicks") or 1))
                eut = int(r.get("eut") or 0)
                sv = int(r.get("specialValue") or 0)
                md = r.get("metadata") or {}
                ins = []
                for i, x in enumerate(r.get("itemInputs") or []):
                    ch = x.get("inputChance")
                    ins.append(self.io_row(x, "in", i, chance=(ch / 10000.0) if ch else 1.0))
                base = len(ins)
                for i, x in enumerate(r.get("nonConsumedInputs") or []):
                    ins.append(self.io_row(x, "in", base + i, consumed=False))
                base = len(ins)
                for i, x in enumerate(r.get("fluidInputs") or []):
                    ins.append(self.io_row(x, "in", base + i))
                outs = [self.io_row(x, "out", i) for i, x in enumerate(r.get("itemOutputs") or [])]
                base = len(outs)
                outs += [self.io_row(x, "out", base + i) for i, x in enumerate(r.get("fluidOutputs") or [])]
                heat = md.get("coil_heat")
                if heat is None and OC_PROFILES.get(mid) == "ebf-heat" and sv > 0:
                    heat = sv
                cleanroom = bool(md.get("cleanroom")) or sv in (-200, -300)
                lowgrav = bool(md.get("low_gravity")) or sv in (-100, -300)
                extra = {}
                if md:
                    extra["metadata"] = md
                if r.get("fusionStartupEu"):
                    extra["fusionStartupEu"] = r["fusionStartupEu"]
                if r.get("spargeOutputs") or r.get("spargeByproducts"):
                    extra["sparge"] = "rolled byproducts not modelled"
                fake = bool(r.get("fake"))
                self.add_recipe(mid, ins, outs, ticks, eut, sv, source="gregtech", extra=extra, fake=fake,
                                hidden=bool(r.get("hidden")), heat=int(heat) if heat else None,
                                cleanroom=cleanroom, lowgrav=lowgrav)

    def crafting(self, dom):
        for r in dom.get("recipes") or []:
            out = r.get("output")
            if not out:
                self.stats["no-outputs:crafting"] += 1
                continue
            shapeless = r.get("type") == "shapeless" or "shapeless" in str(r.get("className", "")).lower()
            mid = "crafting.shapeless" if shapeless else "crafting.shaped"
            self.map(mid, "Shapeless Crafting" if shapeless else "Shaped Crafting", "crafting")
            # a crafting tool (an oredict craftingTool* slot or a GregTech tool) loses durability, it is not used up
            ins = [self.io_row(x, "in", x.get("slotIndex", i), consumed=not is_tool(x))
                   for i, x in enumerate(r.get("inputs") or []) if x.get("kind") != "text"]
            extra = {"class": r.get("className")} if r.get("className") and not r.get("className", "").startswith(
                ("net.minecraft.item.crafting.", "net.minecraftforge.oredict.")) else None
            # a recipe class the exporter cannot read (special IRecipe implementations) comes with no inputs
            self.add_recipe(mid, ins, [self.io_row(out, "out", 0)], 1, 0, source="crafting", extra=extra,
                            incomplete=not any(ins))

    def smelting(self, dom):
        self.map("furnace", "Furnace", "smelting")
        for r in dom.get("recipes") or []:
            if not r.get("input") or not r.get("output"):
                continue
            self.add_recipe("furnace", [self.io_row(r["input"], "in", 0)], [self.io_row(r["output"], "out", 0)],
                            200, 0, source="smelting")

    def thaumcraft(self, dom):
        for r in dom.get("recipes") or []:
            t = r.get("type") or "thaumcraft"
            mid = "thaumcraft." + t
            self.map(mid, THAUM_MAPS.get(t, "Thaumcraft"), "thaumcraft")
            ins, slot = [], 0
            for key in ("centralInput", "catalyst", "input"):
                if r.get(key):
                    ins.append(self.io_row(r[key], "in", slot)); slot += 1
            for x in r.get("components") or []:
                ins.append(self.io_row(x, "in", slot)); slot += 1
            if t != "essentiaSmelting":
                for x in r.get("aspects") or []:
                    ins.append(self.io_row(x, "in", slot)); slot += 1
            outs = []
            if r.get("output"):
                outs.append(self.io_row(r["output"], "out", 0))
            if t == "essentiaSmelting":
                outs += [self.io_row(x, "out", i + 1) for i, x in enumerate(r.get("outputs") or r.get("aspects") or [])]
            # On a dedicated server the oracle cannot read an arcane recipe's crafting grid (it comes from NEI on a
            # client), so those recipes carry only their output and vis: kept for lookups, never planned.
            incomplete = t == "arcane" and not r.get("centralInput") and not r.get("components")
            extra = {k: r[k] for k in ("research", "instability") if r.get(k) is not None}
            self.add_recipe(mid, ins, outs, max(1, int(r.get("durationTicks") or 1)), 0, source="thaumcraft",
                            extra=extra, incomplete=incomplete)

    def ore_dictionary(self, entries):
        for name, stacks in (entries or {}).items():
            for st in stacks or []:
                iid = self.cat.add(st)
                if iid:
                    self.cat.items[iid]["oredict"].add(name)


def is_tool(res):
    if res.get("kind") == "oreDictionary":
        return any(str(n).startswith("craftingTool") for n in res.get("names") or [])
    return str(res.get("id") or "").startswith("gregtech:gt.metatool.")


def aggregate(rows, side):
    """One row per (item, consumed, chance) on a side: a crafting grid's six stone become one stack of 6."""
    out, index = [], {}
    for r in rows:
        key = (r["item"], r["consumed"], r["chance"])
        if key in index:
            agg = index[key]
            agg["stack"] += r["stack"]
            if r["alts"] and not agg["alts"]:
                agg["alts"] = r["alts"]
            continue
        agg = dict(r)
        index[key] = agg
        out.append(agg)
    for r in out:
        r["side"] = side
    return out


def classify_raw(item, produced):
    """Default cost class of an item no (plannable) recipe makes."""
    iid, names = item["id"], item["oredict"]
    if item["kind"] in ("oredict", "choice", "wildcard"):
        return None
    if any(n.startswith(("ore", "denseore", "rawOre")) for n in names):
        return "cheap", "ore (mined)"
    if any(n.startswith(("log", "treeLeaves", "treeSapling", "crop", "seed")) for n in names):
        return "cheap", "farm / trees"
    if "creative" in iid or "creative" in (item["name"] or "").lower():
        return "never", "creative-only"
    if iid.startswith("aspect:"):
        return "costly", "essentia (no recipe makes it; from smelting or a jar)"
    return "costly", "no recipe makes it (world, mob or loot)"


# ---------------------------------------------------------------- write

SCHEMA = """
CREATE TABLE pack_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE items(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, mod TEXT, oredict TEXT, tooltip TEXT,
                   registry TEXT, meta INTEGER, members TEXT, producers INTEGER NOT NULL DEFAULT 0,
                   uses INTEGER NOT NULL DEFAULT 0);
CREATE TABLE recipes(id INTEGER PRIMARY KEY, hash TEXT NOT NULL UNIQUE, map TEXT NOT NULL, machine TEXT,
                     source TEXT, tier INTEGER, eut INTEGER, ticks INTEGER, amps INTEGER, circuit INTEGER,
                     cleanroom INTEGER, lowgrav INTEGER, heat INTEGER, fake INTEGER, hidden INTEGER, recycle INTEGER,
                     special TEXT);
CREATE TABLE recipe_io(recipe_id INTEGER NOT NULL, side TEXT NOT NULL, slot INTEGER, item_id TEXT NOT NULL,
                       amount REAL NOT NULL, chance REAL NOT NULL, consumed INTEGER NOT NULL, oredict_alts TEXT);
CREATE TABLE maps(id TEXT PRIMARY KEY, name TEXT, source TEXT, recipe_count INTEGER, oc_profile TEXT);
CREATE TABLE machines(map TEXT, item_id TEXT, name TEXT, class TEXT, family TEXT, multiblock INTEGER,
                      tier INTEGER, priority INTEGER);
CREATE TABLE raw_resources(item_id TEXT PRIMARY KEY, class TEXT NOT NULL
                           CHECK (class IN ('free', 'cheap', 'costly', 'never')), note TEXT);
CREATE VIRTUAL TABLE items_fts USING fts5(name, oredict, id UNINDEXED, tokenize = 'unicode61 remove_diacritics 2');
"""
INDEXES = """
CREATE INDEX io_item ON recipe_io(item_id, side);
CREATE INDEX io_recipe ON recipe_io(recipe_id);
CREATE INDEX recipes_map ON recipes(map);
CREATE INDEX items_name ON items(name COLLATE NOCASE);
CREATE INDEX machines_map ON machines(map);
"""


def build(export, db_path, run_info=None):
    t0 = time.time()
    b = Builder()
    doms = {d.get("id"): d for d in export.get("domains") or []}
    if "gregtech" in doms:
        b.gregtech(doms["gregtech"])
    if "crafting" in doms:
        b.crafting(doms["crafting"])
    if "smelting" in doms:
        b.smelting(doms["smelting"])
    if "thaumcraft" in doms:
        b.thaumcraft(doms["thaumcraft"])
    if "oreDictionary" in doms:   # last: recipe stacks name an item better than ore dictionary stacks do
        b.ore_dictionary(doms["oreDictionary"].get("entries"))
    if not b.recipes:
        raise SystemExit("normalization produced zero recipes")
    not_normalized = [d for d in doms if d not in ("oreDictionary", "gregtech", "crafting", "smelting", "thaumcraft")]
    doms.clear()
    export["domains"] = None    # the raw recipes are no longer needed: free them before writing

    # wildcard and oredict nodes: record their members so the planner can expand them
    by_registry = defaultdict(list)
    for iid, e in b.cat.items.items():
        if e["kind"] == "item":
            by_registry[iid.rpartition("@")[0] if "@" in iid else iid].append(iid)
    ore_members = defaultdict(set)
    for iid, e in b.cat.items.items():
        for n in e["oredict"]:
            ore_members[n].add(iid)
    for iid, e in b.cat.items.items():
        if e["kind"] == "wildcard":
            base = iid.rpartition("@")[0]
            e["members"] = {"items": sorted(set(by_registry.get(base, [])) | ({base} if base in b.cat.items else set()))}
        elif e["kind"] == "oredict":
            names = (e["members"] or {}).get("names") or [iid[4:]]
            e["members"] = {"names": names, "items": sorted(set().union(*(ore_members.get(n, set()) for n in names)))}

    tmp = Path(str(db_path) + ".tmp")
    if tmp.exists():
        tmp.unlink()
    tmp.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
    producers, uses = Counter(), Counter()
    rows_r, rows_io = [], []
    for rid, (h, r) in enumerate(sorted(b.recipes.items()), start=1):
        rows_r.append((rid, h, r["map"], r["machine"], r["source"], r["tier"], r["eut"], r["ticks"], r["amps"],
                       r["circuit"], r["cleanroom"], r["lowgrav"], r["heat"], r["fake"], r["hidden"], r["recycle"],
                       r["special"]))
        plannable = not r["fake"] or r["map"] in REAL_FAKE_MAPS
        for io in r["io"]:
            rows_io.append((rid, io["side"], io["slot"], io["item"], io["stack"], io["chance"], int(io["consumed"]),
                            json.dumps(io["alts"]) if io["alts"] else None))
            if io["side"] == "out" and plannable:
                producers[io["item"]] += 1
            elif io["side"] == "in":
                uses[io["item"]] += 1
    con.executemany("INSERT INTO recipes VALUES (%s)" % ",".join("?" * 17), rows_r)
    con.executemany("INSERT INTO recipe_io VALUES (?,?,?,?,?,?,?,?)", rows_io)
    rows_i = []
    for iid, e in b.cat.items.items():
        rows_i.append((iid, e["kind"], e["name"] or iid, e["mod"], json.dumps(sorted(e["oredict"])) if e["oredict"] else None,
                       e["tooltip"], e["registry"], e["meta"], json.dumps(e["members"]) if e["members"] else None,
                       producers[iid], uses[iid]))
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows_i)
    con.executemany("INSERT INTO items_fts(name, oredict, id) VALUES (?,?,?)",
                    [(r[2], " ".join(json.loads(r[4])) if r[4] else "", r[0]) for r in rows_i])
    con.executemany("INSERT INTO maps VALUES (?,?,?,?,?)",
                    [(k, v["name"], v["source"], v["count"], v["oc_profile"]) for k, v in sorted(b.maps.items())])
    con.executemany("INSERT INTO machines VALUES (?,?,?,?,?,?,?,?)",
                    [(m["map"], m["item_id"], m["name"], m["class"], m["family"], m["multiblock"], m["tier"],
                      m["priority"]) for m in b.machines])
    raw = {}
    for iid, e in b.cat.items.items():
        if iid in RAW_SEED:
            raw[iid] = RAW_SEED[iid]
        elif producers[iid] == 0:
            c = classify_raw(e, producers)
            if c:
                raw[iid] = c
    con.executemany("INSERT INTO raw_resources VALUES (?,?,?)", [(k, v[0], v[1]) for k, v in sorted(raw.items())])

    adapters = export.get("adapters") or []
    meta = {
        "schema_version": SCHEMA_VERSION,
        "pack_version": (run_info or {}).get("pack_version") or os.environ.get("DAVE_PACK_VERSION") or "unknown",
        "tuxmine_server_version": (run_info or {}).get("tuxmine_server_version"),
        "exported_at": export.get("generatedAt"),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "exporter": export.get("exporter"), "format": export.get("format"),
        "mods": export.get("loadedMods") or [],
        "adapters": [{k: a.get(k) for k in ("id", "status", "recipeCount", "warnings") if a.get(k) is not None}
                     for a in adapters],
        "run_info": run_info,
        "counts": {"recipes": len(rows_r), "io_rows": len(rows_io), "items": len(rows_i), "maps": len(b.maps),
                   "machines": len(b.machines), "raw_resources": len(raw), "duplicates_dropped": b.dupes},
        "dropped": dict(b.stats),
        "not_normalized": not_normalized,
    }
    con.executemany("INSERT INTO pack_meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.executescript(INDEXES)
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, db_path)
    log("wrote %s: %d recipes, %d io rows, %d items, %d maps in %.1fs" % (
        db_path, len(rows_r), len(rows_io), len(rows_i), len(b.maps), time.time() - t0))
    return meta


DROP_KEYS = ("runtimeCalculation", "neiLayout", "icon", "iconPath", "dominantColor")


def slim(obj):
    """json object_hook: drops what the database never uses (overclock variants, NEI layouts, icons) while parsing,
    which roughly halves the memory a 300+ MB export needs."""
    for k in DROP_KEYS:
        if k in obj:
            del obj[k]
    return obj


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export")
    ap.add_argument("db", nargs="?", default=None)
    ap.add_argument("--run-info")
    a = ap.parse_args(argv)
    db = Path(a.db) if a.db else recipedb.default_db_path()
    with open(a.export, encoding="utf-8") as f:
        export = json.load(f, object_hook=slim)
    run_info = None
    if a.run_info and Path(a.run_info).is_file():
        run_info = json.loads(Path(a.run_info).read_text(encoding="utf-8"))
    meta = build(export, db, run_info)
    print(json.dumps(meta["counts"]))


if __name__ == "__main__":
    main()
