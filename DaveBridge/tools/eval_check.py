#!/usr/bin/env python3
"""Live check of milestone 2 (eval, describe, confirms, test hooks) against a LOCAL dev or test server.

Standard library only (it reuses the daemon's WebSocket client, dave/daemon/ws.py). Never point it at production
unless the owner asked for a gym run: it changes blocks (one glass block at the given position, then air again).

    python3 -I DaveBridge/tools/eval_check.py --config run/server/config/davebridge.cfg \
        --rcon 127.0.0.1:25575 --rcon-password-file <file> [--url ws://127.0.0.1:25580] [--gt]

--config reads authToken from davebridge.cfg (never printed). --rcon enables the console steps (/dave pending,
/dave confirm, /dave cancel, /dave ask); the server needs enable-rcon=true. --gt also runs the GregTech-only checks
(live recipe lookup, describe of GT machines) for a real pack server. Prints PASS/FAIL lines and a summary; exits 1
on any failure.
"""

import argparse
import asyncio
import json
import re
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dave.daemon.ws import WebSocket  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail else ""), flush=True)


def read_token(path):
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*S:authToken=(.*)$", line)
        if m:
            return m.group(1).strip()
    raise SystemExit("authToken not found in %s" % path)


class Rcon:
    """Minimal Source RCON client (what rcon-cli speaks)."""

    def __init__(self, host, port, password):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.rid = 0
        if self._send(3, password)[0] == -1:
            raise SystemExit("RCON authentication failed")

    def _send(self, kind, body):
        self.rid += 1
        data = struct.pack("<ii", self.rid, kind) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(data)) + data)
        size = struct.unpack("<i", self._read(4))[0]
        payload = self._read(size)
        rid, _ = struct.unpack("<ii", payload[:8])
        return rid, payload[8:-2].decode("utf-8", "replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON closed")
            buf += chunk
        return buf

    def command(self, cmd):
        return self._send(2, cmd)[1]


class Agent:
    """One reader task: replies go to the waiting request (by reqId), everything else to the event list."""

    def __init__(self, ws):
        self.ws, self.n, self.events, self.waiting = ws, 0, [], {}
        self.changed = asyncio.Event()
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        while True:
            m = json.loads(await self.ws.recv())
            fut = self.waiting.pop(m.get("reqId"), None)
            if fut is not None and not fut.done():
                fut.set_result(m)
            else:
                self.events.append(m)
                self.changed.set()

    async def request(self, msg, timeout=30):
        self.n += 1
        rid = "c%d" % self.n
        fut = asyncio.get_running_loop().create_future()
        self.waiting[rid] = fut
        await self.ws.send(json.dumps(dict(msg, reqId=rid)))
        return await asyncio.wait_for(fut, timeout)

    async def wait_event(self, pred, timeout=15):
        end = time.monotonic() + timeout
        while True:
            for m in list(self.events):
                if pred(m):
                    self.events.remove(m)
                    return m
            self.changed.clear()
            await asyncio.wait_for(self.changed.wait(), max(0.1, end - time.monotonic()))

    async def eval(self, script, **kw):
        wait = kw.pop("_wait", 60)
        return await self.request(dict({"type": "eval", "script": script}, **kw), timeout=wait)


