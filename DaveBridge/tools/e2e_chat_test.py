#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["websockets>=14"]
# ///
"""End-to-end test against a LOCAL dev server (./gradlew runServer / runServer21). Never a real server.

Logs two scripted 1.7.10 Forge clients ("bots", offline mode) into the server and drives the agent WebSocket:

  * PlainBot  - completes the FML handshake but has no DaveBridge client half (the "player without the mod"):
                chat "dave, ..." -> triggered chat event; agent say/thinking -> plain <Dave> chat lines.
  * ModBot    - also registers the davebridge channel and speaks its packets (the "client half", scripted):
                client_hello -> client_mod event + server_hello; ask -> chat event with source=client and
                context; chunked (>30000 byte) ask; ask cooldown; say/thinking -> dave_message/thinking packets.

With --commands, PlainBot runs /dave status and /dave reload (make PlainBot an op in run/server/ops.json; its
offline UUID is md5("OfflinePlayer:PlainBot") as a v3 UUID). With --stop it then runs /stop to check that agents
get server_stopping and a clean close.

    uv run tools/e2e_chat_test.py --mc-port 25599 --commands --stop

Needs online-mode=false in run/server/server.properties.
"""

import argparse
import asyncio
import json
import re
import struct
import sys

import websockets

# ---------------------------------------------------------------- wire helpers (1.7.10, protocol 5)


def varint(n):
    out = b""
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def mc_string(s):
    data = s.encode("utf-8")
    return varint(len(data)) + data


async def read_varint(reader):
    result = shift = 0
    while True:
        b = (await reader.readexactly(1))[0]
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result
        shift += 7


def parse_varint(buf, pos):
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def parse_string(buf, pos):
    n, pos = parse_varint(buf, pos)
    return buf[pos:pos + n].decode("utf-8"), pos + n


# Mods the bots claim to have (extra entries are ignored by the server). GTNHLib is listed for dev setups that load
# it; DaveBridge only compiles against it, so a plain runServer has none and fluids fall back to plain text.
MODS = [("mcp", "9.05"), ("FML", "7.99.40.1614"), ("Forge", "10.13.4.1614"), ("gtnhlib", "0.11.48"),
        # BetterQuesting (loaded in DaveBridge's dev runs for the native quest links) must be on clients
        ("betterquesting", "3.8.92-GTNH"), ("questbook", "3.8.92-GTNH"), ("bq_standard", "3.8.92-GTNH"),
        ("cb4bq", "3.8.92-GTNH")]


