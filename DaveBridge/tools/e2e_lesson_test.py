#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["websockets>=14"]
# ///
"""End-to-end check of guided demonstrations (lessons) against a LOCAL dev server. Never a real server.

Uses the scripted 1.7.10 clients from e2e_chat_test.py:

  * PlainBot - no client half: a lesson for it is refused with no_client_mod (Dave falls back to chat).
  * OldBot   - a client half without the "lesson" capability (an older DaveBridge): also no_client_mod.
  * ModBot   - a client half with "lesson": the server validates the agent's lesson (drops far, unknown and
               invalid steps with warnings), acks it, and sends the normalized lesson packet to ModBot only;
               lesson_stop reaches ModBot; ModBot's lesson_status is relayed to the agent.

    uv run tools/e2e_lesson_test.py --mc-port 25566 --url ws://127.0.0.1:25581

Needs online-mode=false in run/server/server.properties. Visuals are not checked here (no real client); see the
manual checklist in docs/plans/guided-demos.md.
"""

import argparse
import asyncio
import json
import os
import re
import sys

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_chat_test import Bot, queue_get_matching  # noqa: E402


async def main(a):
    token = a.token
    if not token:
        with open(a.config, encoding="utf-8") as f:
            token = re.search(r"S:authToken=(\S+)", f.read()).group(1)

    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        detail = str(detail)
        if len(detail) > 600:
            detail = detail[:600] + "..."
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and (not ok or a.verbose) else ""),
              flush=True)

    ws = await websockets.connect(a.url)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    hello = json.loads(await ws.recv())
    accepts = hello.get("accepts", [])
    check("hello advertises lesson and lesson_stop", "lesson" in accepts and "lesson_stop" in accepts, hello)

    async def next_event(pred, timeout=5.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.05, end - loop.time())))
            if pred(msg):
                return msg

    async def request(msg):
        await ws.send(json.dumps(msg))
        return await next_event(lambda m: m.get("reqId") == msg["reqId"])

    async def join(bot, caps=None):
        await bot.connect()
        ev = await next_event(lambda m: m.get("type") == "player_join" and m.get("player") == bot.name, timeout=20)
        if caps is not None:
            await asyncio.sleep(0.5)
            await bot.send_dave("client_hello", {"modVersion": "0.2.0", "protocol": 1, "capabilities": caps,
                                                 "clientEvalAllowed": False})
            ev = await next_event(lambda m: m.get("type") == "client_mod" and m.get("player") == bot.name)
        return ev

    simple = {"id": "s", "steps": [{"swing": True}]}

    # ---- refusals
    r = await request({"type": "lesson", "player": "Nobody", "lesson": simple, "reqId": "off"})
    check("offline player -> not_found", r.get("type") == "error" and r.get("code") == "not_found", r)

    plain = Bot(a.mc_host, a.mc_port, "PlainBot")
    await join(plain)
    r = await request({"type": "lesson", "player": "PlainBot", "lesson": simple, "reqId": "plain"})
    check("player without the client half -> no_client_mod",
          r.get("type") == "error" and r.get("code") == "no_client_mod", r)

    old = Bot(a.mc_host, a.mc_port, "OldBot", client_mod=True)
    cm = await join(old, ["render", "ask", "context"])
    r = await request({"type": "lesson", "player": "OldBot", "lesson": simple, "reqId": "old"})
    check("client half without the lesson capability -> no_client_mod",
          r.get("type") == "error" and r.get("code") == "no_client_mod", [cm, r])

    mod = Bot(a.mc_host, a.mc_port, "ModBot", client_mod=True)
    cm = await join(mod, ["render", "ask", "context", "lesson"])
    check("ModBot reports the lesson capability", "lesson" in cm.get("capabilities", []), cm)
    x, y, z = cm["x"], cm["y"], cm["z"]
    bx, by, bz = int(x // 1), int(y // 1), int(z // 1)

    r = await request({"type": "lesson", "player": "ModBot", "lesson": {"steps": []}, "reqId": "empty"})
    check("lesson without steps -> bad_request", r.get("type") == "error" and r.get("code") == "bad_request", r)
    r = await request({"type": "lesson", "player": "ModBot", "reqId": "nolesson"})
    check("request without 'lesson' -> bad_request", r.get("code") == "bad_request", r)

    # ---- a real lesson
    while not mod.packets.empty():
        mod.packets.get_nowait()
    lesson = {"id": "e2e-1", "title": "E2E lesson", "loop": True, "speed": 0.6, "steps": [
        {"walkTo": [x + 2, y, z + 2]},
        {"lookAt": [x + 4, y + 1, z + 2]},
        {"hold": "minecraft:stick"},
        {"hold": "nope:nothing"},                                            # unknown item: dropped
        {"highlight": {"pos": [bx + 3, by, bz + 3], "color": "gold", "label": "Here"}},
        {"ghost": {"pos": [bx + 3, by + 1, bz + 3], "block": "minecraft:chest", "facing": "north"}},
        {"ghost": {"pos": [bx + 3, by + 1, bz + 3], "block": "nope:block"}},  # unknown block: dropped
        {"walkTo": [x + 500, y, z]},                                         # too far: dropped
        {"teleport": [x, y, z]},                                             # unknown step: dropped
        {"swing": True},
        {"say": "§cRight-click§r with a screwdriver"},
        {"wait": 40},
    ]}
    r = await request({"type": "lesson", "player": "modbot", "lesson": lesson, "reqId": "l1"})
    check("lesson acked with kept/dropped counts and warnings",
          r.get("type") == "ack" and r.get("for") == "lesson" and r.get("id") == "e2e-1" and r.get("steps") == 8
          and r.get("dropped") == 4 and len(r.get("warnings", [])) == 4 and r.get("passTicks", 0) > 40, r)

    pkt, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "lesson")
    body = pkt[1] if pkt else {}
    steps = body.get("steps", [])
    check("ModBot received the normalized lesson packet",
          pkt is not None and body.get("id") == "e2e-1" and len(steps) == 8
          and [s.get("op") for s in steps] == ["walkTo", "lookAt", "hold", "highlight", "ghost", "swing", "say",
                                               "wait"]
          and all(s.get("ticks", 0) >= 1 for s in steps)
          and body.get("anchor") is not None and body.get("dim") == cm.get("dim"), seen)
    check("label text was cleaned (no formatting codes)",
          steps and steps[6].get("text") == "Right-click with a screwdriver", steps[6] if len(steps) > 6 else steps)
    leak, _ = await queue_get_matching(old.packets, lambda p: p[0] == "lesson", timeout=1.0)
    check("only the target player got the lesson", leak is None, leak)

    # ---- stop and status
    r = await request({"type": "lesson_stop", "player": "ModBot", "id": "e2e-1", "reqId": "stop"})
    pkt, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "lesson_stop")
    check("lesson_stop acked and delivered",
          r.get("type") == "ack" and pkt is not None and pkt[1].get("id") == "e2e-1", [r, seen])

    await mod.send_dave("lesson_status", {"id": "e2e-1", "state": "stopped", "reason": "agent"})
    ev = await next_event(lambda m: m.get("type") == "lesson_status")
    check("lesson_status relayed to the agent",
          ev.get("player") == "ModBot" and ev.get("id") == "e2e-1" and ev.get("state") == "stopped"
          and ev.get("reason") == "agent", ev)

    await asyncio.sleep(0.3)
    await mod.send_dave("lesson_status", {"id": "e2e-1", "state": "exploded", "reason": "x"})
    try:
        bogus = await next_event(lambda m: m.get("type") == "lesson_status", timeout=1.5)
    except asyncio.TimeoutError:
        bogus = None
    check("invalid lesson_status is not relayed", bogus is None, bogus)

    for bot in (plain, old, mod):
        await bot.close()
    await ws.close()
    passed = sum(results)
    print(f"Lesson e2e: {passed} passed, {len(results) - passed} failed", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--token")
    p.add_argument("--config", default="run/server/config/davebridge.cfg")
    p.add_argument("--mc-host", default="127.0.0.1")
    p.add_argument("--mc-port", type=int, default=25565)
    p.add_argument("-v", "--verbose", action="store_true")
    sys.exit(asyncio.run(main(p.parse_args())))
