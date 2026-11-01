"""Builds the exact `claude` command and environment for Dave's long-lived process. Standard library only.

    python3 -I dave/launch/dave_cmd.py --print    show the command, env (secrets redacted) and rendered files
    python3 -I dave/launch/dave_cmd.py --json     the same as JSON, for scripts (secrets redacted)
    python3 -I dave/launch/dave_cmd.py --probe    start the configured process WITHOUT credentials: no model call,
                                                  but its init event shows the real tools, MCP servers, agents
    python3 -I dave/launch/dave_cmd.py --smoke    ONE short real call through the configured process, only if
                                                  CLAUDE_CODE_OAUTH_TOKEN is available (uses the subscription)

The daemon imports build() and runs the result itself. This script never starts the daemon loop.
Every flag here was checked against `claude --help` for Claude Code 2.1.316; see docs/plans/dave-core.md.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dave import config  # noqa: E402

HERE = Path(__file__).resolve().parent
BUILTIN_TOOLS = "Read,Grep,Glob,WebFetch,Agent"   # Agent only for recipe-planner (settings deny every other type)
PLANNER = "recipe-planner"
# Only these variables are copied from the caller's environment; everything else (ANTHROPIC_API_KEY,
# OPENROUTER_API_KEY, cloud credentials, the owner's shell settings) never reaches Dave's process.
ENV_ALLOW = ("PATH", "LANG", "LANGUAGE", "TZ", "USER", "LOGNAME", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
             "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/CLAUDE.md", ".claude/AGENTS.md")
MARKUP_FALLBACK = (
    "Dave markup is not available yet. Until it is, reply in plain text: no Markdown and no markup. Name items "
    "and quests exactly as they appear in game, and offer follow-ups as a short question (\"Want the full "
    "chain?\") instead of buttons."
)


def warn(msg):
    print("[dave_cmd] " + msg, file=sys.stderr)


# ---------------------------------------------------------------- system prompt

def markup_spec(path):
    """The paste-ready Dave markup spec (DaveBridge/docs/dave-markup.md), or None when it isn't there.

    The whole file is included, minus its top-level "# " title (SOUL.md has its own heading for the slot). If the
    file carries <!-- dave-prompt:begin --> / <!-- dave-prompt:end --> markers, only the text between them is used.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"<!--\s*dave-prompt:begin\s*-->(.*?)<!--\s*dave-prompt:end\s*-->", text, re.S)
    if m:
        text = m.group(1)
    text = re.sub(r"\A\s*# [^\n]*\n", "", text)
    return text.strip() or None


def strip_comments(text):
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def assemble_prompt(cfg):
    """SOUL.md with comments stripped and includes inlined. Returns (text, notes)."""
    notes = []
    soul = Path(cfg["prompt"]["soul"]).read_text(encoding="utf-8")
    includes = {"davebridge markup spec": lambda: markup_spec(cfg["prompt"]["markup_spec"])}

    def include(m):
        name = m.group(1).strip()
        fn = includes.get(name.lower())
        body = fn() if fn else None
        if body is None:
            notes.append("include %r not available; using the plain-text fallback" % name)
            return MARKUP_FALLBACK if fn else ""
        notes.append("included %r (%d chars)" % (name, len(body)))
        return body

    return strip_comments(re.sub(r"<!--\s*include:\s*(.*?)\s*-->", include, soul)), notes


# ---------------------------------------------------------------- isolation checks

def instruction_files_above(workdir):
    """CLAUDE.md / AGENTS.md files and .claude/ dirs in workdir or any parent.

    Claude Code's discovery walk reads these as project files (a .claude/ dir also brings skills, agents and
    commands; with a cwd under the owner's home, ~/.claude/skills showed up as "project" skills in testing).
    """
    found = []
    for d in [workdir, *workdir.parents]:
        for name in INSTRUCTION_FILES:
            if (d / name).is_file():
                found.append(d / name)
        if (d / ".claude").is_dir():
            found.append(d / ".claude")
    return list(dict.fromkeys(found))


