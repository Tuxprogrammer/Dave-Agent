#!/usr/bin/env python3
"""Build tuxmine-<version>.zip: the official GTNH Prism/MultiMC instance plus our bits.

What it adds to GTNH's own client zip (and nothing else):
  * .minecraft/packwiz-installer-bootstrap.jar (pinned release)
  * instance.cfg: name, iconKey, OverrideCommands=true and a PreLaunchCommand that syncs
    the tuxmine client pack on every launch
  * tuxmine_dave.png in the instance root (Prism imports <iconKey>.png as the icon)
  * .minecraft/servers.dat with the tuxmine server first (any servers already listed are kept)

and what it removes: GTNH's fairplay JourneyMap (REMOVE below). The client pack installs
JourneyMap Unlimited in its place; packwiz never deletes files it did not install itself.

GTNH's JVM args, Java settings, mmc-pack.json components and patches are left alone.

Downloads are cached in .work/tuxmine/cache/ and checked against pinned sha256s.
The output goes to .work/tuxmine/out/. Run with -I-safe Python; needs Pillow.

Usage: tuxmine/scripts/build-instance.py [--version V] [--keep-tree]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import struct
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
TUXMINE = ROOT / "tuxmine"
WORK = ROOT / ".work" / "tuxmine"
CACHE = WORK / "cache"
BUILD = WORK / "build"
OUT = WORK / "out"

GTNH_VERSION = "2.9.0"
GTNH_ZIP_NAME = f"GT_New_Horizons_{GTNH_VERSION}_Java_17-26.zip"
GTNH_ZIP_URL = f"https://downloads.gtnewhorizons.com/Multi_mc_downloads/{GTNH_ZIP_NAME}"
# GTNH publishes no checksum; this is the file as downloaded on 2026-10-31 (747848389 bytes).
GTNH_ZIP_SHA256 = "6d0ebe7e6be18fb74b4fc920916cc5710e142a3f885072d324da05244d398b16"

BOOTSTRAP_VERSION = "v0.0.3"
BOOTSTRAP_URL = (
    "https://github.com/packwiz/packwiz-installer-bootstrap/releases/download/"
    f"{BOOTSTRAP_VERSION}/packwiz-installer-bootstrap.jar"
)
BOOTSTRAP_SHA256 = "a8fbb24dc604278e97f4688e82d3d91a318b98efc08d5dbfcbcbcab6443d116c"

# The pack lives under a secret path (see publish.sh); the token is git-ignored.
TOKEN_FILE = TUXMINE / "deploy/secrets/pack-token"


def pack_token() -> str:
    token = os.environ.get("TUXMINE_PACK_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")
    if not (len(token) >= 24 and token.isascii() and token.isalnum()):
        sys.exit(f"no usable pack token (24+ letters/digits) in {TOKEN_FILE} or TUXMINE_PACK_TOKEN")
    return token


def site(name: str, default: str) -> str:
    """A site setting: $TUXMINE_<NAME>, else tuxmine/deploy/secrets/<name> (git-ignored), else the example."""
    value = os.environ.get("TUXMINE_" + name.upper().replace("-", "_"))
    path = TUXMINE / "deploy/secrets" / name
    if not value and path.exists():
        value = path.read_text().strip()
    return value or default


PUBLIC_BASE = site("public-base", "https://pack.example.net").rstrip("/")
CLIENT_PACK_URL = f"{PUBLIC_BASE}/{pack_token()}/client/pack.toml"
INSTANCE_NAME = f"tuxmine (GTNH {GTNH_VERSION})"
ICON_KEY = "tuxmine_dave"
DAVE_SKIN = ROOT / "DaveBridge/src/main/resources/assets/davebridge/textures/entity/dave.png"
SERVER_NAME = "tuxmine"
SERVER_ADDRESS = site("server-address", "example.net:25567")

# GTNH files the client pack replaces. Missing ones fail the build, so a GTNH bump gets a look.
REMOVE = [".minecraft/mods/journeymap-1.7.10-5.2.23-fairplay.jar"]

# instance.cfg as GTNH ships it has no ConfigVersion, so Prism reads it with its old-format
# parser (backslash-unescape, no quote stripping here). Once Prism saves it, it is a QSettings
# INI where a bare leading quote would be eaten. Escaping the quotes as \" is read as a literal
# quote by both parsers, and is what Prism itself writes.
PRE_LAUNCH = f'\\"$INST_JAVA\\" -jar packwiz-installer-bootstrap.jar {CLIENT_PACK_URL}'
CFG_SET = {
    "name": INSTANCE_NAME,
    "iconKey": ICON_KEY,
    "OverrideCommands": "true",
    "PreLaunchCommand": PRE_LAUNCH,
}


def log(msg: str) -> None:
    print(f"[build-instance] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, sha256: str | None) -> Path:
    """Download url to dest (cached); verify sha256 when one is pinned."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        log(f"downloading {url}")
        part = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(url) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        part.rename(dest)
    actual = sha256_file(dest)
    if sha256 and actual != sha256:
        sys.exit(f"sha256 mismatch for {dest}:\n  expected {sha256}\n  got      {actual}\n"
                 "Delete the file to re-download, or update the pin if GTNH re-released it.")
    log(f"{dest.name} sha256 {actual}")
    return dest


