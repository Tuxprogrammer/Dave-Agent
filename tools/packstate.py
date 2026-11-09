#!/usr/bin/env python3
"""What pack the baked data was built from, and whether it is still current.

Dave's image bakes data derived from the pack: gtnh-src/ (source, including the tuxmine extras), the recipe database,
the search corpus and its embeddings. Each producer records the pack it was built from by calling `stamp` when it
succeeds; `check` compares those stamps with the current packs so a stale artifact never ships unnoticed.

The "pack" is stock GTNH (the extracted server pack, GTNH_PACK_DIR or the newest .work/gtnh-*/pack) plus our two
packwiz packs (tuxmine/server, tuxmine/client). A tuxmine pack is identified by its index hash in pack.toml, which
packwiz refresh rewrites whenever any file in the pack changes (jars, URL mods, configs).

  packstate.py show                    current pack state and per-component fingerprints (JSON)
  packstate.py jars [--fetch]          every tuxmine jar (JSON); --fetch downloads URL mods into the cache first
  packstate.py stamp COMPONENT [--note TEXT]   record that COMPONENT was just rebuilt from the current packs
  packstate.py check [COMPONENT...]    exit 1 and list every stale or unstamped component

Components and what they depend on:
  gtnh-src  GTNH + both tuxmine packs   (tools/decomp/, the tuxmine extras)
  recipes   GTNH + tuxmine server pack  (tools/recipe-export/run.sh -> data/recipes.sqlite)
  corpus    GTNH + both tuxmine packs   (tools/gtnh-search/index.py --extract -> data/corpus)
  index     GTNH + both tuxmine packs   (tools/gtnh-search/index.py -> data/index embeddings)

Environment: DAVE_AGENT_ROOT (default: this repo; set it when running from a worktree that lacks the git-ignored
data), TUXMINE_DIR (default <root>/tuxmine), GTNH_PACK_DIR, PACKSTATE_DIR (default <root>/data/packstate),
TUXMINE_JAR_CACHE (default <root>/.work/tuxmine-jars).

Downloaded jars are untrusted data: they are only ever read as zip files, never put on a classpath by this tool.
Standard library only.
"""
import hashlib, json, os, shutil, sys, time, tomllib, urllib.request
from pathlib import Path

COMPONENTS = {
    "gtnh-src": ("server", "client"),
    "recipes": ("server",),
    "corpus": ("server", "client"),
    "index": ("server", "client"),
}


def root():
    return Path(os.environ.get("DAVE_AGENT_ROOT") or Path(__file__).resolve().parent.parent)


def tuxmine_dir():
    return Path(os.environ.get("TUXMINE_DIR") or root() / "tuxmine")


def gtnh_pack_dir():
    if os.environ.get("GTNH_PACK_DIR"):
        return Path(os.environ["GTNH_PACK_DIR"])
    found = sorted(p for p in (root() / ".work").glob("gtnh-*/pack") if (p / "mods").is_dir())
    return found[-1] if found else None


def stamp_dir():
    return Path(os.environ.get("PACKSTATE_DIR") or root() / "data" / "packstate")


def jar_cache():
    return Path(os.environ.get("TUXMINE_JAR_CACHE") or root() / ".work" / "tuxmine-jars")


def gtnh_version(pack):
    if pack is None:
        return None
    props = pack / "server.properties"
    if props.is_file():
        for line in props.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("motd=") and "Horizons" in line:
                return line.rsplit(" ", 1)[-1].strip()
    name = pack.parent.name                      # .work/gtnh-<version>/pack
    return name[5:] if name.startswith("gtnh-") else None


def tuxmine_pack(side):
    d = tuxmine_dir() / side
    p = d / "pack.toml"
    if not p.is_file():
        return None
    t = tomllib.loads(p.read_text(encoding="utf-8"))
    return {"name": t.get("name"), "version": t.get("version"), "index_hash": t.get("index", {}).get("hash"),
            "dir": str(d)}


def state():
    pack = gtnh_pack_dir()
    s = {"gtnh_version": gtnh_version(pack), "gtnh_pack_dir": str(pack) if pack else None,
         "tuxmine": {side: tuxmine_pack(side) for side in ("server", "client")}}
    s["fingerprints"] = {c: fingerprint(s, c) for c in COMPONENTS}
    return s