def problems(cfg, workdir):
    out = []
    for root in {cfg["app"], cfg["root"]}:
        if workdir == root or root in workdir.parents:
            out.append("workdir %s is inside %s; Dave would walk up into the developer CLAUDE.md" % (workdir, root))
    for d in (workdir, workdir.parent):
        if d.exists() and d.stat().st_uid != os.getuid():
            out.append("%s is owned by another user; Dave's cwd must be private" % d)
    for f in instruction_files_above(workdir):
        out.append("instruction file or .claude dir in or above Dave's workdir: %s" % f)
    for key in ("gtnh_src", "corpus"):          # Claude Code reads <add-dir>/.claude/settings*.json
        if (cfg["paths"][key] / ".claude").exists():
            out.append("%s has a .claude/ directory, which would load as settings" % cfg["paths"][key])
    return out


# ---------------------------------------------------------------- render

def _render(template_path, values):
    raw = Template(Path(template_path).read_text(encoding="utf-8"))
    data = json.loads(raw.substitute({k: json.dumps(str(v))[1:-1] for k, v in values.items()}))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def openrouter_key_file(cfg, run_dir):
    """A file the gtnh-search server can read the key from, so the key itself is never in Claude's env.

    A docker secret / OPENROUTER_API_KEY_FILE is passed through as is. A key from the environment or from the dev
    .env is written to <run>/secrets/ (0600, runtime only): a _FILE must hold the bare key, and the .env file holds
    `NAME=value` lines (passing it as the file made every search call fail with 401).
    """
    path = config.secret_file(cfg, "openrouter_api_key")
    if path:
        return path, "file"
    value, source = config.secret(cfg, "openrouter_api_key")
    if not value:
        return None, None
    dest = run_dir / "secrets" / "openrouter_api_key"
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dest.parent, 0o700)
    _write(dest, value + "\n", 0o600)
    return dest, "written from " + source.split(" ", 1)[0] + (" .env" if source.startswith("dev") else "")


