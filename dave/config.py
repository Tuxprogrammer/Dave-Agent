"""Loads dave/config.toml with environment overrides, and looks up secrets. Standard library only.

Used by dave_cmd.py, the dave-memory MCP server and (later) the daemon, so every location comes from one place.
"""

import os
import tomllib
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent        # the directory that contains dave/
DEFAULT_CONFIG = APP_DIR / "dave" / "config.toml"

# config key -> environment variable that overrides it
ENV = {
    ("pack", "version"): "DAVE_PACK_VERSION",
    ("model", "name"): "DAVE_MODEL",
    ("model", "fallback"): "DAVE_FALLBACK_MODEL",
    ("model", "effort"): "DAVE_EFFORT",
    ("model", "planner"): "DAVE_PLANNER_MODEL",
    ("paths", "gtnh_src"): "DAVE_GTNH_SRC",
    ("paths", "corpus"): "DAVE_CORPUS_DIR",
    ("paths", "index"): "DAVE_INDEX_DIR",
    ("paths", "memory"): "DAVE_MEMORY_DIR",
    ("paths", "memory_history"): "DAVE_MEMORY_HISTORY",
    ("paths", "queries"): "DAVE_QUERIES_DIR",
    ("paths", "claude_home"): "DAVE_CLAUDE_HOME",
    ("paths", "run"): "DAVE_RUN_DIR",
    ("paths", "workdir"): "DAVE_WORKDIR",
    ("paths", "logs"): "DAVE_LOG_DIR",
    ("paths", "recipes"): "DAVE_RECIPES_DB",
    ("prompt", "soul"): "DAVE_SOUL",
    ("prompt", "planner"): "DAVE_PLANNER_PROMPT",
    ("prompt", "markup_spec"): "DAVE_MARKUP_SPEC",
    ("claude", "bin"): "DAVE_CLAUDE_BIN",
    ("bridge", "url"): "DAVE_BRIDGE_URL",
    ("search", "state"): "DAVE_SEARCH_STATE",
}


def in_container():
    """True inside Docker/Podman, or when DAVE_CONTAINER=1. Dev .env fallbacks are disabled there."""
    if os.environ.get("DAVE_CONTAINER") in ("1", "true", "yes"):
        return True
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _resolve(value, base):
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else (base / p)


def load(path=None):
    """Returns the config as a dict of sections, with env overrides applied and paths made absolute.

    Adds cfg["root"] (data root), cfg["app"] (code root) and cfg["config_path"].
    """
    path = Path(path or os.environ.get("DAVE_CONFIG") or DEFAULT_CONFIG)
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for (section, key), var in ENV.items():
        if os.environ.get(var):
            cfg.setdefault(section, {})[key] = os.environ[var]
    root = Path(os.path.expanduser(os.environ.get("DAVE_ROOT") or str(APP_DIR))).resolve()
    cfg["root"], cfg["app"], cfg["config_path"] = root, APP_DIR, path.resolve()
    cfg["paths"] = {k: _resolve(v, root) for k, v in cfg.get("paths", {}).items()}
    cfg["prompt"] = {k: _resolve(v, APP_DIR) for k, v in cfg.get("prompt", {}).items()}
    # Empty means "no state volume" (dev), so it must not resolve to the root like the paths above.
    state = cfg.setdefault("search", {}).get("state") or ""
    cfg["search"]["state"] = _resolve(state, root) if state else ""
    return cfg


def bridge_socket(cfg):
    """The daemon's RPC socket for the `bridge` MCP server: <run>/bridge.sock.

    A unix socket path must fit in 108 bytes; a run dir deep in a checkout may not, so a long path is replaced by a
    short one in /tmp named after the run dir (still 0600, and only this user's daemon creates it).
    """
    import hashlib
    path = Path(cfg["paths"]["run"]) / "bridge.sock"
    if len(str(path).encode()) <= 100:
        return path
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    return Path("/tmp") / ("dave-bridge-%d-%s.sock" % (os.getuid(), digest))


def _read_env_file(path, var):
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    except OSError:
        pass
    return None


def secret(cfg, name):
    """Looks up a secret named in [secrets]. Returns (value or None, where it came from).

    Order: env NAME, file at env NAME_FILE, /run/secrets/<docker_secret>, then the dev .env file
    (only outside a container). The value itself is never logged.
    """
    spec = cfg.get("secrets", {}).get(name)
    if not spec:
        raise KeyError("unknown secret: %s" % name)
    var = spec["env"]
    if os.environ.get(var):
        return os.environ[var], "env " + var
    candidates = []
    if os.environ.get(var + "_FILE"):
        candidates.append(Path(os.environ[var + "_FILE"]))
    if spec.get("docker_secret"):
        candidates.append(Path("/run/secrets") / spec["docker_secret"])
    for p in candidates:
        try:
            value = p.read_text().strip()
        except OSError:
            continue
        if value:
            return value, "file " + str(p)
    if spec.get("dev_env_file") and not in_container():
        p = _resolve(spec["dev_env_file"], APP_DIR)
        value = _read_env_file(p, var)
        if value:
            return value, "dev file " + str(p)
    return None, None


def secret_file(cfg, name):
    """Path of a file that already holds the secret (NAME_FILE or the docker secret), or None.

    Lets a child process read a secret from a file instead of from its environment.
    """
    spec = cfg["secrets"][name]
    for p in (os.environ.get(spec["env"] + "_FILE"), "/run/secrets/" + spec["docker_secret"]):
        if p and Path(p).is_file():
            return Path(p)
    return None