class Bot:
    """A scripted 1.7.10 Forge client: FML handshake, keep-alives, chat, and optionally the davebridge channel."""

    def __init__(self, host, port, name, client_mod=False, mod_version="0.1.0"):
        self.host, self.port, self.name = host, port, name
        self.client_mod = client_mod
        self.mod_version = mod_version
        self.chat = asyncio.Queue()
        self.packets = asyncio.Queue()
        self.nei_payloads = {}  # payloadId -> raw bytes, from NEI's CACHE_BOOKMARK_DATA packets
        self.sounds = []
        self.hs_state = 1
        self.stream = 0
        self.disconnect_reason = None

    async def send(self, packet_id, payload=b""):
        body = varint(packet_id) + payload
        self.writer.write(varint(len(body)) + body)
        await self.writer.drain()

    async def custom_payload(self, channel, data):
        await self.send(0x17, mc_string(channel) + struct.pack(">h", len(data)) + data)

    async def read_packet(self):
        length = await read_varint(self.reader)
        data = await self.reader.readexactly(length)
        pid, pos = parse_varint(data, 0)
        return pid, data[pos:]

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        await self.send(0x00, varint(5) + mc_string(self.host) + struct.pack(">H", self.port) + varint(2))
        await self.send(0x00, mc_string(self.name))
        while True:
            pid, data = await self.read_packet()
            if pid == 0x02:
                break
            if pid == 0x00:
                raise RuntimeError(f"login refused: {data!r}")
        self.task = asyncio.create_task(self._loop())

    async def _loop(self):
        try:
            while True:
                pid, data = await self.read_packet()
                if pid == 0x00:  # keep-alive
                    await self.send(0x00, data[:4])
                elif pid == 0x02:  # chat
                    text, _ = parse_string(data, 0)
                    await self.chat.put(text)
                elif pid == 0x3F:  # custom payload: string channel, varshort length, data
                    channel, pos = parse_string(data, 0)
                    low = struct.unpack(">H", data[pos:pos + 2])[0]
                    pos += 2
                    if low & 0x8000:
                        low = (low & 0x7FFF) | (data[pos] << 15)
                        pos += 1
                    await self._custom(channel, data[pos:pos + low])
                elif pid == 0x29:  # named sound effect
                    name, _ = parse_string(data, 0)
                    self.sounds.append(name)
                elif pid == 0x40:  # disconnect
                    self.disconnect_reason, _ = parse_string(data, 0)
                    return
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            return

    async def _custom(self, channel, data):
        if channel == "FML|HS":
            await self._handshake(data)
        elif channel == "NEI" and data and data[0] == 25:  # S2C.CACHE_BOOKMARK_DATA: type, utf8 id, NBT
            payload_id, pos = parse_string(data, 1)
            self.nei_payloads[payload_id] = data[pos:]
        elif channel == "davebridge" and data and data[0] == 1:
            pos = 2  # discriminator 1, frame version byte
            kind, pos = parse_string(data, pos)
            _stream, pos = parse_varint(data, pos)
            _index, pos = parse_varint(data, pos)
            total, pos = parse_varint(data, pos)
            n, pos = parse_varint(data, pos)
            assert total == 1, "test bot only handles single-chunk server packets"
            await self.packets.put((kind, json.loads(data[pos:pos + n].decode("utf-8"))))

    async def _handshake(self, data):
        disc = struct.unpack("b", data[:1])[0]
        if self.hs_state == 1 and disc == 0:  # ServerHello
            if self.client_mod:
                await self.custom_payload("REGISTER", b"davebridge")
            await self.custom_payload("FML|HS", bytes([1, 2]))  # ClientHello, protocol 2
            mods = MODS + ([("davebridge", self.mod_version)] if self.client_mod else [])
            body = bytes([2]) + varint(len(mods)) + b"".join(mc_string(k) + mc_string(v) for k, v in mods)
            await self.custom_payload("FML|HS", body)
            self.hs_state = 2
        elif self.hs_state == 2 and disc == 2:  # server ModList
            await self.custom_payload("FML|HS", bytes([0xFF, 2]))
            self.hs_state = 3
        elif self.hs_state == 3 and disc == 3:  # ModIdData
            await self.custom_payload("FML|HS", bytes([0xFF, 3]))
            self.hs_state = 4
        elif self.hs_state in (4, 5) and disc == -1:  # server acks
            await self.custom_payload("FML|HS", bytes([0xFF, self.hs_state]))
            self.hs_state += 1

    async def send_dave(self, kind, obj):
        """Sends a davebridge packet, chunked exactly like the mod does (30000-byte chunks)."""
        payload = json.dumps(obj).encode("utf-8")
        chunks = [payload[i:i + 30000] for i in range(0, len(payload), 30000)] or [b""]
        self.stream += 1
        for i, chunk in enumerate(chunks):
            frame = (bytes([0, 1]) + mc_string(kind) + varint(self.stream) + varint(i) + varint(len(chunks))
                     + varint(len(chunk)) + chunk)
            await self.custom_payload("davebridge", frame)

    async def say(self, text):
        await self.send(0x01, mc_string(text))

    async def close(self):
        self.task.cancel()
        self.writer.close()


def flatten(chat_json):
    """IChatComponent JSON -> plain text."""
    def walk(c):
        if isinstance(c, str):
            return c
        s = c.get("text", "")
        if "translate" in c:
            s += c["translate"] + " " + " ".join(walk(w) for w in c.get("with", []))
        return s + "".join(walk(e) for e in c.get("extra", []))
    try:
        return walk(json.loads(chat_json))
    except ValueError:
        return chat_json


def components(chat_json):
    """All components of a chat JSON message, depth first (siblings and translation args)."""
    out = []

    def walk(c):
        if isinstance(c, str):  # unstyled components serialize as bare strings
            out.append({"text": c})
        elif isinstance(c, dict):
            out.append(c)
            for e in c.get("extra", []):
                walk(e)
            for w in c.get("with", []):
                walk(w)

    walk(json.loads(chat_json))
    return out


