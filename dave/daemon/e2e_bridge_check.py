"""End-to-end check of the bridge tools against a LOCAL test server, with NO model calls.

Runs the real daemon (dave/daemon/main.py) with the fake claude (fake_claude.py) against a real DaveBridge, then
drives the real `bridge` MCP server (dave/bridge/server.py) over stdio exactly as Claude would: tools/list, eval,
describe, query_list, query_run gt-recipes, and a write that a console /dave confirm (RCON) lets through. Finally a
console /dave ask goes through the daemon's chat loop to the fake claude and back as a say.

    python3 -I dave/daemon/e2e_bridge_check.py --davebridge-cfg <server>/config/davebridge.cfg \
        --rcon-password-file <file> [--rcon-port 25575] [--url ws://127.0.0.1:25580] [--gt]

Everything it writes (memory, run dir, logs) goes to a temporary directory. Secrets are read from files and passed
in the environment, never printed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "DaveBridge" / "tools"))
from eval_check import Rcon  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % str(detail)[:400]) if detail else ""), flush=True)


class Mcp:
    def __init__(self, socket_path):
        self.proc = subprocess.Popen([sys.executable, "-I", str(ROOT / "dave" / "bridge" / "server.py")],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env={"DAVE_BRIDGE_SOCKET": str(socket_path), "PATH": os.environ["PATH"]},
                                     text=True)
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        while True:
            reply = json.loads(self.proc.stdout.readline())
            if reply.get("id") == self.n:
                return reply

    def call(self, _tool, **args):
        res = self.rpc("tools/call", {"name": _tool, "arguments": args})["result"]
        text = res["content"][0]["text"]
        try:
            return res["isError"], json.loads(text)
        except ValueError:
            return res["isError"], text

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(10)


def token_from(cfg):
    for line in Path(cfg).read_text().splitlines():
        m = re.match(r"\s*S:authToken=(.*)$", line)
        if m:
            return m.group(1).strip()
    raise SystemExit("no authToken in " + cfg)


def main(a):
    tmp = Path(tempfile.mkdtemp(prefix="dave-e2e-"))
    work = tmp / "work"                                  # private parent: dave_cmd refuses a cwd under /tmp itself
    shutil.copytree(ROOT / "data" / "memory", tmp / "memory")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "HOME", "USER", "TMPDIR")}
    env.update({"DAVE_WORKDIR": str(work), "DAVE_RUN_DIR": str(tmp / "run"), "DAVE_CLAUDE_HOME": str(tmp / "home"),
                "DAVE_MEMORY_DIR": str(tmp / "memory"), "DAVE_LOG_DIR": str(tmp / "logs"),
                "DAVE_CLAUDE_BIN": str(HERE / "fake_claude.py"), "CLAUDE_CODE_OAUTH_TOKEN": "fake-token-no-model-calls",
                "DAVE_BRIDGE_TOKEN": token_from(a.davebridge_cfg), "DAVE_BRIDGE_URL": a.url,
                "DAVE_CONTAINER": "1"})
    (HERE / "fake_claude.py").chmod(0o755)
    daemon = subprocess.Popen([sys.executable, "-I", str(HERE / "main.py")], env=env, stdout=subprocess.DEVNULL,
                              stderr=open(tmp / "daemon.stderr", "w"))
    rcon = Rcon("127.0.0.1", a.rcon_port, Path(a.rcon_password_file).read_text().strip())
    mcp = None
    try:
        sys.path.insert(0, str(ROOT))
        os.environ.update({k: env[k] for k in ("DAVE_RUN_DIR",)})
        from dave import config
        sock = config.bridge_socket(config.load())
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.2)
        check("daemon opened its RPC socket (0600)", sock.exists() and (sock.stat().st_mode & 0o777) == 0o600, sock)
        time.sleep(2)                                    # bridge connect
        mcp = Mcp(sock)
        tools = {t["name"] for t in mcp.rpc("tools/list")["result"]["tools"]}
        check("MCP server lists the bridge tools", {"eval", "describe", "query_run", "query_save"} <= tools, tools)
        err, players = mcp.call("list_players")
        check("list_players through the daemon", not err and players.get("type") == "players", players)
        err, r = mcp.call("eval", script="[world.provider.dimensionId, server.getMOTD()]")
        check("eval read through MCP -> daemon -> DaveBridge", not err and r.get("ok") and r["result"][0] == 0, r)
        err, r = mcp.call("eval", script="while (true) {}", timeout_ms=200)
        check("timeout comes back as a tool result", r.get("errorType") == "timeout", r)
        err, r = mcp.call("describe", target="block", x=0, y=0, z=0, dim=0)
        check("describe through MCP", not err and r.get("type") == "description", r)
        err, r = mcp.call("query_list")
        check("query_list shows the starters", not err and any(q["name"] == "gt-recipes" for q in r["queries"]), r)
        if a.gt:
            err, r = mcp.call("query_run", name="gt-recipes", params={"item": "gregtech:gt.metaitem.03:32042",
                                                                      "map": "engraver", "limit": 1})
            rec = ((r.get("result") or {}).get("recipes") or [{}])[0] if isinstance(r, dict) else {}
            check("query_run gt-recipes (NOR wafer, laser engraver) live", not err and rec.get("eut"),
                  {k: rec.get(k) for k in ("map", "eut", "tier", "ticks", "inputs", "special")})
        # a write: the call waits until the console confirms it
        import threading
        out = {}
        t = threading.Thread(target=lambda: out.update(r=mcp.call(
            "eval", script="'would change something here'", mode="write", player="Gym",
            summary="E2E check: a write that changes nothing")))
        t.start()
        token = None
        for _ in range(50):
            m = re.search(r"\b([0-9a-f]{6,12})\s+Gym", rcon.command("dave pending"))
            if m:
                token = m.group(1)
                break
            time.sleep(0.2)
        check("the write waits for a confirm (/dave pending)", token, token)
        if token:
            rcon.command("dave confirm " + token)
        t.join(30)
        err, r = out.get("r", (True, None))
        check("console confirm completes the MCP call", not err and r.get("confirmed") and r.get("ok"), r)
        # the chat loop: console ask -> daemon -> fake claude -> say
        rcon.command("dave ask Gym dave, e2e check, are you there?")
        turns = tmp / "logs" / "turns.jsonl"
        row = None
        for _ in range(100):
            if turns.exists() and turns.read_text().strip():
                row = json.loads(turns.read_text().splitlines()[-1])
                break
            time.sleep(0.2)
        check("/dave ask went through the daemon and back as a reply", row and row.get("player") == "Gym"
              and row.get("reply") == "hello Gym", row)
    finally:
        if mcp:
            mcp.close()
        daemon.terminate()
        try:
            daemon.wait(20)
        except subprocess.TimeoutExpired:
            daemon.kill()
        print("daemon log tail:\n" + "\n".join((tmp / "logs" / "daemon.log").read_text().splitlines()[-6:])
              if (tmp / "logs" / "daemon.log").exists() else "(no daemon log)")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    print("\nChecks: %d passed, %d failed" % (RESULTS.count(True), RESULTS.count(False)))
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--davebridge-cfg", required=True)
    p.add_argument("--rcon-password-file", required=True)
    p.add_argument("--rcon-port", type=int, default=25575)
    p.add_argument("--url", default="ws://127.0.0.1:25580")
    p.add_argument("--gt", action="store_true")
    sys.exit(main(p.parse_args()))
