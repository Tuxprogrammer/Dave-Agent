"""Read-only queries over Dave's recipe database (data/recipes.sqlite, built by build_db.py). Standard library only.

Item ids:
  items    `<mod>:<name>[@meta]`, lowercased, meta 0 omitted, @32767 = any meta   e.g. gregtech:gt.metaitem.01@11305
  fluids   `fluid:<fluid name>`                                                   e.g. fluid:nitrogen
  essentia `aspect:<tag>`; an ore dictionary slot `ore:<name>`; an item choice `choice:<hash>`
Recipe ids are 16-hex content hashes (map, slots, ticks, EU/t, special value): stable across exports of the same pack.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

VOLTAGE_NAMES = ["ULV", "LV", "MV", "HV", "EV", "IV", "LuV", "ZPM", "UV", "UHV", "UEV", "UIV", "UXV", "OpV", "MAX"]
VOLTAGES = [8, 32, 128, 512, 2048, 8192, 32768, 131072, 524288, 2097152, 8388608, 33554432, 134217728, 536870912]
COILS = {  # GregTech heating coils: base heat in kelvin (the EBF adds 100 K per voltage tier above MV)
    "cupronickel": 1801, "kanthal": 2701, "nichrome": 3601, "tpv": 4501, "tpv-alloy": 4501, "hss-g": 5401,
    "hssg": 5401, "hss-s": 6301, "hsss": 6301, "naquadah": 7201, "naquadah alloy": 8101, "naquadah-alloy": 8101,
    "trinium": 9001, "electrum flux": 9901, "electrum-flux": 9901, "awakened draconium": 10801,
    "awakened-draconium": 10801, "infinity": 11701, "hypogen": 12601, "eternal": 13501,
}
SCHEMA_TABLES = ("pack_meta", "items", "recipes", "recipe_io", "maps", "machines", "raw_resources", "items_fts")


def voltage_tier(eut):
    """GregTech voltage tier index (0 = ULV) a recipe of this EU/t needs: the lowest tier whose voltage covers it."""
    v = abs(int(eut or 0))
    for i, cap in enumerate(VOLTAGES):
        if v <= cap:
            return i
    return len(VOLTAGES)


def tier_name(t):
    return VOLTAGE_NAMES[t] if t is not None and 0 <= t < len(VOLTAGE_NAMES) else "?"


def parse_tier(value):
    """'HV', 'hv', 3, '3' -> 3. None stays None. Raises ValueError for anything else."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    for i, n in enumerate(VOLTAGE_NAMES):
        if n.lower() == s.lower():
            return i
    raise ValueError("unknown tier %r (use ULV, LV, MV, HV, EV, IV, LuV, ZPM, UV, UHV, ...)" % value)


