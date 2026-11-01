"""plan_chain: the best production chain for an item, as a lexicographic linear program solved with HiGHS (highspy).

1. Candidate graph. Walk backwards from the target through recipe_io: the producers of every item, filtered by the
   player's tier, coil heat, cleanroom and low gravity, bans, display-only recipes and recycling, cheapest EU per unit
   first and at most `per_item` per item. The walk stops at raw resources (raw_resources), at free inputs, and at a
   depth or size limit. An ore dictionary slot becomes 1:1 conversions from its member items.
2. LP. One rate variable per recipe (runs per second), one balance row per item:
   production - consumption + import - surplus = demand. Byproducts go to surplus; cycles need no special handling.
   Imports exist only for items the walk did not expand, each at a price by class.
3. Objective, lexicographic (each stage keeps the previous optimum within a small tolerance):
   1) EU per target unit: machine EU (EU/t x ticks per run) plus raw resources at an EU-equivalent price by class
      (free 0; cheap and costly a fixed price; anything unexpanded or unavailable at the player's tier a prohibitive
      one). Pure machine EU would make any ore-electrolysis byproduct route "best" and ignores that mining costs
      something; the price list is RAW_PRICE below. The machine EU alone is reported separately.
   2) raw-resource cost by class weight; 3) machine count at base speed; 4) total flow.
4. Steering: locks (a recipe id or a machine) in a strong form: "direct" (it makes the target, and nothing else
   does) when feasible, else "route1-3" (the target is made 1-3 steps downstream of it, from what it makes; the
   cheapest wins; empty cells and buckets do not count as a link); only if none is feasible, "weak" (it just has to
   run). The plan says which form held, free inputs (import at no cost, not expanded), bans (recipe id, machine or map, mod, or item: no import).
5. Runner-up: the same problem with the winning route's last step (the main producer of the target) banned.

Machine counts are at base speed with no overclocking: with standard overclocks EU per item goes UP, so the least-EU
answer is the un-overclocked one; overclocking changes machine counts, not the ranking.
"""

import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipedb as R  # noqa: E402

try:  # the one non-stdlib dependency (tools/recipes/requirements.txt)
    import highspy
    import numpy as np
except ImportError:  # pragma: no cover - reported by plan_chain
    highspy = None
    np = None

# EU-equivalent price of importing one unit (one item, or 1000 L of a fluid) by cost class.
RAW_PRICE = {"free": 0.0, "cheap": 2_000.0, "costly": 100_000.0, "unavailable": 10_000_000.0,
             "frontier": 10_000_000.0}
# Stage-2 weights per unit by class.
RAW_WEIGHT = {"free": 0.0, "cheap": 1.0, "costly": 10.0, "unavailable": 1000.0, "frontier": 1000.0}
REAL_FAKE_MAPS = ("gt.recipe.fakeAssemblylineProcess", "gt.recipe.rockbreaker", "gt.recipe.multiblockrockbreaker",
                  "gt.recipe.treefarm")
LOCK_RATE = 1e-3          # runs per second a locked recipe or machine must at least do
LOCK_MODES = {
    "direct": "the target is made only by the locked step",
    "route1": "the target is made one step after the locked step, from what it makes",
    "route2": "the target is made two steps after the locked step, from what it makes",
    "route3": "the target is made three steps after the locked step, from what it makes",
    "weak": "the locked step only has to run",
}
REL_TOL = 1e-5            # lexicographic tolerance: later stages may give up this much of an earlier optimum
MAX_ORE_MEMBERS = 6


class PlanError(Exception):
    pass


class _Infeasible(Exception):
    pass


def unit_scale(iid):
    """Per-unit factor: prices are per item and per 1000 L."""
    return 1e-3 if iid.startswith("fluid:") else 1.0


def default_rate(iid):
    return 1000.0 if iid.startswith("fluid:") else 1.0


def fmt_rate(iid, per_s):
    if iid.startswith("fluid:"):
        return "%s L/s" % R.fmt_num(round(per_s, 3))
    return "%s/s" % R.fmt_num(round(per_s, 4))


