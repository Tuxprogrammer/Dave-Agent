#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["websockets>=14"]
# ///
"""Tiny test client for the DaveBridge agent WebSocket.

Run without installing anything system-wide:

    uv run tools/dave_client.py --config run/server/config/davebridge.cfg selftest
    uv run tools/dave_client.py --token <token> listen
    uv run tools/dave_client.py --token <token> send '{"type":"say","target":"@a","text":"hello"}'

Modes:
  selftest  exercise auth, ping, errors, list_players, say, thinking; exit 1 on any failure
  listen    authenticate and print every event (chat, player_join, ...) until Ctrl-C
  send      authenticate, send each JSON argument (or stdin lines), print replies for a few seconds
"""

import argparse
import asyncio
import json
import re
import sys

import websockets


def read_token(config_path):
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*S:authToken=(.*)$", line)
            if m:
                return m.group(1).strip()
    raise SystemExit(f"authToken not found in {config_path}")


async def recv_json(ws, timeout=5.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def recv_until(ws, predicate, timeout=5.0):
    """Receive messages until one matches; unrelated events (chat, joins) are skipped."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        msg = await recv_json(ws, max(0.1, deadline - loop.time()))
        if predicate(msg):
            return msg


async def connect_authed(url, token, header=False):
    if header:
        ws = await websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"})
    else:
        ws = await websockets.connect(url)
        await ws.send(json.dumps({"type": "auth", "token": token}))
    hello = await recv_json(ws)
    if hello.get("type") != "hello":
        raise RuntimeError(f"expected hello, got {hello}")
    return ws, hello


async def selftest(url, token):
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""))

    # 1. unauthenticated traffic is rejected and the connection dropped
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        msg = await recv_json(ws)
        check("unauthenticated ping -> error unauthorized", msg.get("code") == "unauthorized", msg)
        try:
            await asyncio.wait_for(ws.recv(), 3)
            closed = False
        except websockets.ConnectionClosed:
            closed = True
        check("unauthenticated connection closed", closed)

    # 2. wrong token
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": "wrong"}))
        msg = await recv_json(ws)
        check("bad token -> error unauthorized", msg.get("code") == "unauthorized", msg)

    # 3. header auth
    try:
        ws, hello = await connect_authed(url, token, header=True)
        check("Authorization header auth -> hello", True, f"accepts={hello.get('accepts')}")
        await ws.close()
    except Exception as e:  # noqa: BLE001
        check("Authorization header auth -> hello", False, repr(e))

    # 4. message auth and the request types
    ws, hello = await connect_authed(url, token)
    check("auth message -> hello", hello.get("protocol") == 1, f"version={hello.get('version')}")
    try:
        await ws.send(json.dumps({"type": "ping", "reqId": 1}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == 1)
        check("ping -> pong", msg.get("type") == "pong", msg)

        await ws.send("{not json")
        msg = await recv_until(ws, lambda m: m.get("type") == "error")
        check("malformed JSON -> error bad_json", msg.get("code") == "bad_json", msg)

        await ws.send(json.dumps({"type": "nope", "reqId": "u"}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == "u")
        check("unknown type -> error unknown_type", msg.get("code") == "unknown_type", msg)

        await ws.send(json.dumps({"type": "say", "reqId": "m"}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == "m")
        check("say without text -> error bad_request", msg.get("code") == "bad_request", msg)

        await ws.send(json.dumps({"type": "list_players", "reqId": 2}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == 2)
        check("list_players -> players", msg.get("type") == "players", msg)

        await ws.send(json.dumps({"type": "thinking", "target": "@a", "reqId": 3}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == 3)
        check("thinking -> ack", msg.get("type") == "ack" and msg.get("ok") is True, msg)

        long_line = "word " * 120
        text = "selftest line one\nselftest line two\n" + long_line
        await ws.send(json.dumps({"type": "say", "target": "@a", "text": text, "replyTo": "x", "reqId": 4}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == 4)
        check("say @a (multi-line, long) -> ack", msg.get("type") == "ack", msg)

        await ws.send(json.dumps({"type": "say", "target": "NoSuchPlayer", "text": "hi", "reqId": 5}))
        msg = await recv_until(ws, lambda m: m.get("reqId") == 5)
        # since 0.2.0: an absent target is not an error (the asker may have left, or be a /dave ask test name)
        check("say to offline player -> ack, 0 recipients, warning",
              msg.get("type") == "ack" and msg.get("recipients") == 0
              and any("not online" in w for w in msg.get("warnings", [])), msg)
    finally:
        await ws.close()

    failed = results.count(False)
    print(f"Selftest: {len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


async def listen(url, token, header):
    ws, hello = await connect_authed(url, token, header)
    print(json.dumps(hello))
    async for raw in ws:
        print(raw, flush=True)


async def send(url, token, header, messages, wait):
    ws, hello = await connect_authed(url, token, header)
    print(json.dumps(hello))
    for m in messages:
        await ws.send(m)
    try:
        while True:
            print(json.dumps(await recv_json(ws, wait)), flush=True)
    except asyncio.TimeoutError:
        pass
    await ws.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--token", help="auth token (or use --config)")
    p.add_argument("--config", help="path to davebridge.cfg to read the token from")
    p.add_argument("--header", action="store_true", help="authenticate with an Authorization header")
    p.add_argument("--wait", type=float, default=3.0, help="send mode: seconds to wait for replies")
    p.add_argument("mode", choices=["selftest", "listen", "send"])
    p.add_argument("messages", nargs="*", help="send mode: JSON messages (default: read lines from stdin)")
    a = p.parse_args()

    token = a.token or (read_token(a.config) if a.config else None)
    if not token:
        p.error("--token or --config is required")

    if a.mode == "selftest":
        sys.exit(asyncio.run(selftest(a.url, token)))
    elif a.mode == "listen":
        try:
            asyncio.run(listen(a.url, token, a.header))
        except KeyboardInterrupt:
            pass
    else:
        msgs = a.messages or [line.strip() for line in sys.stdin if line.strip()]
        asyncio.run(send(a.url, token, a.header, msgs, a.wait))


if __name__ == "__main__":
    main()