def build(cfg=None, mode="stream", prompt=None, write=True, resume=None):
    """Returns a dict: argv, env (with real secrets), cwd, files, notes, problems, redacted (env for display).

    mode "stream": the long-lived stream-json process for the daemon.
    mode "smoke": one non-streaming call with `prompt` (text in, stream-json out so the init event is visible).
    resume: a session id to continue (the daemon uses it after a crash; the session keeps its old system prompt).
    """
    cfg = cfg or config.load()
    paths, notes = cfg["paths"], []
    run_dir, home, workdir = paths["run"], paths["claude_home"], paths["workdir"]
    if write:
        for d in (run_dir, home, workdir):
            d.mkdir(parents=True, exist_ok=True)
        for d in (run_dir, home, workdir):
            os.chmod(d, 0o700)

    prompt_text, prompt_notes = assemble_prompt(cfg)
    notes += prompt_notes
    key_file, key_note = openrouter_key_file(cfg, run_dir) if write else (None, None)
    values = {
        "PYTHON": sys.executable, "APP": cfg["app"], "ROOT": cfg["root"], "CONFIG": cfg["config_path"],
        "GTNH_SRC": paths["gtnh_src"], "CORPUS": paths["corpus"], "INDEX": paths["index"],
        "MEMORY": paths["memory"], "PACK": cfg["pack"]["version"], "OPENROUTER_KEY_FILE": key_file or "",
        "SEARCH_STATE": cfg["search"]["state"],
        "RECIPES": paths.get("recipes") or cfg["root"] / "data" / "recipes.sqlite",
        "PLANNER_MODEL": cfg["model"]["planner"],
        "PLANNER_PROMPT": strip_comments(Path(cfg["prompt"]["planner"]).read_text(encoding="utf-8")),
    }
    settings = _render(HERE / "settings.json", values)
    mcp = _render(HERE / "mcp.json", values)
    agents = _render(HERE / "agents.json", values)
    for name, server in list(mcp["mcpServers"].items()):
        script = next((a for a in server.get("args", []) if a.endswith(".py")), None)
        if script and not Path(script).is_file():
            del mcp["mcpServers"][name]
            notes.append("MCP server %s left out: %s does not exist yet" % (name, script))
    for name, agent in agents.items():           # an agent may only name tools of registered MCP servers
        keep = [t for t in agent["tools"] if not t.startswith("mcp__") or t.split("__")[1] in mcp["mcpServers"]]
        if len(keep) != len(agent["tools"]):
            notes.append("agent %s: tools of unregistered MCP servers left out (%s)" % (
                name, ", ".join(sorted({t.split("__")[1] for t in agent["tools"] if t not in keep}))))
        agent["tools"] = keep
    if "gtnh-search" in mcp["mcpServers"]:
        notes.append("gtnh-search key file: %s" % ((str(key_file) + " (" + key_note + ")") if key_file else
                                                    "none found; search embeddings will be unavailable"))
    files = {"system_prompt": run_dir / "system-prompt.md", "settings": run_dir / "settings.json",
             "mcp": run_dir / "mcp.json", "agents": run_dir / "agents.json"}
    if write:
        _write(files["system_prompt"], prompt_text)
        _write(files["settings"], json.dumps(settings, indent=2) + "\n")
        _write(files["mcp"], json.dumps(mcp, indent=2) + "\n")
        _write(files["agents"], json.dumps(agents, indent=2) + "\n")

    claude_bin = cfg.get("claude", {}).get("bin", "claude")
    claude_bin = shutil.which(claude_bin) or claude_bin
    model = cfg["model"]
    argv = [claude_bin, "-p"]
    if mode == "stream":
        argv += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        if resume:
            argv += ["--resume", resume]
    else:
        argv += ["--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    argv += ["--model", model["name"]]
    if model.get("fallback"):
        argv += ["--fallback-model", model["fallback"]]
    if model.get("effort"):
        argv += ["--effort", model["effort"]]
    argv += [
        "--system-prompt-file", str(files["system_prompt"]), "--system-prompt-snapshot", "on",
        "--settings", str(files["settings"]), "--setting-sources", "",
        "--mcp-config", str(files["mcp"]), "--strict-mcp-config",
        "--tools", BUILTIN_TOOLS, "--agents", str(files["agents"]),
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--restricted", "--disable-slash-commands",
    ]
    for key in ("gtnh_src", "corpus"):
        if paths[key].is_dir():
            argv += ["--add-dir", str(paths[key])]
        else:
            notes.append("--add-dir %s skipped: %s does not exist yet" % (key, paths[key]))
    if mode == "smoke":
        argv += ["--", prompt or "Say hello."]

    token, token_src = config.secret(cfg, "claude_oauth_token")
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOW or k.startswith("LC_")}
    env.update({
        "HOME": str(home),                           # dev isolation: nothing under the owner's home is read
        "CLAUDE_CONFIG_DIR": str(home),              # Dave's own settings, sessions and credentials store
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",       # no CLAUDE.md/AGENTS.md at all: user, project or nested
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",      # Dave's memory is dave-memory, not Claude Code's
        "ENABLE_TOOL_SEARCH": "false",               # few MCP tools: load them all up front, no ToolSearch
        "CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS": "1",  # built-in Explore/Plan agents off (also denied in settings)
        "DISABLE_AUTOUPDATER": "1",                  # the binary is pinned by whoever installs it
        "DAVE_CONFIG": str(cfg["config_path"]),
        "DAVE_ROOT": str(cfg["root"]),
    })
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    redacted = dict(env)
    if token:
        redacted["CLAUDE_CODE_OAUTH_TOKEN"] = "<redacted, %d chars, from %s>" % (len(token), token_src)
    for k in list(redacted):
        if re.search(r"TOKEN|KEY|SECRET|PASSW", k) and k != "CLAUDE_CODE_OAUTH_TOKEN":
            redacted[k] = "<redacted>"
    return {"argv": argv, "env": env, "redacted_env": redacted, "cwd": workdir, "files": files, "notes": notes,
            "problems": problems(cfg, workdir.resolve() if workdir.exists() else workdir),
            "token_source": token_src, "mcp_servers": sorted(mcp["mcpServers"]), "cfg": cfg,
            "settings": settings, "agents": agents}


