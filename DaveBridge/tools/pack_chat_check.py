#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["websockets>=14"]
# ///
"""Chat-rendering check against a LOCAL copy of the real pack server (never production).

Logs a scripted plain 1.7.10 client (PlainBot, no DaveBridge client half) and a scripted client half (ModBot) into
the pack server, claiming exactly the server's mod list (read over eval), and checks what players really receive:

  * a long multi-sentence reply (wider than maxLineLength) arrives as ONE chat message, not several <Dave> lines;
  * {quest:NOR and NAND Chips} resolves although the quest's real title is "§5§lNOR and NAND Chips", and the line
    carries BetterQuesting's share token for that quest, alone and unstyled.

    python -I DaveBridge/tools/pack_chat_check.py --config <pack>/config/davebridge.cfg --mc-port 25565 \
        --rcon-port 25575 --rcon-password-file <file>

With --rcon-password-file, the whitelist is turned off for the run and on again afterwards (the test pack server
has one, and in offline mode `whitelist add` does not match the bots' offline UUIDs).
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_chat_test as e2e  # noqa: E402
from e2e_chat_test import Bot, flatten, components, queue_get_matching  # noqa: E402
from eval_check import Rcon, read_token  # noqa: E402

QUEST = "NOR and NAND Chips"
LONG = ("Steel comes from the Electric Blast Furnace once you reach MV, but before that you can make it in the "
        "Bricked Blast Furnace from iron and coal coke. The EBF needs Cupronickel coils at first and a Maintenance "
        "Hatch, an Energy Hatch, input and output buses and a Muffler Hatch. Run it at 120 EU/t for steel, which "
        "takes about a minute per ingot, and remember to keep the coils topped up. After that, Kanthal coils let "
        "you smelt aluminium and later stainless steel, which opens up the HV tier.")


async def main(a):
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        detail = str(detail)
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  ({detail[:700]})" if detail else ""), flush=True)

    ws = await websockets.connect(a.url, additional_headers={"Authorization": "Bearer " + read_token(a.config)})
    json.loads(await ws.recv())
    n = [0]

    async def request(msg, timeout=30):
        n[0] += 1
        rid = "p%d" % n[0]
        await ws.send(json.dumps(dict(msg, reqId=rid)))
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), max(0.05, end - loop.time())))
            if m.get("reqId") == rid:
                return m

    r = await request({"type": "eval", "script": (
        "def q = com.tuxprogrammer.davebridge.server.compat.BqQuests.find(params.quest)\n"
        "[mods: cpw.mods.fml.common.Loader.instance().getActiveModList().collect { [it.modId, it.version] },\n"
        " width: com.tuxprogrammer.davebridge.common.Config.maxLineLength,\n"
        " quest: q == null ? null : [name: q.name, token: q.shareToken()]]"), "params": {"quest": QUEST},
        "timeoutMs": 5000})
    res = r.get("result") or {}
    quest = res.get("quest") or {}
    check("server finds the quest by its plain title; the real title has formatting codes",
          quest.get("name", "").startswith("§") and quest.get("name", "").endswith(QUEST), quest or r)
    # claim exactly the server's mods (DaveBridge is added by Bot for the client half; it is optional for others)
    e2e.MODS = [(m, v) for m, v in res.get("mods", []) if m != "davebridge"]
    print("server: %d mods, maxLineLength %s" % (len(e2e.MODS), res.get("width")))

    rcon = None
    if a.rcon_password_file:
        rcon = Rcon("127.0.0.1", a.rcon_port, Path(a.rcon_password_file).read_text().strip())
        rcon.command("whitelist off")
    plain = Bot(a.mc_host, a.mc_port, "PlainBot")
    mod = Bot(a.mc_host, a.mc_port, "ModBot", client_mod=True, mod_version="0.2.0")
    try:
        await plain.connect()
        await mod.connect()
        await asyncio.sleep(3)
        await mod.send_dave("client_hello", {"modVersion": "0.2.0", "protocol": 1, "clientEvalAllowed": False,
                                             "capabilities": ["render", "ask", "context", "lesson", "nei", "eval"]})
        await asyncio.sleep(2)
        r = await request({"type": "list_players"})
        flags = {p["player"]: p["hasClientMod"] for p in r.get("players", [])}
        check("both bots are on the pack server", flags == {"PlainBot": False, "ModBot": True},
              [r, plain.disconnect_reason, mod.disconnect_reason])

        async def received(bot, needle, quiet=2.0):
            """Every chat message that arrives until `quiet` seconds pass with nothing new, after the first match."""
            first, _ = await queue_get_matching(bot.chat, lambda c: needle in c, timeout=10)
            got = [first] if first else []
            while first:
                more, _ = await queue_get_matching(bot.chat, lambda c: True, timeout=quiet)
                if more is None:
                    break
                got.append(more)
            return got

        for bot in (plain, mod):
            while not bot.chat.empty():
                bot.chat.get_nowait()
        ack = await request({"type": "say", "target": "@a", "markup": LONG})
        check("long reply acked without warnings", ack.get("type") == "ack" and not ack.get("warnings"), ack)
        for bot in (plain, mod):
            msgs = [m for m in await received(bot, "Electric Blast Furnace") if "Dave" in flatten(m)]
            text = flatten(msgs[0]) if msgs else ""
            check(f"{bot.name}: a {len(LONG)}-character reply is ONE chat message",
                  len(msgs) == 1 and text.startswith("<Dave> ") and text.endswith("opens up the HV tier.")
                  and len(text) >= len(LONG), [flatten(m) for m in msgs])

        markup = ("Next, wafers and chips: {quest:%s}\nEngrave the wafer in a "
                  "{recipe:gregtech:gt.metaitem.03:32042|Laser Engraver} first." % QUEST)
        ack = await request({"type": "say", "target": "@a", "markup": markup})
        check("quest by coloured title: say acked without warnings",
              ack.get("type") == "ack" and not ack.get("warnings"), ack)
        for bot in (plain, mod):
            msgs = await received(bot, "betterquesting.msg.sharequest:")
            line = msgs[0] if msgs else None
            runs = [c for c in components(line) if "betterquesting.msg.sharequest:" in c.get("text", "")] if line else []
            ids = re.findall(r"betterquesting\.msg\.sharequest:(\S{24})", runs[0]["text"]) if runs else []
            check(f"{bot.name}: quest line carries BQ's token for '{QUEST}', unstyled, no other link on it",
                  ids and "betterquesting.msg.sharequest:" + ids[0] == quest.get("token")
                  and "clickEvent" not in json.dumps(json.loads(line)) and "Laser Engraver" not in flatten(line),
                  flatten(line) if line else msgs)
            rest = [m for m in msgs[1:] if "Laser Engraver" in flatten(m)]
            check(f"{bot.name}: the recipe link follows as its own message", len(rest) == 1,
                  [flatten(m) for m in msgs])
            rec = [c for c in components(rest[0]) if "clickEvent" in c] if rest else []
            want = ("/davebridge nei recipe gregtech:gt.metaitem.03:32042" if bot is mod else "/nei_bookmark ")
            check(f"{bot.name}: recipe link click is {want.strip()}",
                  rec and all(c["clickEvent"]["value"].startswith(want) for c in rec), rec)

        # the pack has GTNHLib: fluids are its client-localized component (a dev runServer only has the fallback)
        ack = await request({"type": "say", "target": "@a", "markup": "Cool it with {fluid:water}."})
        for bot in (plain, mod):
            msgs = await received(bot, "Cool it with", quiet=1.0)
            fluid = [c for c in components(msgs[0]) if c.get("gtnhlib_id") == "gtnhlib:ChatComponentFluidName"] \
                if msgs else []
            check(f"{bot.name}: fluid is GTNHLib's client-localized name with a details hover",
                  len(fluid) == 1 and "Fluid: water" in json.dumps(fluid[0].get("hoverEvent")), msgs or ack)
    finally:
        for bot in (plain, mod):
            try:
                await bot.close()
            except Exception:  # noqa: BLE001
                pass
        if rcon:
            rcon.command("whitelist on")
        await ws.close()

    failed = results.count(False)
    print(f"\nChecks: {len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--config", required=True)
    p.add_argument("--mc-host", default="127.0.0.1")
    p.add_argument("--mc-port", type=int, default=25565)
    p.add_argument("--rcon-port", type=int, default=25575)
    p.add_argument("--rcon-password-file")
    sys.exit(asyncio.run(main(p.parse_args())))
