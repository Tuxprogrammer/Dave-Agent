"""The daemon's local RPC socket: how the `bridge` MCP server (dave/bridge/server.py) reaches DaveBridge.

Claude starts the MCP server as its own stdio child, so it cannot share the daemon's WebSocket. Instead the daemon
listens on a unix socket in its run directory (`<run>/bridge.sock`, mode 0600, so only the daemon's user can
connect), and the MCP server sends each tool call there as one JSON line:

    -> {"id": 1, "op": "eval", "args": {"script": "...", "mode": "read"}}
    <- {"id": 1, "ok": true, "result": {...the bridge's reply...}}
    <- {"id": 1, "ok": false, "error": "bridge not connected"}

The daemon fills in what Claude must not choose: the asking player of the turn in flight (for confirms and the
`player` binding). Standard library only.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from dave.bridge.queries import QueryError, Queries

log = logging.getLogger("dave")

MAX_LINE = 1024 * 1024


class RpcError(Exception):
    pass


def socket_path(cfg):
    from dave import config
    return config.bridge_socket(cfg)


class BridgeRPC:
    def __init__(self, daemon, path, queries):
        self.daemon = daemon
        self.path = Path(path)
        self.queries = queries if isinstance(queries, Queries) else Queries(queries)
        self.server = None
        self._tasks = set()

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()                    # a stale socket from a previous run
        except FileNotFoundError:
            pass
        old = os.umask(0o177)                     # created 0600 from the start, not chmod-ed afterwards
        try:
            self.server = await asyncio.start_unix_server(self._client, path=str(self.path), limit=MAX_LINE)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        log.info("bridge RPC listening on %s", self.path)

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    async def _client(self, reader, writer):
        lock = asyncio.Lock()
        mine = set()
        try:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:                # over MAX_LINE
                    break
                if not line:
                    break
                task = asyncio.create_task(self._serve(line, writer, lock))
                for s in (mine, self._tasks):
                    s.add(task)
                    task.add_done_callback(s.discard)
            if mine:                              # the caller half-closed: finish its calls, then hang up
                await asyncio.gather(*mine, return_exceptions=True)
        finally:
            writer.close()

    async def _serve(self, line, writer, lock):
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            result = await self.handle(req.get("op"), req.get("args") or {})
            reply = {"id": rid, "ok": True, "result": result}
        except (RpcError, QueryError) as e:
            reply = {"id": rid, "ok": False, "error": str(e)}
        except asyncio.TimeoutError:
            reply = {"id": rid, "ok": False, "error": "DaveBridge did not answer in time"}
        except Exception as e:                    # noqa: BLE001 - every failure goes back to the caller
            log.exception("bridge RPC call failed")
            reply = {"id": rid, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        async with lock:
            try:
                writer.write((json.dumps(reply) + "\n").encode("utf-8"))
                await writer.drain()
            except (ConnectionError, OSError):
                pass

    # ---- ops

    def asker(self):
        turn = self.daemon.in_flight
        return turn.player if turn else None

    async def request(self, msg, timeout):
        from dave.daemon.main import BridgeDown   # late import: main imports this module
        bridge = self.daemon.bridge
        if not bridge.ready.is_set():
            raise RpcError("DaveBridge is not connected right now")
        accepts = (bridge.hello or {}).get("accepts") or []
        if msg["type"] not in accepts:
            raise RpcError("this server's DaveBridge does not support %s (it needs DaveBridge 0.2.0 or newer)"
                           % msg["type"])
        try:
            reply = await bridge.request(msg, timeout=timeout)
        except BridgeDown as e:
            raise RpcError("DaveBridge connection lost: %s" % e)
        if reply.get("type") == "error":
            raise RpcError("%s: %s" % (reply.get("code"), reply.get("message")))
        reply.pop("reqId", None)
        reply.pop("ts", None)
        return reply

    async def handle(self, op, a):
        if op == "eval":
            return await self.eval(a)
        if op == "describe":
            msg = {"type": "describe", "target": a.get("target") or "looking"}
            for k_in, k_out in (("x", "x"), ("y", "y"), ("z", "z"), ("dim", "dim"), ("entity_id", "entityId"),
                                ("reach", "reach")):
                if a.get(k_in) is not None:
                    msg[k_out] = a[k_in]
            player = a.get("player") or self.asker()
            if player:
                msg["player"] = player
            return await self.request(msg, timeout=30)
        if op == "say":
            if not a.get("markup"):
                raise RpcError("markup is required")
            return await self.request({"type": "say", "target": a.get("target") or "@a", "markup": a["markup"]},
                                      timeout=30)
        if op == "list_players":
            return await self.request({"type": "list_players"}, timeout=30)
        if op == "lesson":
            player = a.get("player") or self.asker()
            if not player or not isinstance(a.get("lesson"), dict):
                raise RpcError("lesson needs a player (default: the asker) and a lesson object with steps")
            return await self.request({"type": "lesson", "player": player, "lesson": a["lesson"]}, timeout=15)
        if op == "lesson_stop":
            player = a.get("player") or self.asker()
            if not player:
                raise RpcError("lesson_stop needs a player (default: the asker)")
            msg = {"type": "lesson_stop", "player": player}
            if a.get("id"):
                msg["id"] = str(a["id"])
            return await self.request(msg, timeout=10)
        if op == "query_list":
            return {"queries": [{k: q.get(k) for k in ("name", "description", "mode", "side", "params", "origin")}
                                for q in self.queries.list()]}
        if op == "query_get":
            q = self.queries.get(a.get("name"))
            return {k: q.get(k) for k in ("name", "description", "mode", "side", "params", "origin", "script")}
        if op == "query_save":
            return await asyncio.to_thread(
                self.queries.save, a.get("name"), a.get("description"), a.get("script"), a.get("mode") or "read",
                a.get("side") or "server", a.get("params_doc"), a.get("timeout_ms"), bool(a.get("replace")))
        if op == "query_run":
            q = await asyncio.to_thread(self.queries.get, a.get("name"))
            args = {"script": q["script"], "mode": q["mode"], "side": q["side"], "params": a.get("params") or {},
                    "timeout_ms": a.get("timeout_ms") or q.get("timeout_ms"), "id": "q:" + q["name"],
                    "summary": a.get("summary") or q["description"], "player": a.get("player")}
            reply = await self.eval(args)
            reply["query"] = q["name"]
            return reply
        raise RpcError("unknown op %r" % (op,))

    async def eval(self, a):
        script = a.get("script")
        if not isinstance(script, str) or not script.strip():
            raise RpcError("script is required")
        side = a.get("side") or "server"
        mode = a.get("mode") or "read"
        player = a.get("player") or self.asker()
        timeout_ms = a.get("timeout_ms")
        msg = {"script": script, "params": a.get("params") or {}}
        if a.get("id"):
            msg["id"] = str(a["id"])
        if timeout_ms:
            msg["timeoutMs"] = int(timeout_ms)
        if side == "client":
            if not player:
                raise RpcError("client eval needs a player (the asker of this turn)")
            msg.update(type="client_eval", player=player, mode="groovy")
            wait = 60 + (int(timeout_ms or 0) // 1000)
        elif side == "server":
            msg.update(type="eval", mode=mode)
            if player:
                msg["player"] = player
            if mode == "write":
                if not player:
                    raise RpcError("a write needs the asking player, who confirms it in chat")
                if not (a.get("summary") or "").strip():
                    raise RpcError("a write needs summary: one line telling the player what will change")
                msg["summary"] = a["summary"]
                confirm = int(a.get("confirm_timeout_seconds") or 120)
                msg["confirmTimeoutSeconds"] = confirm
                wait = confirm + 60
            else:
                wait = 60 + (int(timeout_ms or 0) // 1000)
        else:
            raise RpcError("side must be server or client")
        return await self.request(msg, timeout=wait)