def find_component(chat_json, text):
    """The first component whose own text contains `text`."""
    for c in components(chat_json):
        if text in c.get("text", ""):
            return c
    return None


def find_styled(chat_json, text):
    """The first component carrying a click or hover whose subtree's text contains `text` (styles inherit)."""
    for c in components(chat_json):
        if ("clickEvent" in c or "hoverEvent" in c) and text in flatten(json.dumps(c)):
            return c
    return None


async def queue_get_matching(q, pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    seen = []
    while True:
        try:
            item = await asyncio.wait_for(q.get(), max(0.05, end - loop.time()))
        except asyncio.TimeoutError:
            return None, seen
        seen.append(item)
        if pred(item):
            return item, seen

# ---------------------------------------------------------------- test


async def main(a):
    token = a.token
    if not token:
        with open(a.config, encoding="utf-8") as f:
            token = re.search(r"S:authToken=(\S+)", f.read()).group(1)

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        detail = str(detail)
        if len(detail) > 400:
            detail = detail[:400] + "..."
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok or a.verbose else ""),
              flush=True)

    ws = await websockets.connect(a.url)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    hello = json.loads(await ws.recv())
    check("agent authenticated", hello.get("type") == "hello", hello)

    async def next_event(pred, timeout=5.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.05, end - loop.time())))
            if pred(msg):
                return msg

    async def no_event(pred, timeout=1.5):
        try:
            return await next_event(pred, timeout)
        except asyncio.TimeoutError:
            return None

    async def request(msg):
        await ws.send(json.dumps(msg))
        return await next_event(lambda m: m.get("reqId") == msg["reqId"])

    plain = Bot(a.mc_host, a.mc_port, "PlainBot")
    mod = Bot(a.mc_host, a.mc_port, "ModBot", client_mod=True)

    # ---- player without the client half
    await plain.connect()
    join = await next_event(lambda m: m.get("type") == "player_join", timeout=20)
    check("PlainBot: player_join", join.get("player") == "PlainBot" and join.get("hasClientMod") is False, join)

    await asyncio.sleep(0.5)
    await plain.say("Dave, how do I make steel?")
    chat = await next_event(lambda m: m.get("type") == "chat")
    check("PlainBot: triggered chat event",
          chat.get("triggered") is True and chat.get("prompt") == "how do I make steel?"
          and chat.get("source") == "chat" and chat.get("hasClientMod") is False and "id" in chat, chat)

    await plain.say("just chatting, not for dave")
    check("PlainBot: untriggered chat not forwarded", await no_event(lambda m: m.get("type") == "chat") is None)

    r = await request({"type": "thinking", "target": "PlainBot", "reqId": "t1"})
    line, seen = await queue_get_matching(plain.chat, lambda c: "is thinking" in flatten(c))
    check("PlainBot: thinking shown as plain chat", r.get("type") == "ack" and line is not None, [r, seen])

    r = await request({"type": "say", "target": "plainbot", "text": "First line\nSecond line",
                       "replyTo": chat.get("id"), "reqId": "s1"})
    l1, s1 = await queue_get_matching(plain.chat, lambda c: "First line" in flatten(c))
    l2, s2 = await queue_get_matching(plain.chat, lambda c: "Second line" in flatten(c))
    check("PlainBot: targeted say -> two whisper lines",
          r.get("type") == "ack" and l1 and l2 and "commands.message.display.incoming" in l1, [r, s1 + s2])

    # ---- player with the (scripted) client half
    await mod.connect()
    join = await next_event(lambda m: m.get("type") == "player_join" and m.get("player") == "ModBot", timeout=20)
    check("ModBot: player_join", join is not None, join)
    await asyncio.sleep(0.5)
    # "nei": the client half has NEI, so recipe/uses links use its /davebridge nei command (PROTOCOL 2.3)
    await mod.send_dave("client_hello", {"modVersion": "0.1.0", "protocol": 1,
                                         "capabilities": ["render", "ask", "context", "nei"],
                                         "clientEvalAllowed": False})
    cm = await next_event(lambda m: m.get("type") == "client_mod")
    check("ModBot: client_mod event",
          cm.get("player") == "ModBot" and cm.get("hasClientMod") is True and cm.get("capabilities") == [
              "render", "ask", "context", "nei"] and cm.get("clientEvalAllowed") is False, cm)
    sh, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "server_hello")
    check("ModBot: server_hello packet", sh is not None and sh[1].get("botName") == "Dave", seen)

    ctx = {"dim": 0, "heldItem": {"id": "minecraft:stick", "meta": 0, "count": 1}}
    await mod.send_dave("ask", {"text": "dave, what am I holding?", "context": ctx})
    ask = await next_event(lambda m: m.get("type") == "chat" and m.get("player") == "ModBot")
    check("ModBot: ask -> chat event source=client with context",
          ask.get("source") == "client" and ask.get("triggered") is True
          and ask.get("prompt") == "what am I holding?" and ask.get("context") == ctx
          and ask.get("hasClientMod") is True, ask)
    # Since 0.2.0 an Ask-key question is public, shown to everyone like vanilla chat (PROTOCOL 2.3: replies are
    # public, so others must see the question to follow along)
    def is_question(c):
        m = json.loads(c)
        return (m.get("translate") == "chat.type.text" and flatten(c).endswith("dave, what am I holding?")
                and "ModBot" in flatten(json.dumps(m["with"][0])))
    echo, seen = await queue_get_matching(mod.chat, is_question)
    check("ModBot: the asker sees the question as <ModBot> chat", echo is not None, seen)
    shown, seen = await queue_get_matching(plain.chat, is_question)
    check("ModBot: the question is shown to other players too", shown is not None, seen)

    await asyncio.sleep(1.2)  # let the first ask's cooldown pass, then send two asks back to back
    await mod.send_dave("ask", {"text": "first of two"})
    await mod.send_dave("ask", {"text": "too fast"})
    first = await next_event(lambda m: m.get("type") == "chat" and m.get("message") == "first of two")
    slow, seen = await queue_get_matching(mod.chat, lambda c: "Slow down" in flatten(c))
    check("ModBot: ask cooldown enforced", first is not None and slow is not None and await no_event(
        lambda m: m.get("type") == "chat" and m.get("message") == "too fast", 1.0) is None, seen)

    await asyncio.sleep(1.2)
    big = {"blob": "x" * 40000}
    await mod.send_dave("ask", {"text": "big context question", "context": big})
    ask = await next_event(lambda m: m.get("type") == "chat" and m.get("message") == "big context question")
    check("ModBot: 2-chunk ask reassembled; oversized context dropped", "context" not in ask, ask)

    r = await request({"type": "thinking", "target": "ModBot", "reqId": "t2"})
    th, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "thinking")
    check("ModBot: thinking -> thinking packet", th is not None, seen)

    r = await request({"type": "say", "target": "@a", "text": "Hello everyone\nfrom Dave", "replyTo": "abc",
                       "reqId": "s2"})
    mod_line, seen = await queue_get_matching(mod.chat, lambda c: "Hello everyone" in flatten(c))
    check("ModBot: say @a arrives as chat", mod_line is not None and flatten(mod_line).startswith("<Dave> "), seen)
    cleared, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "thinking" and p[1].get("clear"))
    check("ModBot: thinking indicator cleared by the reply", cleared is not None, seen)
    l1, seen = await queue_get_matching(plain.chat, lambda c: "Hello everyone" in flatten(c))
    check("PlainBot: say @a -> plain chat", l1 is not None, seen)

    r = await request({"type": "list_players", "reqId": "p"})
    flags = {p["player"]: p["hasClientMod"] for p in r.get("players", [])}
    check("list_players shows both, with hasClientMod", flags == {"PlainBot": False, "ModBot": True}, r)

    # ---- rich chat: markup rendered per recipient into native pack formats
    markup = ("Smelt {item:minecraft:iron_ingot} or {recipe:minecraft:iron_ingot|see the recipe}, "
              "{url:https://wiki.gtnewhorizons.com|Wiki}\n"
              "Start with {quest:Your First Automation}\n"
              "{chain:minecraft:iron_ingot*4,minecraft:coal*2|Steel kit} {fluid:water} {item:nope:nope}\n"
              "{send:dave, show the full chain|Full chain} {suggest:dave, why |Why?}")
    for bot in (plain, mod):
        bot.sounds.clear()
        for q in (bot.chat, bot.packets):
            while not q.empty():
                q.get_nowait()
    r = await request({"type": "say", "target": "@a", "markup": markup, "reqId": "rich"})
    check("rich say acked with warnings for unknown ids",
          r.get("type") == "ack" and any("nope:nope" in w for w in r.get("warnings", [])), r)

    async def lines_of(bot, n=4):
        got = []
        for _ in range(n):
            line, _ = await queue_get_matching(bot.chat, lambda c: "<" in flatten(c) or "sharequest" in c)
            if line is None:
                break
            got.append(line)
        return got

    for bot, has_mod in ((plain, False), (mod, True)):
        name = bot.name
        lines = await lines_of(bot)
        check(f"{name}: rich message arrives as 4 chat lines", len(lines) == 4, [flatten(x) for x in lines])
        if len(lines) < 4:
            continue
        l1, l2, l3, l4 = lines
        item = find_styled(l1, "Iron Ingot")
        check(f"{name}: item has show_item hover",
              item is not None and item.get("hoverEvent", {}).get("action") == "show_item", item)
        click = (item or {}).get("clickEvent", {})
        payload_id = click.get("value", "").split(" ")[-1]
        check(f"{name}: item click is NEI's native /nei_bookmark with a cached payload",
              click.get("action") == "run_command" and click.get("value", "").startswith("/nei_bookmark ")
              and payload_id in bot.nei_payloads, [click, list(bot.nei_payloads)])
        rec = find_styled(l1, "see the recipe")
        rec_click = (rec or {}).get("clickEvent", {}).get("value", "")
        if has_mod:
            check(f"{name}: recipe link uses the client half's command",
                  rec_click == "/davebridge nei recipe minecraft:iron_ingot:0", rec)
        else:
            check(f"{name}: recipe link falls back to the native bookmark", rec_click.startswith("/nei_bookmark "), rec)
        url = find_styled(l1, "Wiki")
        check(f"{name}: url is open_url", (url or {}).get("clickEvent", {}).get("action") == "open_url", url)
        token = [c for c in components(l2) if "betterquesting.msg.sharequest:" in c.get("text", "")]
        raw = token[0]["text"] if token else ""
        qid = raw.split("betterquesting.msg.sharequest:")[-1]
        check(f"{name}: quest link is BQ's share token (no other links on its line, 24-char id in one text run)",
              len(token) == 1 and len(qid) == 24 and qid.endswith("==") and "clickEvent" not in token[0]
              and "Iron" not in flatten(l2), flatten(l2))
        kit = find_styled(l3, "Steel kit")
        kit_click = (kit or {}).get("clickEvent", {}).get("value", "")
        check(f"{name}: chain is an NEI bookmark group link",
              kit_click.startswith("/nei_bookmark ") and kit_click.split(" ")[-1] in bot.nei_payloads
              and "Iron Ingot" in json.dumps(kit.get("hoverEvent")), kit)
        fluid = [c for c in components(l3) if c.get("gtnhlib_id") == "gtnhlib:ChatComponentFluidName"]
        if fluid:
            check(f"{name}: fluid uses GTNHLib's client-localized name with a details hover",
                  len(fluid) == 1 and "Fluid: water" in json.dumps(fluid[0].get("hoverEvent")), fluid)
        else:
            # no GTNHLib on this server (a plain runServer): the server-localized name, same hover
            plain_fluid = find_styled(l3, "Water")
            check(f"{name}: fluid (no GTNHLib here) is the server-localized name with a details hover",
                  plain_fluid is not None and "Fluid: water" in json.dumps(plain_fluid.get("hoverEvent")), l3)
        check(f"{name}: unknown item degraded to plain text", find_component(l3, "nope:nope") is not None, flatten(l3))
        btn = find_styled(l4, "[Full chain]")
        check(f"{name}: send button runs the chat text",
              (btn or {}).get("clickEvent") == {"action": "run_command", "value": "dave, show the full chain"}, btn)
        why = find_styled(l4, "[Why?]")
        check(f"{name}: suggest button", (why or {}).get("clickEvent", {}).get("action") == "suggest_command", why)
        check(f"{name}: lines start with <Dave>", all(flatten(l).startswith("<Dave> ") for l in (l1, l3, l4)))
        for _ in range(20):  # the sound packet follows the chat lines; give it a moment
            if "random.orb" in bot.sounds:
                break
            await asyncio.sleep(0.1)
        check(f"{name}: reply sound played", "random.orb" in bot.sounds, bot.sounds)

    cleared, seen = await queue_get_matching(mod.packets, lambda p: p[0] == "thinking" and p[1].get("clear"))
    check("ModBot: thinking indicator cleared after the reply", cleared is not None, seen)

    r = await request({"type": "say", "target": "PlainBot", "markup": "Just for you, **{player:PlainBot}**",
                       "reqId": "w"})
    line, seen = await queue_get_matching(plain.chat, lambda c: "incoming" in c)
    check("whisper uses vanilla's 'whispers to you' line, body not italic",
          line is not None and json.loads(line)["extra"][0].get("translate") == "commands.message.display.incoming"
          and json.loads(line)["extra"][0].get("italic") is True
          and "italic" not in json.loads(line)["extra"][1], line or seen)

    r = await request({"type": "say", "target": "@a", "components": [
        {"text": "raw ", "extra": [{"text": "op", "clickEvent": {"action": "run_command", "value": "/op PlainBot"}}]}],
        "reqId": "c"})
    line, seen = await queue_get_matching(plain.chat, lambda c: "raw" in flatten(c))
    check("components escape hatch: disallowed click stripped, warning returned",
          line is not None and "clickEvent" not in json.dumps(json.loads(line))
          and any("/op" in w for w in r.get("warnings", [])), [r, line])

    # ---- client eval (M2): relayed only to opted-in clients that report the "eval" capability
    if a.client_eval:
        r = await request({"type": "client_eval", "player": "ModBot", "script": "1", "reqId": "ce0"})
        check("client_eval: refused for a client that did not opt in",
              r.get("type") == "error" and r.get("code") == "not_opted_in", r)
        r = await request({"type": "client_eval", "player": "PlainBot", "script": "1", "reqId": "ce1"})
        check("client_eval: refused for a player without the client half",
              r.get("type") == "error" and r.get("code") == "not_opted_in", r)
        await mod.send_dave("client_settings", {"clientEvalAllowed": True})
        await next_event(lambda m: m.get("type") == "client_mod" and m.get("clientEvalAllowed") is True)
        r = await request({"type": "client_eval", "player": "ModBot", "script": "1", "reqId": "ce2"})
        check("client_eval: an opted-in 0.1.x client without the eval capability is unsupported",
              r.get("type") == "error" and r.get("code") == "unsupported", r)

        ev = Bot(a.mc_host, a.mc_port, "EvalBot", client_mod=True, mod_version="0.2.0")
        await ev.connect()
        await next_event(lambda m: m.get("type") == "player_join" and m.get("player") == "EvalBot", timeout=20)
        await asyncio.sleep(0.5)
        await ev.send_dave("client_hello", {"modVersion": "0.2.0", "protocol": 1, "clientEvalAllowed": True,
                                            "capabilities": ["render", "ask", "context", "eval"]})
        await next_event(lambda m: m.get("type") == "client_mod" and m.get("player") == "EvalBot")
        await ws.send(json.dumps({"type": "client_eval", "player": "EvalBot", "id": "agent-1",
                                  "script": "mc.thePlayer.getHeldItem()", "params": {"n": 2}, "timeoutMs": 700,
                                  "reqId": "ce3"}))
        req, seen = await queue_get_matching(ev.packets, lambda p: p[0] == "client_eval_request")
        check("client_eval: the opted-in client gets client_eval_request",
              req is not None and req[1].get("script") == "mc.thePlayer.getHeldItem()"
              and req[1].get("timeoutMs") == 700 and req[1].get("params") == {"n": 2}, seen)
        if req:
            # a result with another id, or from another player, is dropped; the right one is relayed
            await mod.send_dave("client_eval_result", {"id": req[1]["id"], "ok": True, "result": "forged"})
            await ev.send_dave("client_eval_result", {"id": "nope", "ok": True, "result": "wrong id"})
            await ev.send_dave("client_eval_result", {"id": req[1]["id"], "ok": True, "result": {"held": None},
                                                      "output": "printed", "ms": 0.5})
            res = await next_event(lambda m: m.get("reqId") == "ce3")
            check("client_eval: only the asked client's result is relayed, with the agent's id",
                  res.get("type") == "client_eval_result" and res.get("id") == "agent-1"
                  and res.get("player") == "EvalBot" and res.get("result") == {"held": None}
                  and res.get("output") == "printed", res)
        await ev.send_dave("client_settings", {"clientEvalAllowed": False})
        await next_event(lambda m: m.get("type") == "client_mod" and m.get("player") == "EvalBot"
                         and m.get("clientEvalAllowed") is False)
        r = await request({"type": "client_eval", "player": "EvalBot", "script": "1", "reqId": "ce4"})
        check("client_eval: opting out mid-session is respected at once",
              r.get("type") == "error" and r.get("code") == "not_opted_in", r)
        await ev.send_dave("client_settings", {"clientEvalAllowed": True})
        await next_event(lambda m: m.get("type") == "client_mod" and m.get("player") == "EvalBot")
        await ws.send(json.dumps({"type": "client_eval", "player": "EvalBot", "script": "1", "reqId": "ce5"}))
        await queue_get_matching(ev.packets, lambda p: p[0] == "client_eval_request")
        await ev.close()
        res = await next_event(lambda m: m.get("reqId") == "ce5", timeout=10)
        check("client_eval: a client that logs out answers disconnected",
              res.get("ok") is False and res.get("errorType") == "disconnected", res)

    # ---- /dave command, run by PlainBot (needs PlainBot in the dev server's ops.json)
    if a.commands:
        for cmd, needle, name in (("/dave status", "Socket: listening", "/dave status"),
                                  ("/dave reload", "config reloaded", "/dave reload")):
            await plain.say(cmd)
            line, seen = await queue_get_matching(plain.chat, lambda c: needle in flatten(c))
            await asyncio.sleep(0.3)
            while not plain.chat.empty():
                seen.append(plain.chat.get_nowait())
            print(f"--- {cmd}\n" + "\n".join(flatten(c) for c in seen))
            check(name + " (as op)", line is not None, seen)
        await mod.say("/dave status")
        denied, seen = await queue_get_matching(mod.chat, lambda c: "permission" in flatten(c).lower()
                                                or "commands.generic" in flatten(c))
        check("/dave denied for non-op", denied is not None, seen)

    await plain.close()
    await mod.close()
    leaves = set()
    for _ in range(2):
        ev = await next_event(lambda m: m.get("type") == "player_leave", timeout=10)
        leaves.add(ev.get("player"))
    check("player_leave events", leaves == {"PlainBot", "ModBot"}, leaves)

    if a.stop:
        # SIGTERM-free shutdown: an op runs /stop, which takes the normal FMLServerStoppingEvent path
        stopper = Bot(a.mc_host, a.mc_port, "PlainBot")
        await stopper.connect()
        await next_event(lambda m: m.get("type") == "player_join", timeout=20)
        await asyncio.sleep(0.5)
        await stopper.say("/stop")
        stopping = await no_event(lambda m: m.get("type") == "server_stopping", timeout=30)
        check("server_stopping event on /stop", stopping is not None, stopping)
        try:
            await asyncio.wait_for(ws.wait_closed(), 15)
            check("socket closed by server on /stop", True, ws.close_code)
        except asyncio.TimeoutError:
            check("socket closed by server on /stop", False)
    else:
        await ws.close()

    failed = results.count(False)
    print(f"E2E: {len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--token")
    p.add_argument("--config", default="run/server/config/davebridge.cfg")
    p.add_argument("--mc-host", default="127.0.0.1")
    p.add_argument("--mc-port", type=int, default=25565)
    p.add_argument("--commands", action="store_true", help="test /dave as PlainBot (must be op on the dev server)")
    p.add_argument("--client-eval", action="store_true", help="test the client_eval relay (DaveBridge 0.2.0+)")
    p.add_argument("--stop", action="store_true", help="have PlainBot (op) run /stop at the end")
    p.add_argument("-v", "--verbose", action="store_true")
    sys.exit(asyncio.run(main(p.parse_args())))