# --- minimal NBT (uncompressed, big-endian), enough for servers.dat --------------------

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = range(13)
_FMT = {BYTE: ">b", SHORT: ">h", INT: ">i", LONG: ">q", FLOAT: ">f", DOUBLE: ">d"}


def _read_str(b: io.BytesIO) -> str:
    (n,) = struct.unpack(">H", b.read(2))
    return b.read(n).decode("utf-8")


def _read_payload(b: io.BytesIO, t: int):
    if t in _FMT:
        fmt = _FMT[t]
        return struct.unpack(fmt, b.read(struct.calcsize(fmt)))[0]
    if t == STRING:
        return _read_str(b)
    if t in (BYTE_ARRAY, INT_ARRAY, LONG_ARRAY):
        (n,) = struct.unpack(">i", b.read(4))
        size = {BYTE_ARRAY: 1, INT_ARRAY: 4, LONG_ARRAY: 8}[t]
        return (t, b.read(n * size))
    if t == LIST:
        et = b.read(1)[0]
        (n,) = struct.unpack(">i", b.read(4))
        return ("list", et, [_read_payload(b, et) for _ in range(n)])
    if t == COMPOUND:
        out = {}
        while True:
            ct = b.read(1)[0]
            if ct == END:
                return out
            name = _read_str(b)
            out[name] = (ct, _read_payload(b, ct))
    raise ValueError(f"unknown NBT tag {t}")


def _write_str(b: io.BytesIO, s: str) -> None:
    raw = s.encode("utf-8")
    b.write(struct.pack(">H", len(raw)) + raw)