def fingerprint(s, component):
    parts = {"gtnh": s["gtnh_version"]}
    for side in COMPONENTS[component]:
        tp = s["tuxmine"].get(side)
        parts[side] = tp and tp["index_hash"]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jars(fetch=False, tuxmine=None, cache=None):
    """Every jar in the tuxmine packs, merged across sides: name, sha256, packs (which packs carry it), origin
    (file|url), url, path (local file, None for an unfetched URL mod). tuxmine and cache override TUXMINE_DIR and
    TUXMINE_JAR_CACHE for one call (a caller with its own root, e.g. the search corpus's tests)."""
    out = {}
    cache = Path(cache) if cache else jar_cache()
    for side in ("server", "client"):
        d = Path(tuxmine or tuxmine_dir()) / side
        idx = d / "index.toml"
        if not idx.is_file():
            continue
        for f in tomllib.loads(idx.read_text(encoding="utf-8")).get("files", []):
            rel = f["file"]
            if not rel.startswith("mods/"):
                continue
            if rel.endswith(".jar"):
                path = d / rel
                e = {"name": path.name, "sha256": _sha256(path), "origin": "file", "url": None, "path": str(path)}
            elif rel.endswith(".pw.toml"):
                m = tomllib.loads((d / rel).read_text(encoding="utf-8"))
                dl = m.get("download", {})
                if dl.get("hash-format") != "sha256":
                    raise SystemExit(f"{d / rel}: hash-format {dl.get('hash-format')!r}, expected sha256")
                cached = cache / m["filename"]
                e = {"name": m["filename"], "sha256": dl["hash"], "origin": "url", "url": dl["url"],
                     "path": str(cached) if cached.is_file() and _sha256(cached) == dl["hash"] else None,
                     "display_name": m.get("name"), "pw_side": m.get("side")}
            else:
                continue
            prev = out.get(e["name"])
            if prev:
                if prev["sha256"] != e["sha256"]:
                    raise SystemExit(f"{e['name']}: different content in the server and client packs")
                prev["packs"].append(side)
            else:
                e["packs"] = [side]
                out[e["name"]] = e
    if fetch:
        for e in out.values():
            if e["path"] is None:
                e["path"] = str(_download(e["url"], e["name"], e["sha256"], cache))
    return sorted(out.values(), key=lambda e: e["name"].lower())


def _download(url, name, sha, cache):
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / name
    tmp = cache / (name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "dave-agent-packstate"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    got = _sha256(tmp)
    if got != sha:
        tmp.unlink()
        raise SystemExit(f"{name}: sha256 {got} does not match the pack's {sha} ({url})")
    os.replace(tmp, dest)
    return dest


def stamp(component, note=None):
    if component not in COMPONENTS:
        raise SystemExit(f"unknown component {component!r} (known: {', '.join(COMPONENTS)})")
    s = state()
    rec = {"component": component, "fingerprint": s["fingerprints"][component], "gtnh_version": s["gtnh_version"],
           "tuxmine": {side: s["tuxmine"][side] and s["tuxmine"][side]["version"] for side in COMPONENTS[component]},
           "stamped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note}
    d = stamp_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{component}.json.tmp"
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, d / f"{component}.json")
    return rec


def check(components=None):
    """Return a list of (component, problem) for every stale or unstamped component."""
    s = state()
    bad = []
    if not s["gtnh_version"]:
        bad.append(("*", "no extracted GTNH pack (GTNH_PACK_DIR or .work/gtnh-*/pack)"))
    for side in ("server", "client"):
        if not s["tuxmine"][side]:
            bad.append(("*", f"no tuxmine {side} pack at {tuxmine_dir() / side}"))
    for c in components or COMPONENTS:
        if c not in COMPONENTS:
            raise SystemExit(f"unknown component {c!r}")
        p = stamp_dir() / f"{c}.json"
        if not p.is_file():
            bad.append((c, "never stamped"))
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("fingerprint") != s["fingerprints"][c]:
            was = f"GTNH {rec.get('gtnh_version')}, tuxmine {rec.get('tuxmine')}"
            now = f"GTNH {s['gtnh_version']}, tuxmine " + str({x: s['tuxmine'][x] and s['tuxmine'][x]['version']
                                                               for x in COMPONENTS[c]})
            bad.append((c, f"built from {was}; current is {now}"))
    return bad


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "show":
        print(json.dumps(state(), indent=2))
    elif cmd == "jars":
        print(json.dumps(jars(fetch="--fetch" in rest), indent=2))
    elif cmd == "stamp":
        if not rest:
            raise SystemExit("usage: packstate.py stamp COMPONENT [--note TEXT]")
        note = rest[rest.index("--note") + 1] if "--note" in rest else None
        rec = stamp(rest[0], note)
        print(f"stamped {rec['component']} {rec['fingerprint']}")
    elif cmd == "check":
        bad = check(rest or None)
        for c, why in bad:
            print(f"STALE {c}: {why}", file=sys.stderr)
        if not bad:
            print("all pack-derived data is current")
        return 1 if bad else 0
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
