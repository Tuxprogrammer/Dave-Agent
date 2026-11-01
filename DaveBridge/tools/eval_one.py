#!/usr/bin/env python3
"""Send one eval (or any JSON request) to a LOCAL DaveBridge and print the reply. Standard library only.

    python3 -I DaveBridge/tools/eval_one.py --config run/server/config/davebridge.cfg 'world.getTotalWorldTime()'
    python3 -I DaveBridge/tools/eval_one.py --config ... --file dave/queries/gt-recipes.groovy --params '{"item":"..."}'
    python3 -I DaveBridge/tools/eval_one.py --config ... --raw '{"type":"describe","target":"block","x":0,"y":64,"z":0}'
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dave.daemon.ws import WebSocket  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_check import read_token  # noqa: E402


async def main(a):
    ws = await WebSocket.connect(a.url, headers={"Authorization": "Bearer " + read_token(a.config)})
    json.loads(await ws.recv())
    if a.raw:
        msg = json.loads(a.raw)
    else:
        script = Path(a.file).read_text() if a.file else a.script
        msg = {"type": "eval", "script": script, "timeoutMs": a.timeout}
        if a.params:
            msg["params"] = json.loads(a.params)
    msg["reqId"] = 1
    await ws.send(json.dumps(msg))
    while True:
        reply = json.loads(await asyncio.wait_for(ws.recv(), 120))
        if reply.get("reqId") == 1:
            print(json.dumps(reply, indent=1)[: a.max])
            break
    await ws.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("script", nargs="?")
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--config", required=True)
    p.add_argument("--file")
    p.add_argument("--params")
    p.add_argument("--raw")
    p.add_argument("--timeout", type=int, default=5000)
    p.add_argument("--max", type=int, default=6000)
    asyncio.run(main(p.parse_args()))