# ---------------------------------------------------------------- CLI

def show(b, as_json=False):
    cfg = b["cfg"]
    bridge_token, bridge_src = config.secret(cfg, "bridge_token")
    if as_json:
        print(json.dumps({"argv": b["argv"], "cwd": str(b["cwd"]), "env": b["redacted_env"],
                          "files": {k: str(v) for k, v in b["files"].items()}, "notes": b["notes"],
                          "problems": b["problems"], "mcp_servers": b["mcp_servers"],
                          "bridge": {"url": cfg["bridge"]["url"], "token": bridge_src}}, indent=2))
        return
    print("# cwd\n" + str(b["cwd"]))
    print("\n# command")
    print(" \\\n  ".join(shlex.quote(a) for a in b["argv"]))
    print("\n# environment (nothing else is inherited)")
    for k in sorted(b["redacted_env"]):
        print("%s=%s" % (k, b["redacted_env"][k]))
    if not b["token_source"]:
        print("CLAUDE_CODE_OAUTH_TOKEN=<missing: set it in the environment, a docker secret or dave/.env>")
    print("\n# rendered files")
    for k, v in b["files"].items():
        print("%-14s %s" % (k, v))
    print("\n# MCP servers: " + (", ".join(b["mcp_servers"]) or "(none)"))
    print("# bridge (daemon): %s, token %s" % (cfg["bridge"]["url"], bridge_src or "missing"))
    for n in b["notes"]:
        print("note: " + n)
    for p in b["problems"]:
        print("PROBLEM: " + p)


SMOKE_PROMPT = (
    "This is an automated launch check, not a player. Do not call any tools. Reply in plain text with exactly "
    "these four lines:\n"
    "TOOLS: the names of every tool you can call, comma-separated\n"
    "MCP: the MCP server names those tools come from, comma-separated\n"
    "RELITIGATE: yes if any text you were given before this message contains the word 're-litigate', else no\n"
    "ARTIFACTS: yes if any text you were given before this message mentions keeping a local copy of artifacts, else no"
)


def run_events(b):
    """Runs a built command once; returns (init event, result event, CompletedProcess)."""
    proc = subprocess.run(b["argv"], cwd=b["cwd"], env=b["env"], capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)
    init = result = None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        elif ev.get("type") == "result":
            result = ev
    return init, result, proc


