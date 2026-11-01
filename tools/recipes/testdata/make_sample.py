"""Cuts the offline test fixture (oracle-sample.json) out of a REAL oracle export, so the tests run on our pack's own
recipes without the 300+ MB file.

    python3 -I tools/recipes/testdata/make_sample.py <oracle-export.json> [out.json]

It keeps every GregTech recipe that touches one of KEEP (nitrogen and air, steel, the NAND and NOR chip lines), with
the catalysts of their maps, a few crafting, furnace and Thaumcraft recipes, and a few ore dictionary entries.
"""

import json
import sys
from pathlib import Path

KEEP = {
    "fluid": {"nitrogen", "air", "liquidair", "liquidnitrogen"},
    "item": {"gregtech:gt.metaitem.01@11305",   # Steel Ingot
             "gregtech:gt.metaitem.01@2305",    # Steel Dust
             "gregtech:gt.metaitem.03@32075",   # NAND Chip
             "gregtech:gt.metaitem.03@32042",   # NOR Memory Chip (Wafer)
             "gregtech:gt.metaitem.03@32043"},  # NOR Memory Chip
}
MAPS = {"gt.recipe.centrifuge", "gt.recipe.multicentrifuge", "gt.recipe.vacuumfreezer", "gt.recipe.distillationtower",
        "gt.recipe.electrolyzer", "gt.recipe.multielectro", "gt.recipe.blastfurnace", "gt.recipe.laserengraver",
        "gt.recipe.cuttingsaw", "gt.recipe.canner", "gt.recipe.primitiveblastfurnace", "gt.recipe.compressor"}
ORE = ("ingotSteel", "dustSteel", "wafer", "waferNOR")


def touches(r):
    for key in ("itemInputs", "itemOutputs", "fluidInputs", "fluidOutputs", "nonConsumedInputs"):
        for x in r.get(key) or []:
            if x.get("id") in KEEP.get(x.get("kind"), ()):
                return True
    return False


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("runtimeCalculation", "neiLayout", "icon", "tooltip")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def main():
    src = json.load(open(sys.argv[1], encoding="utf-8"))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("oracle-sample.json")
    doms = {d["id"]: d for d in src["domains"]}
    gt = []
    for m in doms["gregtech"]["recipeMaps"]:
        if m["id"] not in MAPS:
            continue
        rs = [r for r in m["recipes"] if touches(r)]
        if rs:
            gt.append(dict({k: v for k, v in m.items() if k != "recipes"}, recipes=rs))
    steel = "gregtech:gt.metaitem.01@11305"
    craft = [r for r in doms["crafting"]["recipes"] if (r.get("output") or {}).get("id") in KEEP["item"]][:6]
    smelt = [r for r in doms["smelting"]["recipes"] if (r.get("output") or {}).get("id") == steel][:4]
    thaum = [next(r for r in doms["thaumcraft"]["recipes"] if r.get("type") == t) for t in ("crucible", "arcane")]
    ore = {k: v for k, v in doms["oreDictionary"]["entries"].items() if k in ORE}
    sample = {k: src[k] for k in ("schemaVersion", "exporter", "format", "generatedAt", "minecraftVersion")}
    sample["loadedMods"] = [m for m in src["loadedMods"] if m in ("gregtech", "gregguns", "Thaumcraft", "IC2")]
    sample["adapters"] = src["adapters"]
    sample["domains"] = [{"id": "oreDictionary", "entries": ore}, {"id": "gregtech", "recipeMaps": gt},
                         {"id": "crafting", "recipes": craft}, {"id": "smelting", "recipes": smelt},
                         {"id": "thaumcraft", "recipes": thaum}]
    out.write_text(json.dumps(strip(sample), separators=(",", ":")) + "\n", encoding="utf-8")
    n = sum(len(m["recipes"]) for m in gt)
    print("wrote %s: %d GregTech recipes in %d maps, %d crafting, %d furnace, %d Thaumcraft (%d KB)" % (
        out, n, len(gt), len(craft), len(smelt), len(thaum), out.stat().st_size // 1024))


if __name__ == "__main__":
    main()