async def main(args):
    token = read_token(args.config)
    ws = await WebSocket.connect(args.url, headers={"Authorization": "Bearer " + token})
    hello = json.loads(await ws.recv())
    a = Agent(ws)
    accepts = set(hello.get("accepts") or [])
    check("hello advertises eval, describe, client_eval", {"eval", "describe", "client_eval"} <= accepts,
          sorted(accepts))
    print("server: DaveBridge %s" % hello.get("version"))

    r = await a.eval("def s = world.getSpawnPoint()\n"
                     "[dim: world.provider.dimensionId, motd: server.getMOTD(), stone: Blocks.stone.getLocalizedName(), "
                     "players: dave.players().size(), spawn: [s.posX, world.getTopSolidOrLiquidBlock(s.posX, s.posZ), s.posZ]]")
    check("eval read returns JSON (MCP names: provider.dimensionId, getMOTD, Blocks.stone)",
          r.get("ok") and r["result"]["dim"] == 0 and r["result"]["stone"], r.get("result") or r)
    sx, top, sz = (r.get("result") or {}).get("spawn") or (0, 64, 0)

    r = await a.eval("println 'hello from the script'; 6 * 7")
    check("println goes to output", r.get("ok") and r["result"] == 42 and "hello from the script" in r.get("output", ""),
          r)

    t0 = (await a.request({"type": "ping"}))["tick"]
    r = await a.eval("while (true) { }", timeoutMs=300)
    check("infinite loop stops with errorType timeout", r.get("errorType") == "timeout", r.get("error"))
    await asyncio.sleep(2)
    t1 = (await a.request({"type": "ping"}))["tick"]
    check("server keeps ticking after a timeout", t1 > t0, "tick %s -> %s" % (t0, t1))

    r = await a.eval("def x = null\nx.foo()")
    check("exception is returned with its line", r.get("errorType") == "exception" and r.get("line") == 2, r.get("error"))
    r = await a.eval("def (")
    check("compile error is returned", r.get("errorType") == "compile", (r.get("error") or "")[:80])
    r = await a.eval("System.exit(0)")
    check("System.exit is blocked", r.get("errorType") == "blocked", r.get("error"))
    r = await a.eval("world.setBlock(0, 200, 0, Blocks.glass)")
    check("a read script that changes the world needs confirm", r.get("errorType") == "needs_confirm", r.get("error"))
    r = await a.eval("(1..100000).collect { it }")
    check("big results are capped", r.get("ok") and r.get("truncated"), "%d items" % len(r.get("result") or []))

    x, y, z = sx, min(250, top + 40), sz
    d = await a.request({"type": "describe", "target": "block", "dim": 0, "x": sx, "y": 0, "z": sz})
    check("describe block (bedrock under spawn)", d.get("type") == "description"
          and "bedrock" in (d["description"].get("id") or ""), d.get("description"))
    d = await a.request({"type": "describe", "target": "looking", "player": "NobodyHere"})
    check("describe for an absent player is not_found", d.get("code") == "not_found", d)

    r = await a.request({"type": "client_eval", "player": "NobodyHere", "script": "1"})
    check("client_eval for an absent player is refused", r.get("type") == "error", r.get("code"))

    ack = await a.request({"type": "say", "target": "Gym", "text": "whisper to nobody"})
    check("whisper to an offline player acks with a warning", ack.get("ok") and ack.get("recipients") == 0
          and any("not online" in w for w in ack.get("warnings", [])), ack)

    if args.rcon:
        host, port = args.rcon.rsplit(":", 1)
        password = Path(args.rcon_password_file).read_text().strip()
        rcon = Rcon(host, int(port), password)

        write = "world.setBlock(params.x as int, params.y as int, params.z as int, Blocks.glass); 'placed'"
        task = asyncio.create_task(a.eval(write, mode="write", player="Gym", summary="Put one glass block in the sky",
                                          params={"x": x, "y": y, "z": z}, id="w1"))
        pending = await a.wait_event(lambda m: m.get("type") == "eval_pending" and m.get("id") == "w1")
        check("write mode sends eval_pending", bool(pending.get("confirmId")), pending)
        listing = rcon.command("dave pending")
        check("/dave pending lists it", pending["confirmId"] in listing, listing.strip()[:120])
        out = rcon.command("dave confirm " + pending["confirmId"])
        r = await task
        check("console /dave confirm runs it", r.get("ok") and r.get("confirmed") and r.get("result") == "placed",
              "%s | %s" % (out.strip(), r))
        d = await a.request({"type": "describe", "target": "block", "dim": 0, "x": x, "y": y, "z": z})
        check("the confirmed change happened", "glass" in (d["description"].get("id") or ""), d["description"].get("id"))
        again = rcon.command("dave confirm " + pending["confirmId"])
        check("a confirm runs only once", "already handled" in again, again.strip())

        task = asyncio.create_task(a.eval("world.setBlockToAir(params.x as int, params.y as int, params.z as int)",
                                          mode="write", player="Gym", summary="Remove the glass", id="w2",
                                          params={"x": x, "y": y, "z": z}))
        pending = await a.wait_event(lambda m: m.get("type") == "eval_pending" and m.get("id") == "w2")
        rcon.command("dave cancel " + pending["confirmId"])
        r = await task
        check("console /dave cancel cancels it", r.get("errorType") == "cancelled", r.get("error"))

        r = await a.eval("1", mode="write", player="Gym", summary="expires", confirmTimeoutSeconds=5, id="w3", _wait=40)
        check("an unanswered confirm expires", r.get("errorType") == "expired", r.get("error"))

        # clean up: remove the glass (confirmed from the console)
        task = asyncio.create_task(a.eval("world.setBlockToAir(params.x as int, params.y as int, params.z as int); 'ok'",
                                          mode="write", player="Gym", summary="Remove the test glass", id="w4",
                                          params={"x": x, "y": y, "z": z}))
        pending = await a.wait_event(lambda m: m.get("type") == "eval_pending" and m.get("id") == "w4")
        rcon.command("dave confirm " + pending["confirmId"])
        r = await task
        check("cleanup write confirmed", r.get("ok"), r.get("result"))

        out = rcon.command("dave ask Gym @10,70,-5 where is my blast furnace?")
        ev = await a.wait_event(lambda m: m.get("type") == "chat" and m.get("source") == "console")
        check("/dave ask sends a console chat event", ev.get("player") == "Gym" and ev.get("triggered")
              and ev.get("prompt") == "where is my blast furnace?" and ev.get("x") == 10 and ev.get("dim") == 0
              and ev.get("hasClientMod") is False and ev.get("playerUuid"), "%s | %s" % (out.strip(), ev))
        out = rcon.command("dave ask Gym dave, steel?")
        ev = await a.wait_event(lambda m: m.get("type") == "chat" and m.get("source") == "console")
        check("/dave ask strips a trigger prefix and defaults to spawn", ev.get("prompt") == "steel?", ev)

    queries = ROOT / "dave" / "queries"
    samples = {"where-is-machine": {"type": "chest"}, "find-item": {"item": "minecraft:cobblestone"},
               "find-structure": {"type": "all"}, "nearest-ore-vein": {"ore": "iron"},
               "gt-recipes": {"item": "minecraft:iron_ingot"}}
    for name, params in samples.items():
        script = (queries / (name + ".groovy")).read_text()
        r = await a.eval(script, params=params, timeoutMs=5000, id="q:" + name)
        gt_only = name in ("gt-recipes", "nearest-ore-vein") and not args.gt
        res = r.get("result")
        ok = r.get("ok") and isinstance(res, dict) and not res.get("error")
        if gt_only:
            print("INFO %s (needs GT/VisualProspecting; dev server): %s" % (
                name, json.dumps(res)[:200] if r.get("ok") else r.get("error", "")[:200]))
        else:
            check("starter query %s runs" % name, ok, json.dumps(res)[:300] if r.get("ok") else r.get("error"))

    if args.gt:
        r = await a.eval((queries / "gt-recipes.groovy").read_text(), timeoutMs=5000,
                         params={"item": "gregtech:gt.metaitem.03:32041", "limit": 3})
        res = r.get("result") or {}
        # NAND chip: ItemList.Circuit_Chip_NAND = MetaGeneratedItem03 id 41 + offset 32000 (IDMetaItem03.java:33)
        check("gt-recipes finds the NAND chip recipes live", r.get("ok") and res.get("gtRecipesMatched", 0) > 0,
              json.dumps(res)[:1500] if r.get("ok") else r.get("error"))
        r = await a.eval((queries / "gt-recipes.groovy").read_text(), timeoutMs=5000,
                         params={"item": "gregtech:gt.metaitem.03:32042", "map": "engraver", "limit": 2})
        res = r.get("result") or {}
        # the engraver makes the NOR wafer (32042); the cutting saw turns it into chips (32043)
        check("gt-recipes finds the NOR wafer engraver recipe", r.get("ok") and res.get("gtRecipesMatched", 0) > 0,
              json.dumps(res)[:1500] if r.get("ok") else r.get("error"))
        r = await a.eval("[stone: Blocks.stone.getLocalizedName(), dim: world.provider.dimensionId, "
                         "motd: server.getMOTD(), inv: dave.mcp('field_71071_by'), "
                         "tiles: world.loadedTileEntityList.size()]")
        check("SRG translation in an obfuscated server", r.get("ok"), r.get("result") or r.get("error"))
        r = await a.eval((queries / "nearest-ore-vein.groovy").read_text(), timeoutMs=5000, params={"ore": "iron"})
        check("nearest-ore-vein runs against VisualProspecting", r.get("ok") and not (r.get("result") or {}).get("error"),
              json.dumps(r.get("result"))[:400] if r.get("ok") else r.get("error"))

    print("\nChecks: %d passed, %d failed" % (RESULTS.count(True), RESULTS.count(False)))
    await ws.close()
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--config", required=True)
    p.add_argument("--rcon")
    p.add_argument("--rcon-password-file")
    p.add_argument("--gt", action="store_true")
    sys.exit(asyncio.run(main(p.parse_args())))