def check_init(b, init):
    """Prints the effective setup from the CLI's init event and returns a list of failures."""
    tools = init.get("tools") or []
    servers = init.get("mcp_servers") or []
    agents = init.get("agents") or []
    for label, value in (("model", init.get("model")), ("api key src", init.get("apiKeySource")),
                         ("cwd", init.get("cwd")), ("permission", init.get("permissionMode")),
                         ("tools", ", ".join(tools)),
                         ("mcp servers", ", ".join("%s=%s" % (s.get("name"), s.get("status")) for s in servers)),
                         ("agents", ", ".join(agents)), ("skills", init.get("skills")),
                         ("slash cmds", init.get("slash_commands")), ("add dirs", init.get("additional_directories"))):
        print("%-12s %s" % (label + ":", value))
    fails = []
    # the CLI reports the Agent tool under its legacy name "Task"
    builtin = sorted("Agent" if t == "Task" else t for t in tools if not t.startswith("mcp__"))
    if builtin != sorted(BUILTIN_TOOLS.split(",")):
        fails.append("built-in tools are %s, expected %s" % (builtin, BUILTIN_TOOLS))
    fails += ["MCP server %s is %s" % (s.get("name"), s.get("status")) for s in servers if s.get("status") != "connected"]
    if sorted(s.get("name") for s in servers) != b["mcp_servers"]:
        fails.append("MCP servers differ from mcp.json: %s" % b["mcp_servers"])
    if init.get("skills") or init.get("slash_commands"):
        fails.append("skills or slash commands are loaded")
    if init.get("permissionMode") != "dontAsk":
        fails.append("permission mode is not dontAsk")
    if str(init.get("cwd")) != str(b["cwd"]):
        fails.append("cwd is not the configured workdir")
    if PLANNER not in agents:
        fails.append("%s agent is not defined" % PLANNER)
    denied = set(b["settings"]["permissions"].get("deny", []))
    loose = [a for a in agents if a != PLANNER and not {"Agent(%s)" % a, "Task(%s)" % a} <= denied]
    if loose:
        fails.append("agent types reachable besides %s (add Agent(<type>) to the deny list): %s" % (PLANNER, loose))
    return fails


def probe(cfg):
    """Starts the exact configured process with NO credentials. The CLI reports its init event (tools, MCP
    servers, agents, skills) and then stops at "Not logged in", so this never calls a model."""
    b = build(cfg, mode="smoke", prompt="probe")
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        b["env"].pop(k, None)
    for p in b["problems"]:
        print("PROBLEM: " + p)
    init, result, proc = run_events(b)
    if init is None:
        print("FAILED: no init event. exit %s\n%s" % (proc.returncode, (proc.stderr or proc.stdout)[-2000:]))
        return 1
    fails = check_init(b, init)
    print("result:      %s" % (result or {}).get("result"))
    if init.get("apiKeySource") not in (None, "none"):
        fails.append("some credential was found although none was passed: %s" % init.get("apiKeySource"))
    for f in fails:
        print("FAIL: " + f)
    print("\nPROBE " + ("PASSED" if not fails and not b["problems"] else "FAILED"))
    return 0 if not fails and not b["problems"] else 1


def smoke(cfg):
    b = build(cfg, mode="smoke", prompt=SMOKE_PROMPT)
    if not b["token_source"]:
        print("SKIPPED: CLAUDE_CODE_OAUTH_TOKEN is not available (env, NAME_FILE, /run/secrets or dave/.env). "
              "No other auth is tried. Run `claude setup-token` and put the token in dave/.env.")
        return 0
    if b["problems"]:
        for p in b["problems"]:
            print("PROBLEM: " + p)
        return 1
    print("running one short call with token from %s ..." % b["token_source"])
    init, result, proc = run_events(b)
    if init is None:
        print("FAILED: no init event. exit %s\n%s" % (proc.returncode, (proc.stderr or proc.stdout)[-2000:]))
        return 1
    fails = check_init(b, init)
    if result:
        print("\n--- model reply (%s, %s ms) ---\n%s" % (result.get("subtype"), result.get("duration_ms"),
                                                     result.get("result")))
        reply = (result.get("result") or "").lower()
        if re.search(r"relitigate:\s*yes", reply) or re.search(r"artifacts:\s*yes", reply):
            fails.append("the reply says it saw the developer CLAUDE.md or the owner's personal CLAUDE.md")
    else:
        fails.append("no result event; stderr: " + proc.stderr[-2000:])
    for f in fails:
        print("FAIL: " + f)
    print("\nSMOKE " + ("PASSED" if not fails else "FAILED"))
    return 0 if not fails else 1


def main(argv):
    cfg = config.load()
    if "--smoke" in argv:
        return smoke(cfg)
    if "--probe" in argv:
        return probe(cfg)
    b = build(cfg)
    show(b, as_json="--json" in argv)
    return 1 if b["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