def fmt_unit(iid):
    return "1,000 L" if iid.startswith("fluid:") else "item"


class Planner:
    def __init__(self, con, target, rate=None, tier=None, heat=None, cleanroom=True, lowgrav=False, locks=(),
                 free=(), banned=(), max_depth=8, max_recipes=3000, per_item=25):
        if highspy is None:
            raise PlanError("the chain planner needs highspy: pip install -r tools/recipes/requirements.txt")
        self.con = con
        self.names = {}
        tid, err = R.resolve(con, target)
        if err:
            raise PlanError("target: " + err)
        self.target = tid
        self.rate = float(rate) if rate else default_rate(tid)
        if self.rate <= 0:
            raise PlanError("rate must be positive")
        self.tier = R.parse_tier(tier)
        self.heat = R.parse_heat(heat, self.tier)
        self.cleanroom = True if cleanroom is None else bool(cleanroom)
        self.lowgrav = bool(lowgrav)
        self.max_depth, self.max_recipes, self.per_item = int(max_depth), int(max_recipes), int(per_item)
        self.notes = []
        self.free = set()
        for f in free or ():
            iid, err = R.resolve(con, f)
            if err:
                raise PlanError("free input: " + err)
            self.free.add(iid)
        self.ban_hashes, self.ban_maps, self.ban_mods, self.ban_items = set(), set(), set(), set()
        for b in banned or ():
            self._ban(b)
        self.lock_hashes, self.lock_maps = set(), set()
        for lk in locks or ():
            self._lock(lk)

    # ---------------------------------------------------------------- steering
    def _map_ids(self, ref):
        ref = str(ref).strip()
        rows = self.con.execute("SELECT id FROM maps WHERE id = ? OR name = ? COLLATE NOCASE", (ref, ref)).fetchall()
        if not rows:
            rows = self.con.execute("SELECT DISTINCT map AS id FROM machines WHERE name = ? COLLATE NOCASE",
                                    (ref,)).fetchall()
        return {r["id"] for r in rows}

    def _ban(self, ref):
        ref = str(ref).strip()
        if not ref:
            return
        r = R.recipe_by_ref(self.con, ref) if len(ref.lstrip("#")) >= 6 else None
        if r:
            self.ban_hashes.add(r["hash"])
            return
        maps = self._map_ids(ref)
        if maps:
            self.ban_maps |= maps
            return
        low = ref.lower()
        if self.con.execute("SELECT 1 FROM items WHERE lower(mod) = ? LIMIT 1", (low,)).fetchone() or \
                self.con.execute("SELECT 1 FROM maps WHERE id LIKE ? LIMIT 1", (low + ".%",)).fetchone():
            self.ban_mods.add(low)
            self.ban_maps |= {m["id"] for m in self.con.execute("SELECT id FROM maps WHERE lower(id) LIKE ?",
                                                                  (low + ".%",))}
            return
        iid, err = R.resolve(self.con, ref)
        if err:
            raise PlanError("ban %r: not a recipe id, machine, mod or item (%s)" % (ref, err))
        self.ban_items.add(iid)

    def _lock(self, ref):
        ref = str(ref).strip()
        r = R.recipe_by_ref(self.con, ref) if len(ref.lstrip("#")) >= 6 else None
        if r:
            self.lock_hashes.add(r["hash"])
            return
        maps = self._map_ids(ref)
        if not maps:
            raise PlanError("lock %r: not a recipe id or a machine / recipe map name" % ref)
        self.lock_maps |= maps

    # ---------------------------------------------------------------- graph
    def allowed(self, r):
        if r["hash"] in self.ban_hashes or r["map"] in self.ban_maps:
            return False, "banned"
        if r["fake"] and r["map"] not in REAL_FAKE_MAPS:
            return False, "display-only"
        sp = json.loads(r["special"]) if r["special"] else {}
        if sp.get("incomplete"):
            return False, "inputs not exported"
        if self.tier is not None and r["tier"] is not None and r["tier"] > self.tier:
            return False, "needs %s" % R.tier_name(r["tier"])
        if self.heat is not None and r["heat"] and r["heat"] > self.heat:
            return False, "needs %dK coils" % r["heat"]
        if r["eut"] <= 0 and not any(x["side"] == "in" and x["consumed"] for x in self.io(r["id"])):
            # 0 EU and nothing consumed: a display of what a special machine yields (Eye of Harmony, algae pond,
            # tree growth simulator) or a crafting recipe whose inputs the exporter could not read. Its real cost is
            # not in the data, and as a free source it would win every plan.
            return False, "no modelled cost"
        if r["cleanroom"] and not self.cleanroom:
            return False, "needs a cleanroom"
        if r["lowgrav"] and not self.lowgrav:
            return False, "needs low gravity"
        return True, None

    def io(self, rid):
        if rid not in self._io:
            self._io[rid] = R.io_rows(self.con, rid)
        return self._io[rid]

    def build_graph(self):
        con = self.con
        self._io = {}
        self.recipes = {}           # hash -> recipe row
        self.convs = []             # (from member, to node)
        self.imports = {}           # item -> class
        self.why_import = {}
        self.items = set()
        locked = {}
        for h in self.lock_hashes:
            r = dict(con.execute("SELECT * FROM recipes WHERE hash = ?", (h,)).fetchone())
            ok, why = self.allowed(r)
            if not ok:
                raise PlanError("locked recipe #%s is not usable: %s" % (h, why))
            locked[h] = r
        raw = {r["item_id"]: r["class"] for r in con.execute("SELECT item_id, class FROM raw_resources")}
        queue = deque([(self.target, 0)])
        for r in locked.values():
            self.recipes[r["hash"]] = r
            for x in self.io(r["id"]):
                if x["side"] == "in" and x["consumed"]:
                    queue.append((x["item_id"], 1))
        seen = set()
        filtered_out = defaultdict(list)
        while queue:
            iid, depth = queue.popleft()
            if iid in seen:
                continue
            seen.add(iid)
            self.items.add(iid)
            if iid in self.free:
                self.imports[iid] = "free"
                self.why_import[iid] = "free (you said you have plenty)"
                continue
            if iid != self.target and iid in raw:
                if iid not in self.ban_items and raw[iid] != "never":
                    self.imports[iid] = raw[iid]
                    self.why_import[iid] = "raw resource (%s)" % raw[iid]
                continue
            kind = iid.split(":", 1)[0]
            info = R.item(con, iid) or {}
            if kind in ("ore", "choice") or info.get("kind") == "wildcard":
                members = (json.loads(info["members"]) if info.get("members") else {}).get("items") or []
                ranked = con.execute(
                    "SELECT id FROM items WHERE id IN (%s) ORDER BY (id IN (SELECT item_id FROM raw_resources)) DESC, "
                    "producers DESC LIMIT %d" % (",".join("?" * len(members)), MAX_ORE_MEMBERS),
                    members).fetchall() if members else []
                for m in ranked:
                    self.convs.append((m["id"], iid))
                    queue.append((m["id"], depth))
                if not ranked:
                    self.imports[iid] = "unavailable"
                    self.why_import[iid] = "ore dictionary slot with no known member"
                continue
            if depth >= self.max_depth or len(self.recipes) >= self.max_recipes:
                if iid != self.target:
                    self.imports[iid] = "frontier"
                    self.why_import[iid] = "not expanded (depth or size limit)"
                continue
            rows = con.execute(
                "SELECT r.*, io.amount * io.chance AS per_run FROM recipe_io io JOIN recipes r ON r.id = io.recipe_id "
                "WHERE io.item_id = ? AND io.side = 'out' AND r.recycle = 0", (iid,)).fetchall()
            cands = []
            for r in rows:
                r = dict(r)
                ok, why = self.allowed(r)
                if not ok:
                    filtered_out[iid].append(why)
                    continue
                cands.append(r)
            cands.sort(key=lambda r: (r["map"] not in self.lock_maps,
                                      (r["eut"] * r["ticks"]) / max(r["per_run"], 1e-9), r["ticks"]))
            keep = [r for r in cands if r["map"] in self.lock_maps] + \
                   [r for r in cands if r["map"] not in self.lock_maps][:self.per_item]
            for r in keep:
                if r["hash"] in self.recipes:
                    continue
                self.recipes[r["hash"]] = r
                for x in self.io(r["id"]):
                    if x["side"] == "in" and x["consumed"] and x["item_id"] not in seen:
                        queue.append((x["item_id"], depth + 1))
                    elif x["side"] == "out":
                        self.items.add(x["item_id"])
            if not keep and iid != self.target:
                self.imports[iid] = "unavailable" if rows else "costly"
                reasons = sorted(set(filtered_out.get(iid, [])))
                self.why_import[iid] = ("no usable recipe: " + ", ".join(reasons)) if reasons else \
                    "no recipe makes it"
        for iid in self.ban_items:
            self.imports.pop(iid, None)
        self.imports.pop(self.target, None)
        self.filtered_out = filtered_out
        if not any(x["side"] == "out" and x["item_id"] == self.target
                   for r in self.recipes.values() for x in self.io(r["id"])):
            reasons = sorted(set(filtered_out.get(self.target, [])))
            raise PlanError("nothing makes %s under these constraints%s" % (
                R.item_name(con, self.target, self.names), (" (" + ", ".join(reasons) + ")") if reasons else ""))

    # ---------------------------------------------------------------- LP
    def solve(self, extra_bans=()):
        recipes = [r for h, r in sorted(self.recipes.items()) if h not in extra_bans]
        items = sorted(self.items | {m for m, _ in self.convs} | {n for _, n in self.convs})
        row = {iid: i for i, iid in enumerate(items)}
        cols = []   # (kind, key, entries [(row, coef)], costs dict)
        for r in recipes:
            ent = defaultdict(float)
            for x in self.io(r["id"]):
                if x["item_id"] not in row:
                    continue
                if x["side"] == "out":
                    ent[row[x["item_id"]]] += x["amount"] * x["chance"]
                elif x["consumed"]:
                    ent[row[x["item_id"]]] -= x["amount"] * x["chance"]
            eu = float(r["eut"]) * r["ticks"]
            cols.append(("recipe", r["hash"], dict(ent), {"eu": eu, "raw": 0.0, "machines": r["ticks"] / 20.0,
                                                          "flow": 1.0, "machine_eu": eu}))
        for m, n in self.convs:
            cols.append(("conv", (m, n), {row[m]: -1.0, row[n]: 1.0},
                         {"eu": 0.0, "raw": 0.0, "machines": 0.0, "flow": 0.0, "machine_eu": 0.0}))
        for iid, cls in sorted(self.imports.items()):
            s = unit_scale(iid)
            cols.append(("import", iid, {row[iid]: 1.0}, {"eu": RAW_PRICE[cls] * s, "raw": RAW_WEIGHT[cls] * s,
                                                         "machines": 0.0, "flow": 0.0, "machine_eu": 0.0}))
        for iid in items:
            cols.append(("surplus", iid, {row[iid]: -1.0}, {"eu": 0.0, "raw": 0.0, "machines": 0.0, "flow": 0.0,
                                                            "machine_eu": 0.0}))
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        inf = highspy.kHighsInf
        n = len(cols)
        lp = highspy.HighsLp()
        lp.num_col_, lp.num_row_ = n, len(items)
        lp.col_cost_ = np.zeros(n)
        lp.col_lower_ = np.zeros(n)
        lp.col_upper_ = np.full(n, inf)
        demand = np.zeros(len(items))
        demand[row[self.target]] = self.rate
        lp.row_lower_ = demand
        lp.row_upper_ = demand.copy()
        starts, idx, val = [0], [], []
        for _, _, ent, _ in cols:
            for k in sorted(ent):
                if ent[k]:
                    idx.append(k)
                    val.append(ent[k])
            starts.append(len(idx))
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = np.array(starts, dtype=np.int32)
        lp.a_matrix_.index_ = np.array(idx, dtype=np.int32)
        lp.a_matrix_.value_ = np.array(val, dtype=np.float64)
        self._lp = (lp, cols)
        modes = ["weak"]
        if self.lock_hashes or self.lock_maps:
            modes = (["direct"] if self._lock_groups(cols)[1] else []) + ["route1", "route2", "route3", "weak"]
        if modes == ["weak"]:
            res = self._run(lp, cols, "weak")
            if res is not None:
                res["lock_mode"] = None
            return res
        # "direct" when the locked step can make the target and that is feasible; otherwise the route forms compete
        # on EU (the cheapest way through the locked step wins); the weak form is the last resort
        found = []
        for mode in modes[:-1]:
            try:
                res = self._run(lp, cols, mode)
            except _Infeasible:
                res = None
            if res is not None:
                res["lock_mode"] = mode
                res["stuck"] = any(c in ("unavailable", "frontier") for _, _, c in res["imports"])
                if mode == "direct" and not res["stuck"]:
                    return res
                found.append(res)
        if found:
            # a form that only works by importing what the player cannot make loses to one that does not
            return min(found, key=lambda r: (r["stuck"], r["stages"]["eu"]))
        res = self._run(lp, cols, "weak")
        if res is not None:
            res["lock_mode"] = "weak"
        return res

    def _lock_groups(self, cols):
        """Lock groups (one per lock: a set of recipe hashes in the graph) and whether any can make the target."""
        recipes = [c[1] for c in cols if c[0] == "recipe"]
        groups = [{h_} for h_ in self.lock_hashes if h_ in recipes]
        groups += [{h_ for h_ in recipes if self.recipes[h_]["map"] == mp} for mp in sorted(self.lock_maps)]
        groups = [g for g in groups if g]
        if len(groups) < len(self.lock_hashes) + len(self.lock_maps):
            raise PlanError("a locked recipe or machine has no usable recipe in this chain (%s)" % ", ".join(
                sorted(self.lock_hashes | self.lock_maps)))
        direct = any(self._makes(h_, self.target) for g in groups for h_ in g)
        return groups, direct

    def _container(self, iid):
        """Empty cells, buckets and capsules circulate; a route must not 'pass through' the locked step by them."""
        name = self.name(iid).lower()
        return name.startswith("empty ") or iid in ("minecraft:bucket", "minecraft:glass_bottle")

    def _makes(self, h_, iid):
        return any(x["side"] == "out" and x["item_id"] == iid for x in self.io(self.recipes[h_]["id"]))

    def _apply_locks(self, h, cols, mode):
        inf = highspy.kHighsInf
        groups, _ = self._lock_groups(cols)
        col_of = {(c[0], c[1]): i for i, c in enumerate(cols)}
        recipes = [c[1] for c in cols if c[0] == "recipe"]
        makes_target = {h_ for h_ in recipes if self._makes(h_, self.target)}
        banned = set()
        for g in groups:
            js = np.array(sorted(col_of[("recipe", h_)] for h_ in g), dtype=np.int32)
            h.addRow(LOCK_RATE, inf, len(js), js, np.ones(len(js)))
            if mode == "direct" and g & makes_target:
                banned |= makes_target - g
            elif mode.startswith("route"):
                banned |= self._route(h, cols, col_of, g, makes_target, int(mode[5:]))
        for h_ in banned - set().union(*groups):
            h.changeColBounds(col_of[("recipe", h_)], 0, 0)

    def _route(self, h, cols, col_of, g, makes_target, k):
        """The target is made `k` recipe steps downstream of lock group g. Level 0 is g; level i+1 the recipes
        consuming what level i makes. The target's producers are restricted to level k, and walking back from them,
        every level must make at least what the next level on the path consumes of it (a flow constraint, so a
        recipe that merely shares a byproduct with the locked step is not banned)."""
        inf = highspy.kHighsInf
        recipes = [c[1] for c in cols if c[0] == "recipe"]
        outs = {h_: {x["item_id"]: x["amount"] * x["chance"] for x in self.io(self.recipes[h_]["id"])
                     if x["side"] == "out"} for h_ in recipes}
        ins = {h_: {x["item_id"]: x["amount"] * x["chance"] for x in self.io(self.recipes[h_]["id"])
                    if x["side"] == "in" and x["consumed"]} for h_ in recipes}
        levels = [set(g)]
        for _ in range(k):
            made = {m for m in set().union(*(outs[h_] for h_ in levels[-1])) - {self.target}
                    if not self._container(m)}
            levels.append({h_ for h_ in recipes if h_ not in levels[-1] and made & set(ins[h_])})
        final = levels[k] & makes_target
        if not final:
            raise _Infeasible()
        # walk back: the recipes on a path to `final`
        path = [None] * (k + 1)
        path[k] = final
        for i in range(k - 1, -1, -1):
            needed = set().union(*(ins[h_] for h_ in path[i + 1]))
            path[i] = {h_ for h_ in levels[i] if needed & set(outs[h_])}
        for i in range(k):
            links = set().union(*(outs[h_] for h_ in path[i])) & set().union(*(ins[h_] for h_ in path[i + 1]))
            for m in (m for m in links if not self._container(m)):
                idx, val = [], []
                for h_ in path[i]:
                    if outs[h_].get(m):
                        idx.append(col_of[("recipe", h_)]); val.append(outs[h_][m])
                for h_ in path[i + 1]:
                    if ins[h_].get(m):
                        idx.append(col_of[("recipe", h_)]); val.append(-ins[h_][m])
                if idx:
                    h.addRow(0.0, inf, len(idx), np.array(idx, dtype=np.int32), np.array(val))
        return makes_target - final

    def _run(self, lp, cols, lock_mode):
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        inf = highspy.kHighsInf
        n = len(cols)
        h.passModel(lp)
        if self.lock_hashes or self.lock_maps:
            self._apply_locks(h, cols, lock_mode)
        stages, x = {}, None
        all_idx = np.arange(n, dtype=np.int32)
        for stage, scale in (("eu", 1e-3), ("raw", 1.0), ("machines", 1.0), ("flow", 1.0)):
            cost = np.array([c[3][stage] * scale for c in cols])
            h.changeColsCost(n, all_idx, cost)
            h.run()
            status = h.getModelStatus()
            if status != highspy.HighsModelStatus.kOptimal:
                if stage == "eu":
                    return None
                # a later stage HiGHS cannot finish keeps the previous stage's optimum
                self.notes.append("stage %s not solved (%s); kept the previous optimum" % (
                    stage, h.modelStatusToString(status)))
                break
            obj = h.getInfo().objective_function_value
            x = np.array(h.getSolution().col_value)
            stages = {k: float(sum(c[3][k] * v for c, v in zip(cols, x))) for k in ("eu", "raw", "machines", "flow")}
            nz = np.nonzero(cost)[0].astype(np.int32)
            if len(nz):
                h.addRow(-inf, obj + REL_TOL * max(1.0, abs(obj)), len(nz), nz, cost[nz])
        return self._result(cols, x, stages)

    def _result(self, cols, x, stages):
        steps, imports, surplus = [], [], []
        machine_eu = 0.0
        # the lexicographic tolerance lets a later stage keep crumbs of other routes; anything this small is noise
        top = max([v for c, v in zip(cols, x) if c[0] == "recipe"] or [0.0])
        for (kind, key, ent, costs), v in zip(cols, x):
            if v <= max(1e-9, 1e-3 * top) and kind in ("recipe", "conv"):
                continue
            if v <= 1e-6:
                continue
            if kind == "recipe":
                r = self.recipes[key]
                machine_eu += costs["machine_eu"] * v
                steps.append({"recipe": r, "runs": v, "machines": v * r["ticks"] / 20.0})
            elif kind == "import" and v > 1e-5 * max(1.0, self.rate):
                imports.append((key, v, self.imports[key]))
            elif kind == "surplus" and v > 1e-6:
                surplus.append((key, v))
        steps.sort(key=lambda s: -s["machines"])
        target_producers = sorted(
            ((sum(xx["amount"] * xx["chance"] for xx in self.io(s["recipe"]["id"])
                  if xx["side"] == "out" and xx["item_id"] == self.target) * s["runs"], s["recipe"]["hash"])
             for s in steps), reverse=True)
        return {"steps": steps, "imports": imports, "surplus": surplus, "stages": stages,
                "machine_eu_per_s": machine_eu, "eu_per_unit": machine_eu / self.rate,
                "main": target_producers[0][1] if target_producers and target_producers[0][0] > 0 else None}

    # ---------------------------------------------------------------- run
    def plan(self, runner_up=True):
        self.build_graph()
        best = self.solve()
        if best is None:
            raise PlanError("no feasible chain for %s under these constraints" % R.item_name(
                self.con, self.target, self.names))
        second = None
        if runner_up and best["main"] and best["main"] not in self.lock_hashes:
            try:
                second = self.solve(extra_bans={best["main"]})
            except PlanError:      # the main step was the locked machine's only usable recipe
                second = None
        return best, second

    # ---------------------------------------------------------------- text
    def name(self, iid):
        return R.item_name(self.con, iid, self.names)

    def step_line(self, s):
        r = s["recipe"]
        io = self.io(r["id"])
        ins = "; ".join(R.fmt_io(self.con, x, self.names) for x in io if x["side"] == "in")
        outs = "; ".join(R.fmt_io(self.con, x, self.names) for x in io if x["side"] == "out")
        if r["source"] == "crafting":
            count = "by hand / crafter"
        else:
            count = "%sx machines (%s busy)" % (math.ceil(s["machines"] - 1e-9), R.fmt_num(round(s["machines"], 2)))
        return "- #%s %s (%s): %s -> %s | %s runs/s, %s" % (
            r["hash"], r["machine"], R.recipe_flags(r), ins, outs, R.fmt_num(round(s["runs"], 4)), count)

    def describe(self, res, limit=12):
        lines = ["CHAIN (%d steps):" % len(res["steps"])]
        for s in res["steps"][:limit]:
            lines.append(self.step_line(s))
        if len(res["steps"]) > limit:
            lines.append("- ... %d more small steps" % (len(res["steps"]) - limit))
        eut = res["machine_eu_per_s"] / 20.0
        per = res["eu_per_unit"] * (1000.0 if self.target.startswith("fluid:") else 1.0)
        lines.append("TOTALS: %s EU/t (machines at base speed); %s EU per %s of %s; machines by type: %s" % (
            R.fmt_num(round(eut, 2)), R.fmt_num(round(per, 1)), fmt_unit(self.target), self.name(self.target),
            ", ".join("%s %s" % (k, v) for k, v in self.machine_summary(res).items()) or "none"))
        lines.append("IMPORTS: " + ("; ".join("%s %s (%s)" % (fmt_rate(i, v), self.name(i), self.why_import.get(i, c))
                                              for i, v, c in sorted(res["imports"], key=lambda t: -t[1]))
                                    or "none"))
        byp = [(i, v) for i, v in res["surplus"] if i != self.target]
        lines.append("BYPRODUCTS: " + ("; ".join("%s %s" % (fmt_rate(i, v), self.name(i))
                                                 for i, v in sorted(byp, key=lambda t: -t[1])[:8]) or "none"))
        return lines

    def machine_summary(self, res):
        out = defaultdict(int)
        for s in res["steps"]:
            r = s["recipe"]
            if r["source"] == "crafting":
                continue
            out["%s (%s)" % (r["machine"], R.tier_name(r["tier"]) if r["source"] == "gregtech" else "-")] += \
                math.ceil(s["machines"] - 1e-9)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def text(self, best, second):
        rate_txt = fmt_rate(self.target, self.rate)
        cons = ["tier %s" % (R.tier_name(self.tier) if self.tier is not None else "any"),
                "coil heat %s" % ("%dK" % self.heat if self.heat is not None else "any"),
                "cleanroom %s" % ("yes" if self.cleanroom else "no"),
                "low gravity %s" % ("yes" if self.lowgrav else "no")]
        if self.free:
            cons.append("free: " + ", ".join(self.name(i) for i in sorted(self.free)))
        if self.ban_hashes or self.ban_maps or self.ban_items:
            cons.append("banned: " + ", ".join(sorted(self.ban_hashes) + sorted(self.ban_maps) +
                                               [self.name(i) for i in sorted(self.ban_items)]))
        if self.lock_hashes or self.lock_maps:
            cons.append("locked: " + ", ".join(sorted(self.lock_hashes) + sorted(self.lock_maps)))
        lines = ["PLAN: %s %s (%s); %s" % (rate_txt, self.name(self.target), self.target, "; ".join(cons))]
        lines += self.describe(best)
        if second is None:
            lines.append("RUNNER-UP: none (the winning step is a locked recipe, or nothing else can make it)")
        else:
            main = self.recipes[best["main"]]
            lines.append("RUNNER-UP (without #%s %s): %s" % (main["hash"], main["machine"],
                                                             self.why_lost(best, second)))
            lines += ["  " + l for l in self.describe(second, limit=5)]
        lines.append("GRAPH: %d candidate recipes, %d items, %d imports considered%s" % (
            len(self.recipes), len(self.items), len(self.imports),
            "; some branches hit the depth/size limit" if any(c == "frontier" for c in self.imports.values()) else ""))
        if best.get("lock_mode"):
            lines.append("LOCK: held in the %s form: %s" % (best["lock_mode"], LOCK_MODES[best["lock_mode"]]))
        for n in dict.fromkeys(self.notes):
            lines.append("NOTE: " + n)
        lines.append("NOTES: least EU per item, raw resources priced by class (free 0, cheap %s, costly %s EU per "
                     "unit); no overclocking; non-consumed inputs (circuits, molds, lenses) are listed but not "
                     "counted; slot alternatives are not substituted." % (
                         R.fmt_num(RAW_PRICE["cheap"]), R.fmt_num(RAW_PRICE["costly"])))
        return "\n".join(lines)

    def why_lost(self, best, second):
        if second is None:
            return "infeasible: nothing else can make it under these constraints"
        mul = 1000.0 if self.target.startswith("fluid:") else 1.0
        b, s = best["stages"], second["stages"]
        main2 = self.recipes[second["main"]]["machine"] if second.get("main") else "?"
        b_eu, s_eu = best["eu_per_unit"] * mul, second["eu_per_unit"] * mul
        if s.get("eu", 0) > b.get("eu", 0) * (1 + 1e-4) + 1e-9:
            extra = ""
            if s.get("raw", 0) > b.get("raw", 0) + 1e-9:
                extra = " and it uses costlier raw resources"
            return "via %s, %s EU per %s by machines vs %s (%s total EU-equivalent incl. raw resources)%s" % (
                main2, R.fmt_num(round(s_eu, 1)), fmt_unit(self.target), R.fmt_num(round(b_eu, 1)),
                "+%.0f%%" % (100.0 * (s["eu"] - b["eu"]) / b["eu"]) if b.get("eu") else "higher", extra)
        if s.get("raw", 0) > b.get("raw", 0) + 1e-9:
            return "via %s, same EU, costlier raw resources" % main2
        if s.get("machines", 0) > b.get("machines", 0) + 1e-9:
            return "via %s, same EU and raw cost, more machines (%s vs %s busy)" % (
                main2, R.fmt_num(round(s["machines"], 1)), R.fmt_num(round(b["machines"], 1)))
        return "via %s, a tie on every measure" % main2


def plan_chain(con, target, rate=None, tier=None, heat=None, cleanroom=True, lowgrav=False, locks=(), free=(),
               banned=(), max_depth=8, max_recipes=3000, runner_up=True):
    """Returns (text, error flag)."""
    try:
        p = Planner(con, target, rate, tier, heat, cleanroom, lowgrav, locks, free, banned, max_depth, max_recipes)
        best, second = p.plan(runner_up=runner_up)
        return p.text(best, second), False
    except (PlanError, ValueError) as e:
        return "plan_chain: %s" % e, True