def parse_heat(value, tier=None):
    """A coil name or kelvin -> the EBF heat available. A coil name gets the EBF's +100 K per tier above MV."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower().replace("_", "-")
    m = re.match(r"^(\d+)\s*k?$", s)
    if m:
        return int(m.group(1))
    s = s.removesuffix(" coils").removesuffix(" coil").removesuffix("-coils").removesuffix("-coil")
    if s in COILS:
        return COILS[s] + 100 * max(0, (tier if tier is not None else 2) - 2)
    raise ValueError("unknown coil %r (give kelvin or a coil name such as cupronickel, kanthal, nichrome)" % value)


def repo_root():
    return Path(__file__).resolve().parents[2]


def default_db_path():
    """$DAVE_RECIPES_DB, else $DAVE_ROOT/data/recipes.sqlite, else <repo>/data/recipes.sqlite."""
    env = os.environ.get("DAVE_RECIPES_DB")
    if env:
        return Path(os.path.expanduser(env))
    root = os.environ.get("DAVE_ROOT")
    return Path(os.path.expanduser(root) if root else repo_root()) / "data" / "recipes.sqlite"


def connect(path=None):
    path = Path(path or default_db_path())
    if not path.is_file():
        raise FileNotFoundError("recipe database not found at %s (build it with tools/recipe-export/run.sh)" % path)
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def meta(con):
    return {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM pack_meta")}


# ---------------------------------------------------------------- items

def item(con, iid):
    r = con.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone()
    return dict(r) if r else None


def item_name(con, iid, cache=None):
    if cache is not None and iid in cache:
        return cache[iid]
    r = con.execute("SELECT name FROM items WHERE id = ?", (iid,)).fetchone()
    name = r["name"] if r else iid
    if cache is not None:
        cache[iid] = name
    return name


def fts_query(text):
    words = re.findall(r"[\w]+", text.lower())
    return " ".join('"%s"*' % w for w in words) if words else None


def find(con, text, k=10, kind=None):
    """Items by name: exact (case-insensitive) matches first, then FTS5 prefix matches, ranked by how much the pack
    uses them. Returns dicts with id, kind, name, mod, producers, uses."""
    text = (text or "").strip()
    if not text:
        return []
    seen, out = set(), []

    def add(rows):
        for r in rows:
            if r["id"] in seen or (kind and r["kind"] != kind):
                continue
            seen.add(r["id"])
            out.append(dict(r))

    cols = "id, kind, name, mod, producers, uses, oredict"
    add(con.execute("SELECT %s FROM items WHERE id = ? OR id = ? OR id = ?" % cols,
                    (text, text.lower(), "fluid:" + text.lower())))
    add(con.execute("SELECT %s FROM items WHERE name = ? COLLATE NOCASE ORDER BY (kind IN ('item','fluid')) DESC, "
                    "producers + uses DESC LIMIT ?" % cols, (text, k)))
    q = fts_query(text)
    if q and len(out) < k:
        try:
            rows = con.execute(
                "SELECT %s FROM items WHERE id IN (SELECT id FROM items_fts WHERE items_fts MATCH ? "
                "ORDER BY rank LIMIT 200) ORDER BY (kind IN ('item','fluid')) DESC, length(name), "
                "producers + uses DESC LIMIT ?" % cols, (q, k * 3)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        add(rows)
    return out[:k]


def resolve(con, ref):
    """An item reference (id, fluid name or display name) -> (item id, None) or (None, error text with candidates)."""
    ref = (ref or "").strip()
    if not ref:
        return None, "no item given"
    for cand in (ref, ref.lower(), "fluid:" + ref.lower(), "fluid:" + ref.lower().replace(" ", "")):
        if con.execute("SELECT 1 FROM items WHERE id = ?", (cand,)).fetchone():
            return cand, None
    exact = con.execute("SELECT id, kind FROM items WHERE name = ? COLLATE NOCASE AND kind IN ('item','fluid') "
                        "ORDER BY producers DESC, uses DESC", (ref,)).fetchall()
    if len(exact) == 1:
        return exact[0]["id"], None
    if exact:
        # prefer the fluid over its cell, then the most-produced item; an item and a same-named fluid are told apart
        fluids = [r for r in exact if r["kind"] == "fluid"]
        if len(fluids) == 1:
            return fluids[0]["id"], None
        return exact[0]["id"], None
    hits = find(con, ref, 6)
    if not hits:
        return None, "no item or fluid matches %r" % ref
    return None, "%r is ambiguous; pass one of these ids: %s" % (
        ref, "; ".join("%s (%s)" % (h["id"], h["name"]) for h in hits))


# ---------------------------------------------------------------- recipes

def io_rows(con, rid):
    return [dict(r) for r in con.execute(
        "SELECT side, slot, item_id, amount, chance, consumed, oredict_alts FROM recipe_io WHERE recipe_id = ? "
        "ORDER BY side, slot", (rid,))]


def recipe_by_ref(con, ref):
    ref = str(ref).strip().lstrip("#")
    r = con.execute("SELECT * FROM recipes WHERE hash = ?", (ref,)).fetchone()
    if r is None and ref.isdigit():
        r = con.execute("SELECT * FROM recipes WHERE id = ?", (int(ref),)).fetchone()
    if r is None and len(ref) >= 6:
        rows = con.execute("SELECT * FROM recipes WHERE hash LIKE ? LIMIT 2", (ref + "%",)).fetchall()
        r = rows[0] if len(rows) == 1 else None
    return dict(r) if r else None


def fmt_amount(iid, amount):
    if iid.startswith("fluid:"):
        return "%s L" % fmt_num(amount)
    return "%sx" % fmt_num(amount)


def fmt_num(x):
    x = float(x)
    if x.is_integer():
        return "{:,}".format(int(x))
    return ("%.4g" % x) if abs(x) < 1000 else "{:,.1f}".format(x)


def fmt_io(con, row, names):
    s = "%s %s" % (fmt_amount(row["item_id"], row["amount"]), item_name(con, row["item_id"], names))
    tags = []
    if not row["consumed"]:
        tags.append("not consumed")
    if row["chance"] < 1:
        tags.append(("%.4g%% chance" if row["side"] == "out" else "used up %.4g%% of runs") % (row["chance"] * 100))
    if row.get("oredict_alts"):
        alts = json.loads(row["oredict_alts"])
        tags.append("or " + ", ".join("%s %s" % (fmt_amount(a, r * row["amount"]), item_name(con, a, names))
                                       for a, r in alts[:3]) + (" ..." if len(alts) > 3 else ""))
    return s + (" [" + "; ".join(tags) + "]" if tags else "")


def recipe_flags(r):
    bits = []
    if r["source"] == "gregtech" and r["tier"] is not None:
        bits.append("%s %s EU/t" % (tier_name(r["tier"]), fmt_num(r["eut"])))
    elif r["source"] == "gregtech":
        bits.append("%s EU/t" % fmt_num(r["eut"]))
    elif r["eut"]:
        bits.append("%s EU/t" % fmt_num(r["eut"]))
    bits.append("%ss" % fmt_num(r["ticks"] / 20.0))
    if r["source"] == "gregtech" and r["eut"]:
        bits.append("%s EU total" % fmt_num(r["eut"] * r["ticks"]))
    if r["circuit"] is not None:
        bits.append("circuit %d" % r["circuit"])
    if r["cleanroom"]:
        bits.append("cleanroom")
    if r["lowgrav"]:
        bits.append("low gravity")
    if r["heat"]:
        bits.append("%dK coil heat" % r["heat"])
    sp = json.loads(r["special"]) if r.get("special") else {}
    if sp.get("fusionStartupEu"):
        bits.append("fusion start %s EU" % fmt_num(sp["fusionStartupEu"]))
    if sp.get("research"):
        bits.append("research %s" % sp["research"])
    if r["fake"]:
        bits.append("display-only (fake) recipe")
    if sp.get("incomplete"):
        bits.append("inputs not exported")
    return ", ".join(bits)


def format_recipe(con, r, names=None, io=None, focus=None):
    """One recipe in two or three lines."""
    names = {} if names is None else names
    io = io if io is not None else io_rows(con, r["id"])
    ins = [x for x in io if x["side"] == "in"]
    outs = [x for x in io if x["side"] == "out"]
    head = "#%s %s (%s)" % (r["hash"], r["machine"] or r["map"], recipe_flags(r))
    return "%s\n  in:  %s\n  out: %s" % (head, "; ".join(fmt_io(con, x, names) for x in ins) or "(nothing)",
                                         "; ".join(fmt_io(con, x, names) for x in outs))


def _filters(tier=None, heat=None, cleanroom=None, lowgrav=None, include_fake=False, machine=None):
    where, args = [], []
    if tier is not None:
        where.append("(r.tier IS NULL OR r.tier <= ?)")
        args.append(tier)
    if heat is not None:
        where.append("(r.heat IS NULL OR r.heat <= ?)")
        args.append(heat)
    if cleanroom is False:
        where.append("r.cleanroom = 0")
    if lowgrav is False:
        where.append("r.lowgrav = 0")
    if not include_fake:
        where.append("(r.fake = 0 OR r.map IN ('gt.recipe.fakeAssemblylineProcess', 'gt.recipe.rockbreaker', "
                     "'gt.recipe.multiblockrockbreaker', 'gt.recipe.treefarm'))")
    if machine:
        where.append("(r.map = ? OR r.machine = ? COLLATE NOCASE)")
        args += [machine, machine]
    return where, args


def recipes_touching(con, iid, side, limit=15, offset=0, **filters):
    """Recipes with `iid` on `side` ('out' = producers, 'in' = uses). Real production first (recycling and
    furnace melt-downs last), then the cheapest EU per unit."""
    where, args = _filters(**filters)
    sql = ("SELECT r.*, io.amount * io.chance AS per_run FROM recipe_io io JOIN recipes r ON r.id = io.recipe_id "
           "WHERE io.item_id = ? AND io.side = ? %s "
           "ORDER BY r.recycle, r.source = 'smelting', (r.eut * r.ticks) / MAX(io.amount * io.chance, 1e-9), "
           "r.tier, r.ticks LIMIT ? OFFSET ?"
           % "".join(" AND " + w for w in where))
    total = con.execute("SELECT COUNT(DISTINCT r.id) FROM recipe_io io JOIN recipes r ON r.id = io.recipe_id "
                        "WHERE io.item_id = ? AND io.side = ? %s" % "".join(" AND " + w for w in where),
                        [iid, side] + args).fetchone()[0]
    rows, seen = [], set()
    for r in con.execute(sql, [iid, side] + args + [limit, offset]):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        rows.append(dict(r))
    return rows, total