def _write_payload(b: io.BytesIO, t: int, v) -> None:
    if t in _FMT:
        b.write(struct.pack(_FMT[t], v))
    elif t == STRING:
        _write_str(b, v)
    elif t in (BYTE_ARRAY, INT_ARRAY, LONG_ARRAY):
        size = {BYTE_ARRAY: 1, INT_ARRAY: 4, LONG_ARRAY: 8}[t]
        b.write(struct.pack(">i", len(v[1]) // size) + v[1])
    elif t == LIST:
        _, et, items = v
        b.write(bytes([et]) + struct.pack(">i", len(items)))
        for it in items:
            _write_payload(b, et, it)
    elif t == COMPOUND:
        for name, (ct, cv) in v.items():
            b.write(bytes([ct]))
            _write_str(b, name)
            _write_payload(b, ct, cv)
        b.write(bytes([END]))
    else:
        raise ValueError(f"unknown NBT tag {t}")


def read_servers_dat(data: bytes) -> list[dict]:
    b = io.BytesIO(data)
    if b.read(1)[0] != COMPOUND:
        raise ValueError("servers.dat: root is not a compound")
    _read_str(b)
    root = _read_payload(b, COMPOUND)
    if "servers" not in root:
        return []
    _, (_, et, items) = root["servers"]
    return items if et == COMPOUND else []


def write_servers_dat(servers: list[dict]) -> bytes:
    b = io.BytesIO()
    b.write(bytes([COMPOUND]))
    _write_str(b, "")
    _write_payload(b, COMPOUND, {"servers": (LIST, ("list", COMPOUND if servers else END, servers))})
    return b.getvalue()


# --- instance edits -------------------------------------------------------------------

def edit_instance_cfg(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    todo = dict(CFG_SET)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("[") else None
        if key in todo:
            out.append(f"{key}={todo.pop(key)}")
        else:
            out.append(line)
    # Keys not present yet go at the end of the leading (General) block, before any [Section].
    first_section = next((i for i, l in enumerate(out) if l.startswith("[") and l != "[General]"), len(out))
    out[first_section:first_section] = [f"{k}={v}" for k, v in todo.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def make_icon(dest: Path) -> None:
    from PIL import Image  # Pillow

    skin = Image.open(DAVE_SKIN).convert("RGBA")
    face = skin.crop((8, 8, 16, 16))          # head, front
    hat = skin.crop((40, 8, 48, 16))          # hat layer, front (transparent if unused)
    face.alpha_composite(hat)
    face.resize((128, 128), Image.Resampling.NEAREST).save(dest, "PNG", optimize=True)


def add_server(dat: Path) -> None:
    servers = read_servers_dat(dat.read_bytes()) if dat.exists() else []
    servers = [s for s in servers if s.get("ip", (STRING, ""))[1] != SERVER_ADDRESS]
    servers.insert(0, {"name": (STRING, SERVER_NAME), "ip": (STRING, SERVER_ADDRESS)})
    dat.write_bytes(write_servers_dat(servers))


# --- main -----------------------------------------------------------------------------

def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract treating the archive as untrusted: no absolute paths, no '..', no symlinks."""
    dest = dest.resolve()
    for info in zf.infolist():
        p = PurePosixPath(info.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
            sys.exit(f"refusing suspicious zip entry: {info.filename!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            sys.exit(f"refusing symlink in zip: {info.filename!r}")
        target = (dest / p).resolve()
        if not target.is_relative_to(dest):
            sys.exit(f"refusing zip entry outside dest: {info.filename!r}")
        zf.extract(info, dest)


def build_zip(tree: Path, top: str, src_info: dict[str, zipfile.ZipInfo], dest: Path) -> None:
    """Zip tree/ under top/, reusing each original entry's timestamp and compression."""
    default_time = (2026, 1, 1, 0, 0, 0)
    part = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
        for path in sorted(tree.rglob("*")):
            rel = path.relative_to(tree).as_posix()
            name = f"{top}/{rel}" + ("/" if path.is_dir() else "")
            orig = src_info.get(rel + ("/" if path.is_dir() else ""))
            info = zipfile.ZipInfo(name, date_time=orig.date_time if orig else default_time)
            if path.is_dir():
                if not orig:  # mirror the source: only directory entries GTNH's zip had
                    continue
                info.external_attr = (0o40755 << 16) | 0x10
                zf.writestr(info, b"")
                continue
            info.external_attr = 0o100644 << 16
            info.compress_type = orig.compress_type if orig else zipfile.ZIP_DEFLATED
            with path.open("rb") as src, zf.open(info, "w", force_zip64=path.stat().st_size > 0x7FFFFFFF) as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    part.rename(dest)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="zip version label (default: client pack.toml version)")
    ap.add_argument("--keep-tree", action="store_true", help="keep the unpacked build tree")
    args = ap.parse_args()

    with (TUXMINE / "client/pack.toml").open("rb") as f:
        version = args.version or tomllib.load(f)["version"]
    if not version.replace(".", "").replace("-", "").isalnum():
        sys.exit(f"bad version label {version!r}")

    gtnh_zip = fetch(GTNH_ZIP_URL, CACHE / GTNH_ZIP_NAME, GTNH_ZIP_SHA256)
    bootstrap = fetch(BOOTSTRAP_URL, CACHE / f"packwiz-installer-bootstrap-{BOOTSTRAP_VERSION}.jar", BOOTSTRAP_SHA256)

    tree_root = BUILD / f"instance-{version}"
    if tree_root.exists():
        shutil.rmtree(tree_root)
    tree_root.mkdir(parents=True)

    log(f"unpacking {gtnh_zip.name}")
    with zipfile.ZipFile(gtnh_zip) as zf:
        tops = {PurePosixPath(n).parts[0] for n in zf.namelist()}
        if len(tops) != 1:
            sys.exit(f"expected one top-level folder in the GTNH zip, found {sorted(tops)}")
        src_top = tops.pop()
        src_info = {i.filename[len(src_top) + 1:]: i for i in zf.infolist()}
        safe_extract(zf, tree_root)
    inst = tree_root / src_top
    for need in ("instance.cfg", "mmc-pack.json", ".minecraft"):
        if not (inst / need).exists():
            sys.exit(f"GTNH zip has no {need} under {src_top}/; not a Prism/MultiMC instance?")

    for rel in REMOVE:
        if not (inst / rel).is_file():
            sys.exit(f"GTNH zip has no {rel}; update REMOVE in {Path(__file__).name}")
        log(f"removing {rel}")
        (inst / rel).unlink()

    log("adding packwiz-installer-bootstrap.jar, icon, servers.dat; editing instance.cfg")
    shutil.copyfile(bootstrap, inst / ".minecraft/packwiz-installer-bootstrap.jar")
    edit_instance_cfg(inst / "instance.cfg")
    make_icon(inst / f"{ICON_KEY}.png")
    add_server(inst / ".minecraft/servers.dat")

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"tuxmine-{version}.zip"
    log(f"zipping {dest}")
    build_zip(inst, INSTANCE_NAME, src_info, dest)
    if not args.keep_tree:
        shutil.rmtree(tree_root)

    digest = sha256_file(dest)
    (dest.with_name(dest.name + ".sha256")).write_text(f"{digest}  {dest.name}\n")
    size = dest.stat().st_size
    print(f"\n{dest}\n  size   {size} bytes ({size / 2**20:.1f} MiB)\n  sha256 {digest}")


if __name__ == "__main__":
    main()
