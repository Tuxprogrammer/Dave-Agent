#!/usr/bin/env python3
"""Add real source for the tuxmine packs' extra jars (everything on top of stock GTNH) to gtnh-src/.

Driven by tools/decomp/tuxmine-extras.json. For every jar that tools/packstate.py lists in the tuxmine packs:

  1. Match it to exactly one mapping entry. A jar with no entry FAILS the run, so a newly added mod can never go
     silently unsourced. Derive the ref from the jar version and check it on the remote (git ls-remote).
  2. Check out the source like the GTNH checkouts (gtnh-src/SOURCE-INDEX.md, "How the checkouts were made"): shallow,
     partial, sparse without binary assets, into gtnh-src/source/<repo>/, with .git/CLONE_OK. DaveBridge comes from
     this repository instead (git archive of its release commit into gtnh-src/source/DaveBridge/, .SNAPSHOT_OK).
     An up-to-date checkout is left alone.
  3. Copy the shipped jar's text resources (mcmod.info, lang, mixin configs, refmaps; the same filter as prep_jar.py)
     into gtnh-src/mods/<dir>/. Mods without exact source get a Vineflower decompile there too (SRG->MCP remapped).
  4. Check that the source covers the jar's classes, read each license, and write the rows: source-index.json (rows
     with "tuxmineExtra": true), a marked "Tuxmine extras" block in SOURCE-INDEX.md and in INDEX.md.
  5. Remove the checkouts and mods/ dirs of jars that left the packs, then `packstate.py stamp gtnh-src`.

Nothing from a checkout or a jar is ever executed: no gradle, no build scripts. Jars are read as zip files; Vineflower
only reads class files. Run Python with -I.

usage: DAVE_AGENT_ROOT=<project root> python3 -I tools/decomp/tuxmine_extras.py [--plan] [--no-stamp]
  --plan      resolve and print what would be done, change nothing (still needs the network for ls-remote)
  --no-stamp  do not record the gtnh-src stamp (for partial runs)
Environment: DAVE_AGENT_ROOT, VINEFLOWER_JAR (default: newest <root>/.work/gtnh-*/tools/vineflower-*.jar), plus the
packstate.py variables.
"""
import fnmatch, hashlib, io, json, os, re, shutil, subprocess, sys, tarfile, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # -I drops the script dir from sys.path
sys.path.insert(0, str(HERE.parent))
import packstate                          # noqa: E402  tools/packstate.py
from prep_jar import KEEP_EXT, DROP_DIRS, SHADED, MRJ   # noqa: E402  same resource filter as the decompile path
from decompile_mods import out_name      # noqa: E402  same mods/<dir> naming as the GTNH jars
from make_index import mcmod_info        # noqa: E402  same lenient mcmod.info parser as INDEX.md

CONFIG = HERE / "tuxmine-extras.json"
BEGIN, END = "<!-- tuxmine-extras:begin -->", "<!-- tuxmine-extras:end -->"
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
MARKER = ".TUXMINE_EXTRA"                # in every gtnh-src/mods/<dir>/ this tool owns
SNAPSHOT = ".SNAPSHOT_OK"                # in gtnh-src/source/DaveBridge/ (no .git: it is a git archive)
TOOL_VERSION = 1                         # bump to force mods/ dirs to be rebuilt
# Same sparse patterns as the GTNH checkouts (binary assets skipped).
SPARSE = ["/*"] + ["!*." + e for e in (
    "png PNG jpg jpeg gif ogg wav mp3 psd xcf blend blend1 jar zip 7z ico tga bmp webp schematic nbt ttf otf mp4 "
    "kra pdn obj b3d tcn ase aseprite dds").split()]
SRC_EXT = (".java", ".kt", ".scala", ".groovy")
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": os.environ.get("HOME", "/nonexistent")}


class Fail(SystemExit):
    def __init__(self, msg):
        super().__init__("tuxmine_extras: " + msg)


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------------------------------------- git

def git(*args, cwd=None, check=True, capture=True, stdout=None):
    # core.symlinks=false: a symlink in an untrusted repo is checked out as a plain text file.
    cmd = ["git", "-c", "core.symlinks=false", "-c", "protocol.file.allow=user"] + list(args)
    p = subprocess.run(cmd, cwd=cwd, env=GIT_ENV, stdout=stdout or (subprocess.PIPE if capture else None),
                       stderr=subprocess.PIPE, timeout=1800)
    if check and p.returncode != 0:
        raise Fail(f"git {' '.join(args)} failed ({p.returncode}): {p.stderr.decode(errors='replace').strip()[-800:]}")
    return p.stdout.decode(errors="replace").strip() if capture and stdout is None else p


def ls_remote_tag(repo, tag):
    out = git("ls-remote", repo, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    refs = dict(reversed(line.split("\t", 1)) for line in out.splitlines() if "\t" in line)
    sha = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not sha:
        raise Fail(f"tag {tag!r} does not exist on {repo} (derived from the jar version; fix the mapping's tag "
                   f"template in {CONFIG.name} or check that the release was tagged)")
    return sha


def head_of(path):
    p = git("-C", str(path), "rev-parse", "HEAD", check=False, capture=True, stdout=subprocess.PIPE)
    return p.stdout.decode().strip() if p.returncode == 0 else None


def checkout_ok(path, repo, commit):
    path = Path(path)
    if not (path / ".git" / "CLONE_OK").is_file() or head_of(path) != commit:
        return False
    url = git("-C", str(path), "config", "--get", "remote.origin.url", check=False, capture=True,
              stdout=subprocess.PIPE).stdout.decode().strip()
    return url.rstrip("/").removesuffix(".git") == repo.rstrip("/").removesuffix(".git")


def clone(repo, dest, commit, tag=None):
    """Shallow, partial, sparse, detached checkout of `commit` (via `tag` when given) into dest, atomically."""
    dest = Path(dest)
    if checkout_ok(dest, repo, commit):
        return False
    tmp = dest.parent / f".tmp-{dest.name}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if tag:
        git("clone", "--depth", "1", "--single-branch", "--no-tags", "--branch", tag, "--filter=blob:none",
            "--no-checkout", repo, str(tmp))
    else:
        git("init", "-q", str(tmp))
        git("-C", str(tmp), "remote", "add", "origin", repo)
        git("-C", str(tmp), "config", "remote.origin.tagOpt", "--no-tags")
        git("-C", str(tmp), "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit)
        git("-C", str(tmp), "update-ref", "--no-deref", "HEAD", commit)
    git("-C", str(tmp), "sparse-checkout", "set", "--no-cone", *SPARSE)
    git("-C", str(tmp), "checkout", "-q", "--detach", commit)
    got = head_of(tmp)
    if got != commit:
        raise Fail(f"{repo}: checked out {got}, expected {commit}")
    (tmp / ".git" / "CLONE_OK").write_text("")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    return True


def commit_date(path):
    return git("-C", str(path), "log", "-1", "--format=%cs", "HEAD")


# ------------------------------------------------------------------------------------------- DaveBridge (this repo)

def find_release_commit(repo_root, subdir, version):
    """The commit of this repository that built `subdir` version `version`. Fails unless exactly one is found."""
    if git("-C", str(repo_root), "rev-parse", "--is-inside-work-tree", check=False, capture=True,
           stdout=subprocess.PIPE).returncode != 0:
        raise Fail(f"{repo_root} is not a git checkout; the {subdir} source is taken from this repository's history")
    found = {}
    for t in (f"davebridge-v{version}", f"davebridge-{version}", f"DaveBridge-{version}", f"DaveBridge-v{version}"):
        p = git("-C", str(repo_root), "rev-parse", "-q", "--verify", f"refs/tags/{t}^{{commit}}", check=False,
                capture=True, stdout=subprocess.PIPE)
        if p.returncode == 0:
            found.setdefault("tag", p.stdout.decode().strip())
    if "tag" in found:
        return found["tag"], f"tag davebridge-v{version}"
    subj = re.compile(rf"\b{re.escape(subdir)} v?{re.escape(version)}(?![\w.])")
    log_out = git("-C", str(repo_root), "log", "HEAD", "--format=%H %s", "--", f"{subdir}/")
    hits = [line.split(" ", 1)[0] for line in log_out.splitlines() if subj.search(line.split(" ", 1)[1])]
    added = git("-C", str(repo_root), "log", "HEAD", "--no-renames", "--diff-filter=A", "--format=%H", "--",
                f"tuxmine/server/mods/{subdir.lower()}-{version}.jar",
                f"tuxmine/client/mods/{subdir.lower()}-{version}.jar").split()
    how = []
    commit = None
    if hits:
        commit = hits[-1]              # oldest commit naming the version: the release
        how.append(f"commit subject names \"{subdir} {version}\"" + (f" ({len(hits)} such commits, oldest used)"
                                                                     if len(hits) > 1 else ""))
    if added:
        if commit and added[-1] != commit:
            raise Fail(f"{subdir} {version}: the commit naming the version ({commit[:10]}) is not the commit that "
                       f"added the jar ({added[-1][:10]}); tag the release commit davebridge-v{version}")
        commit = commit or added[-1]
        how.append("commit added the jar to the tuxmine pack")
    if not commit:
        raise Fail(f"no commit found for {subdir} {version}: tag the commit that built it `davebridge-v{version}` "
                   f"(git tag davebridge-v{version} <commit>) or name \"{subdir} {version}\" in its subject")
    return commit, "; ".join(how)


def snapshot_ok(dest, commit):
    p = Path(dest) / SNAPSHOT
    try:
        return json.loads(p.read_text())["commit"] == commit
    except Exception:
        return False


def snapshot(repo_root, subdir, commit, dest):
    """git archive of <commit>:<subdir> into dest (same binary filter as the sparse checkouts)."""
    dest = Path(dest)
    if snapshot_ok(dest, commit):
        return False
    tmp = dest.parent / f".tmp-{dest.name}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    data = git("-C", str(repo_root), "archive", "--format=tar", commit, f"{subdir}/", capture=True,
               stdout=subprocess.PIPE).stdout
    skip = [p[1:] for p in SPARSE if p.startswith("!")]
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.startswith(subdir + "/"):
                continue
            rel = m.name[len(subdir) + 1:]
            if not rel or ".." in rel.split("/") or any(fnmatch.fnmatch(os.path.basename(rel), s) for s in skip):
                continue
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as s, open(out, "wb") as d:
                shutil.copyfileobj(s, d)
    (tmp / SNAPSHOT).write_text(json.dumps({"commit": commit, "subdir": subdir, "method": "git archive"}) + "\n")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    return True


# -------------------------------------------------------------------------------------------------- jar contents

def jar_info(jar):
    """(mcmod.info entries, top-level class names) of a jar. Shaded/relocated packages and MRJ copies collapse."""
    info = mcmod_info(jar)
    with zipfile.ZipFile(jar) as z:
        names = z.namelist()
    classes = set()
    for n in names:
        if not n.endswith(".class"):
            continue
        m = MRJ.match(n)
        path = m.group(2) if m else n
        base = path.rsplit("/", 1)[-1]
        if "$" in base or base in ("module-info.class", "package-info.class") or SHADED.search(path) \
                or "/repack/" in path:
            continue
        classes.add(path[:-6].replace("/", "."))
    return info, classes


PKG = re.compile(r"^\s*package\s+([\w.]+)", re.M)


def source_classes(root, only=None):
    """Fully qualified top-level type names declared by the source files under root (from `package` + file name)."""
    found = set()
    for dp, dns, fs in os.walk(root):
        dns[:] = [d for d in dns if d != ".git" and d != "build"]
        rel = os.path.relpath(dp, root).replace(os.sep, "/")
        if only and not only(rel):
            continue
        for f in fs:
            if not f.endswith(SRC_EXT):
                continue
            try:
                with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                    head = fh.read(20000)
            except OSError:
                continue
            m = PKG.search(head)
            stem = f.rsplit(".", 1)[0]
            found.add(f"{m.group(1)}.{stem}" if m else stem)
    return found


def token_class(checkout):
    """The class the GTNH buildscript generates from gradle.properties' generateGradleTokenClass (read as text)."""
    p = Path(checkout) / "gradle.properties"
    if not p.is_file():
        return set()
    m = re.search(r"^\s*generateGradleTokenClass\s*=\s*([\w.]+)\s*$", p.read_text(encoding="utf-8", errors="replace"),
                  re.M)
    return {m.group(1)} if m else set()


def extract_resources(jar, dest):
    """The shipped jar's small text resources, as prep_jar.py keeps them. Returns the number written."""
    n = 0
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            name = info.filename
            if name.endswith("/") or name.startswith("/") or ".." in name.split("/") or "\\" in name or ":" in name:
                continue
            if name.endswith(".class") or MRJ.match(name):
                continue
            ext = os.path.splitext(name)[1].lower()
            if not ((ext in KEEP_EXT or os.path.basename(name).lower() in ("mcmod.info", "pack.mcmeta"))
                    and not DROP_DIRS.search(name) and not SHADED.search(name) and info.file_size < 8 * 1024 * 1024):
                continue
            out = Path(dest) / name
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as s, open(out, "wb") as d:
                shutil.copyfileobj(s, d)
            n += 1
    return n


def vineflower_jar(root):
    if os.environ.get("VINEFLOWER_JAR"):
        return Path(os.environ["VINEFLOWER_JAR"])
    found = sorted((root / ".work").glob("gtnh-*/tools/vineflower-*.jar"))
    if not found:
        raise Fail("no Vineflower jar (set VINEFLOWER_JAR or put it in .work/gtnh-<version>/tools/)")
    return found[-1]


def decompile(root, jar, dest, include):
    """Vineflower decompile of the classes under `include` prefixes, then SRG->MCP remap, into dest."""
    work = root / ".work" / "tuxmine-extras"
    work.mkdir(parents=True, exist_ok=True)
    stem = Path(jar).stem
    prep, stats, filtered = work / f"{stem}.prep.jar", work / f"{stem}.prep.json", work / f"{stem}.filtered.jar"
    subprocess.run([sys.executable, "-I", str(HERE / "prep_jar.py"), str(jar), str(prep), str(stats)], check=True)
    n = 0
    with zipfile.ZipFile(prep) as zi, zipfile.ZipFile(filtered, "w", zipfile.ZIP_STORED) as zo:
        for name in zi.namelist():
            if name.endswith(".class") and not any(name.startswith(p) for p in include):
                continue
            zo.writestr(name, zi.read(name))
            n += name.endswith(".class")
    if not n:
        raise Fail(f"{Path(jar).name}: no classes under {include} to decompile")
    tmp = Path(str(dest) + ".decomp")
    shutil.rmtree(tmp, ignore_errors=True)
    with open(work / f"{stem}.vineflower.log", "w") as lf:
        p = subprocess.run(["java", "-Xmx2000m", "-jar", str(vineflower_jar(root)), "--folder", "--log-level=warn",
                            "--thread-count=2", "--indent-string=    ", "--dump-bytecode-on-error=false",
                            str(filtered), str(tmp)], stdout=lf, stderr=subprocess.STDOUT, timeout=3600)
    if p.returncode != 0:
        raise Fail(f"Vineflower failed on {Path(jar).name} (log: {work / (stem + '.vineflower.log')})")
    subprocess.run([sys.executable, "-I", str(HERE / "remap_srg.py"), str(root / "gtnh-src" / "_mappings"),
                    str(work / f"{stem}.remap.json"), str(tmp)], check=True, stdout=subprocess.DEVNULL)
    files = sum(1 for _, _, fs in os.walk(tmp) for f in fs if f.endswith((".java", ".kt")))
    for dp, _, fs in os.walk(tmp):
        for f in fs:
            s = Path(dp) / f
            d = Path(dest) / s.relative_to(tmp)
            d.parent.mkdir(parents=True, exist_ok=True)
            os.replace(s, d)
    shutil.rmtree(tmp, ignore_errors=True)
    return files, n


# ------------------------------------------------------------------------------------------------------ licenses

def detect_license(root):
    """(SPDX id, note) from the root LICENSE/COPYING file of a checkout."""
    root = Path(root)
    lic_name = re.compile(r"(?i)^(licen[cs]e|copying)([.-]|$)")
    def found(d):
        return sorted(p for p in d.iterdir() if p.is_file() and lic_name.match(p.name)) if d.is_dir() else []
    at_root = found(root)
    # A plain root LICENSE, else the one the jar ships (src/main/resources), else e.g. a root LICENSE-template.
    cands = [p for p in at_root if "template" not in p.name.lower()] or found(root / "src" / "main" / "resources") \
        or at_root
    if not cands:
        return "none", "no LICENSE/COPYING file at the repo root"
    p = cands[0]
    t = re.sub(r"\s+", " ", p.read_text(encoding="utf-8", errors="replace"))
    rel, extra = p.relative_to(root).as_posix(), ""
    if p.parent != root or "template" in p.name.lower():
        extra += "; no plain LICENSE file at the repo root"
    if re.search(r"<year>|\[year\]|<copyright holders>|\[fullname\]", t):
        extra += "; unfilled template text, no copyright holder named"
    tl = t.lower()
    lic = "unknown"
    if "gnu affero general public license" in tl:
        lic = "AGPL-3.0"
    elif "gnu lesser general public license" in tl:
        lic = "LGPL-2.1" if "version 2.1" in tl else "LGPL-3.0"
    elif "gnu general public license" in tl:
        lic = "GPL-2.0" if "version 2," in tl and "version 3," not in tl else "GPL-3.0"
    elif "apache license" in tl and "version 2.0" in tl:
        lic = "Apache-2.0"
    elif "mozilla public license" in tl and "2.0" in tl:
        lic = "MPL-2.0"
    elif "this is free and unencumbered software" in tl:
        lic = "Unlicense"
    elif "do what the fuck you want" in tl:
        lic = "WTFPL"
    elif "cc0" in tl or "creative commons zero" in tl:
        lic = "CC0-1.0"
    elif "permission is hereby granted, free of charge" in tl:
        lic = "MIT"
    elif "redistribution and use in source and binary forms" in tl:
        lic = "BSD-3-Clause" if "neither the name" in tl else "BSD-2-Clause"
    elif "all rights reserved" in tl:
        lic = "LicenseRef-ARR"
    return lic, f"{rel}={lic}{extra}"


# ------------------------------------------------------------------------------------------------------- planning

def load_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for e in cfg["mods"]:
        e["_re"] = re.compile(e["jar"])
        if e["kind"] not in ("git", "this-repo", "covered", "skip"):
            raise Fail(f"{CONFIG.name}: unknown kind {e['kind']!r} in {e['jar']}")
        if e["kind"] == "skip" and not e.get("reason"):
            raise Fail(f"{CONFIG.name}: skip entry {e['jar']} needs a reason")
    return cfg


def side_of(packs):
    return "BOTH" if set(packs) >= {"server", "client"} else packs[0].upper()


def plan(jars, cfg, rows):
    """One plan item per jar. Fails on unmapped/ambiguous jars and on refs that do not exist."""
    unmapped, items = [], []
    for j in jars:
        hits = [e for e in cfg["mods"] if e["_re"].fullmatch(j["name"])]
        if not hits:
            unmapped.append(j["name"])
            continue
        if len(hits) > 1:
            raise Fail(f"{j['name']} matches {len(hits)} entries in {CONFIG.name}: {[e['jar'] for e in hits]}")
        e = hits[0]
        m = e["_re"].fullmatch(j["name"])
        items.append({"jar": j, "entry": e, "version": m.groupdict().get("version") or ""})
    if unmapped:
        raise Fail("tuxmine jars with no entry in tools/decomp/" + CONFIG.name + " (add a git/this-repo/covered/skip "
                   "entry for each): " + ", ".join(unmapped))
    by_manifest = {r["modId"]: r for r in rows if not r.get("tuxmineExtra")}
    resolved = {}
    for it in items:
        e, v = it["entry"], it["version"]
        if e["kind"] == "git":
            if e.get("commit"):
                if v != e.get("verified_version"):
                    raise Fail(f"{it['jar']['name']}: the pinned commit in {CONFIG.name} was verified for version "
                               f"{e.get('verified_version')}, the pack now ships {v}. Find the source for {v} and "
                               f"update the entry.")
                it.update(ref=e["commit"], refKind="commit", commit=e["commit"], branch=e.get("branch"))
            else:
                tag = e["tag"].format(version=v)
                key = (e["repo"], tag)
                if key not in resolved:
                    resolved[key] = ls_remote_tag(e["repo"], tag)
                it.update(ref=tag, refKind="tag", commit=resolved[key])
            it["dir"] = e.get("dir") or e["repo"].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        elif e["kind"] == "this-repo":
            commit, how = find_release_commit(packstate.root(), e["subdir"], v)
            it.update(ref=commit, refKind="commit", commit=commit, how=how, dir=e.get("dir") or e["subdir"])
        elif e["kind"] == "covered":
            row = by_manifest.get(e["covered_modId"])
            if not row:
                raise Fail(f"{it['jar']['name']}: no source-index.json row with modId {e['covered_modId']!r}")
            if row.get("ref") != v:
                raise Fail(f"{it['jar']['name']}: version {v} but the existing {row['path']} checkout is at "
                           f"{row.get('ref')}; the stock GTNH row no longer covers it (map it as kind git)")
            it.update(row=row, dir=row["path"].rstrip("/").rsplit("/", 1)[-1])
        if e["kind"] != "skip":
            it["out"] = out_name(it["jar"]["name"])
    seen = {}
    for it in items:
        if it["entry"]["kind"] in ("git", "this-repo"):
            prev = seen.setdefault(it["dir"], it)
            if prev["commit"] != it["commit"] or prev["entry"].get("repo") != it["entry"].get("repo"):
                raise Fail(f"{prev['jar']['name']} and {it['jar']['name']} need different checkouts in "
                           f"source/{it['dir']}/ ({prev['commit'][:10]} vs {it['commit'][:10]})")
    outs = {}
    for it in items:
        if "out" in it and outs.setdefault(it["out"], it["jar"]["name"]) != it["jar"]["name"]:
            raise Fail(f"{outs[it['out']]} and {it['jar']['name']} both map to mods/{it['out']}/")
    return items


# ---------------------------------------------------------------------------------------------------- the run

def owned_paths(rows, state):
    """gtnh-src-relative dirs this tool created before (rows + state file)."""
    owned = set(state.get("paths", []))
    for r in rows:
        if r.get("tuxmineExtra"):
            for k in ("path", "decompPath"):
                if r.get(k):
                    owned.add(r[k].removeprefix("gtnh-src/").rstrip("/"))
    return owned


def gtnh_claimed(rows):
    claimed = set()
    for r in rows:
        if r.get("tuxmineExtra"):
            continue
        for p in (r.get("path"), r.get("decompPath"), (r.get("apiSource") or {}).get("path")):
            if p:
                claimed.add(p.removeprefix("gtnh-src/").rstrip("/"))
    return claimed


def build_mods_dir(root, it, include_decompile):
    """gtnh-src/mods/<out>/: shipped resources (+ decompile). Rebuilt only when the jar or this tool changed."""
    src = root / "gtnh-src"
    dest = src / "mods" / it["out"]
    jar = it["jar"]
    want = {"jar": jar["name"], "sha256": jar["sha256"], "tool": TOOL_VERSION,
            "decompile": include_decompile or None}
    marker = dest / MARKER
    if dest.exists() and not marker.is_file():
        raise Fail(f"gtnh-src/mods/{it['out']}/ exists and is not ours (no {MARKER}); it would collide with a GTNH jar")
    try:
        have = json.loads(marker.read_text())
        if {k: have.get(k) for k in want} == want:
            return have
    except Exception:
        pass
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    rec = dict(want)
    if include_decompile:
        rec["java_files"], rec["classes"] = decompile(root, jar["path"], dest, include_decompile)
        rec["origin"] = "decompiled (" + ", ".join(p.rstrip("/").replace("/", ".") for p in include_decompile) + ")"
    else:
        rec["java_files"], rec["origin"] = 0, "resources-only"
    rec["resources"] = extract_resources(jar["path"], dest)
    marker.write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def run(do_stamp=True, plan_only=False):
    root = packstate.root()
    src = root / "gtnh-src"
    if not (src / "source-index.json").is_file():
        raise Fail(f"{src}/source-index.json not found; set DAVE_AGENT_ROOT to the checkout that has gtnh-src/")
    cfg = load_config()
    rows = json.loads((src / "source-index.json").read_text(encoding="utf-8"))
    state_p = src / ".tuxmine-extras-state.json"
    state = json.loads(state_p.read_text()) if state_p.is_file() else {}
    jars = packstate.jars(fetch=True)
    items = plan(jars, cfg, rows)
    for it in items:
        log(f"{it['jar']['name']:58} {it['entry']['kind']:9} {it.get('dir', '-'):22} mods/{it.get('out', '-'):24} "
            f"{it.get('ref', '')[:20]} {(it.get('commit') or '')[:12]}")
    if plan_only:
        return
    gt_claim = gtnh_claimed(rows)
    for d in {it["dir"] for it in items if it["entry"]["kind"] in ("git", "this-repo")}:
        if f"source/{d}" in gt_claim:
            raise Fail(f"source/{d}/ belongs to a GTNH manifest row; give the extra a different `dir`")

    # 1. checkouts
    done = set()
    for it in items:
        e = it["entry"]
        if e["kind"] not in ("git", "this-repo") or it["dir"] in done:
            continue
        done.add(it["dir"])
        dest = src / "source" / it["dir"]
        if e["kind"] == "this-repo":
            changed = snapshot(root, e["subdir"], it["commit"], dest)
        else:
            changed = clone(e["repo"], dest, it["commit"], tag=it["ref"] if it["refKind"] == "tag" else None)
        log(("checked out " if changed else "up to date  ") + f"source/{it['dir']}/ @ {it['commit'][:12]}")
        for sub, s in (e.get("submodules") or {}).items():
            sdest = dest / sub
            if sdest.is_dir() and not any(sdest.iterdir()):
                sdest.rmdir()
            ch = clone(s["repo"], sdest, s["commit"])
            log(("checked out " if ch else "up to date  ") + f"source/{it['dir']}/{sub}/ @ {s['commit'][:12]}")
        for b in e.get("bundles") or []:
            bsha = ls_remote_tag(b["repo"], b["tag"])
            b["_commit"] = bsha
            ch = clone(b["repo"], src / "source" / b["name"], bsha, tag=b["tag"])
            log(("checked out " if ch else "up to date  ") + f"source/{b['name']}/ @ {bsha[:12]}")

    # 2. shipped resources / decompiles in mods/
    for it in items:
        if it["entry"]["kind"] == "skip":
            continue
        it["mods"] = build_mods_dir(root, it, (it["entry"].get("decompile") or {}).get("include"))

    # 3. verification: does the source declare the jar's classes? (Classes the build generates are not in any source.)
    scanned = {}

    def classes_in(d):
        if d not in scanned:
            scanned[d] = source_classes(src / "source" / d)
        return scanned[d]

    for it in items:
        e = it["entry"]
        if e["kind"] == "skip":
            continue
        info, jcls = jar_info(it["jar"]["path"])
        it["mcmod"] = info
        sdir = src / "source" / it["dir"]
        if e.get("decompile"):
            jcls = {c for c in jcls if any(c.startswith(p.replace("/", ".")) for p in e["decompile"]["include"])}
        gen = (set(e.get("generated") or []) | token_class(sdir)) & jcls
        it["generated"] = sorted(gen)
        jcls -= gen
        if e["kind"] == "this-repo":
            main = source_classes(sdir, only=lambda rel: rel.startswith("src/main"))
            missing, extra = sorted(jcls - main), sorted(main - jcls)
            if missing or extra:
                raise Fail(f"{it['jar']['name']}: commit {it['commit'][:10]} does not match the jar (classes only in "
                           f"the jar: {missing[:8]}; only in the source: {extra[:8]}). Tag the commit that built it "
                           f"davebridge-v{it['version']}.")
            jlang = _jar_text(it["jar"]["path"], "assets/davebridge/lang/en_US.lang")
            slang = sdir / "src/main/resources/assets/davebridge/lang/en_US.lang"
            if jlang is not None and slang.is_file() and slang.read_bytes() != jlang:
                raise Fail(f"{it['jar']['name']}: en_US.lang differs from commit {it['commit'][:10]}")
            ver = {m.get("version") for m in info}
            if ver and ver != {it["version"]}:
                raise Fail(f"{it['jar']['name']}: mcmod.info says version {ver}")
        have = classes_in(it["dir"])
        hit = len(jcls & have)
        it["coverage"] = f"{hit}/{len(jcls)}"
        if jcls and hit < len(jcls):
            miss = jcls - have
            # Classes a jar embeds from another of the extras (e.g. a library it bundles) are sourced there.
            elsewhere = {}
            for d in sorted({i["dir"] for i in items if i.get("dir") and i["dir"] != it["dir"]}):
                found = miss & classes_in(d)
                if found:
                    elsewhere[f"source/{d}/"] = len(found)
                    miss -= found
            it["coverageElsewhere"] = elsewhere
            if elsewhere:
                log(f"  note: {it['jar']['name']}: {sum(elsewhere.values())} jar classes are sourced in {elsewhere}")
            if miss:
                log(f"  note: {it['jar']['name']}: {len(miss)} of {len(jcls)} jar classes have no source file "
                    f"(e.g. {sorted(miss)[:4]})")
            it["missing"] = sorted(miss)
            if hit < 0.5 * len(jcls):
                raise Fail(f"{it['jar']['name']}: source/{it['dir']}/ declares only {it['coverage']} of the jar's "
                           f"classes; wrong repo or ref?")

    # 4. indexes
    new_rows = make_rows(root, items)
    keep = [r for r in rows if not r.get("tuxmineExtra")]
    for r in keep:
        r.pop("tuxmine", None)
        r["notes"] = re.sub(r" ?Tuxmine: .*$", "", r.get("notes") or "")
    for it in items:
        if it["entry"]["kind"] == "covered":
            r = next(r for r in keep if r is it["row"] or r["modId"] == it["row"]["modId"])
            r["tuxmine"] = tux_field(it)
            r["notes"] = (r["notes"] + " " if r["notes"] else "") + "Tuxmine: " + it["entry"]["notes"]
    all_rows = keep + new_rows
    tmp = src / ".source-index.json.tmp"
    tmp.write_text(json.dumps(all_rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, src / "source-index.json")
    write_block(src / "SOURCE-INDEX.md", source_index_block(items, new_rows), before="## Our own mods",
                replace_section="## Our own mods")
    patch_journeymap_bullet(src / "SOURCE-INDEX.md", items)
    write_block(src / "INDEX.md", index_block(items))

    # 5. removed jars
    now = set()
    for r in new_rows:
        for k in ("path", "decompPath"):
            if r.get(k):
                now.add(r[k].removeprefix("gtnh-src/").rstrip("/"))
    for it in items:
        if it.get("out"):
            now.add(f"mods/{it['out']}")
    for p in sorted(owned_paths(rows, state) - now - gt_claim):
        top = p.split("/")[0]
        d = src / p
        if top not in ("source", "mods") or p.count("/") != 1 or not d.is_dir():
            continue
        if top == "mods" and not (d / MARKER).is_file():
            continue
        log(f"removing gtnh-src/{p}/ (its jar left the tuxmine packs)")
        shutil.rmtree(d)
    state_p.write_text(json.dumps({"paths": sorted(now), "built": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                  indent=1) + "\n")
    if do_stamp:
        rec = packstate.stamp("gtnh-src", note="tools/decomp/tuxmine_extras.py")
        log(f"stamped gtnh-src {rec['fingerprint']}")


def _jar_text(jar, name):
    with zipfile.ZipFile(jar) as z:
        return z.read(name) if name in z.namelist() else None


def tux_field(it):
    j = it["jar"]
    return {"jar": j["name"], "sha256": j["sha256"], "packs": j["packs"],
            "download": j.get("url"), "resourcesPath": f"gtnh-src/mods/{it['out']}/" if it.get("out") else None}


def make_rows(root, items):
    rows = []
    for it in items:
        e, j = it["entry"], it["jar"]
        if e["kind"] == "covered":
            continue
        info = it.get("mcmod") or []
        modids = [m["modid"] for m in info if m.get("modid")]
        name = e.get("name") or "; ".join(dict.fromkeys(m["name"] for m in info if m.get("name"))) \
            or j["name"][:-4]
        base = {"modId": modids[0] if modids else None, "modIds": modids, "name": name, "manifestName": None,
                "jar": j["name"], "packVersion": it["version"], "side": side_of(j["packs"])}
        mods = it.get("mods") or {}
        decomp = {"decompPath": f"gtnh-src/mods/{it['out']}/" if it.get("out") else None,
                  "decompOrigin": mods.get("origin")}
        if e["kind"] == "skip":
            rows.append({**base, "repoUrl": None, "ref": None, "refKind": None, "commit": None, "commitDate": None,
                         "match": "none", "sourceKind": None, "license": "unknown", "licenseNote": "not sourced",
                         "manifestLicense": None, "path": None, "decompPath": None, "decompOrigin": None,
                         "sourcesJar": None, "apiSource": None, "notes": "Skipped on purpose: " + e["reason"],
                         "searched": [], "tuxmineExtra": True, "tuxmine": tux_field(it)})
            continue
        sdir = root / "gtnh-src" / "source" / it["dir"]
        lic, licnote = detect_license(sdir)
        notes = e.get("notes", "")
        if e["kind"] == "this-repo":
            repo_url = git("-C", str(root), "remote", "get-url", "origin", check=False, capture=True,
                           stdout=subprocess.PIPE).stdout.decode().strip().removesuffix(".git") or None
            if repo_url and repo_url.startswith("git@github.com:"):
                repo_url = "https://github.com/" + repo_url.split(":", 1)[1]
            if repo_url and not repo_url.startswith("https://github.com/"):
                repo_url = None                # never record a local or private remote
            date = git("-C", str(root), "log", "-1", "--format=%cs", it["commit"])
            notes = (notes + f" Found by: {it['how']}. Snapshot of {e['subdir']}/ at that commit via git archive "
                     f"(no .git; {SNAPSHOT} holds the commit).").strip()
            drift = git("-C", str(root), "rev-list", "--count", f"{it['commit']}..HEAD", "--", f"{e['subdir']}/src")
            if drift != "0":
                notes += f" {e['subdir']}/src has {drift} newer commit(s) in this repo; this snapshot is the shipped jar."
            ref, ref_kind = it["commit"], "commit"
        else:
            repo_url, ref, ref_kind = e["repo"], it["ref"], it["refKind"]
            date = commit_date(sdir)
            if ref_kind == "commit":
                notes = (notes + f" Pinned commit {it['commit'][:12]} on branch {it.get('branch')}.").strip()
        api = None
        for sub, s in (e.get("submodules") or {}).items():
            slic, _ = detect_license(sdir / sub)
            api = {"repoUrl": s["repo"], "ref": s["branch"], "refKind": "branch", "notes": s["note"],
                   "path": f"gtnh-src/source/{it['dir']}/{sub}/", "commit": s["commit"], "license": slic,
                   "match": s.get("match")}
        row = {**base, "repoUrl": repo_url, "ref": ref, "refKind": ref_kind, "commit": it["commit"],
               "commitDate": date, "match": e.get("match", "exact"), "sourceKind": "original", "license": lic,
               "licenseNote": licnote, "manifestLicense": None, "path": f"gtnh-src/source/{it['dir']}/", **decomp,
               "sourcesJar": None, "apiSource": None, "notes": notes, "searched": e.get("searched", []),
               "tuxmineExtra": True, "tuxmine": {**tux_field(it), "ours": bool(e.get("ours")),
                                                 "jarClassCoverage": it.get("coverage"),
                                                 "generatedClasses": it.get("generated") or [],
                                                 "classesSourcedElsewhere": it.get("coverageElsewhere") or {},
                                                 "classesWithoutSource": (it.get("missing") or [])[:40]}}
        if api:
            row["submodules"] = [api]
        rows.append(row)
        for b in e.get("bundles") or []:
            bdir = root / "gtnh-src" / "source" / b["name"]
            blic, bnote = detect_license(bdir)
            rows.append({"modId": None, "modIds": [], "name": f"{b['name']} (bundled in {name})", "manifestName": None,
                         "jar": j["name"], "packVersion": b["tag"], "side": base["side"], "repoUrl": b["repo"],
                         "ref": b["tag"], "refKind": "tag", "commit": b["_commit"], "commitDate": commit_date(bdir),
                         "match": "exact", "sourceKind": "original", "license": blic, "licenseNote": bnote,
                         "manifestLicense": None, "path": f"gtnh-src/source/{b['name']}/", "decompPath": None,
                         "decompOrigin": None, "sourcesJar": None, "apiSource": None,
                         "notes": b["note"] + f" Runtime package: {b['runtimePackage']}.", "searched": [],
                         "tuxmineExtra": True, "tuxmine": {**tux_field(it), "bundled": True,
                                                           "runtimePackage": b["runtimePackage"]}})
    rows.sort(key=lambda r: (r["name"].lower(), r["jar"].lower()))
    return rows


# ------------------------------------------------------------------------------------------------------ markdown

def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def packs_txt(packs):
    return "+".join(packs)


def source_index_block(items, rows):
    L = [BEGIN, "## Tuxmine extras", "",
         "Our server's own additions on top of stock GTNH 2.9.0: every jar in the tuxmine packwiz packs "
         "(`server` = the game server, `client` = players' instances), including our own mods (GregGuns, Lost Cities: "
         "New Horizons, Fortunate One) and **DaveBridge itself**. Checked out like the GTNH mods above (shallow, "
         "partial, sparse, no binary assets; `.git/CLONE_OK`), except DaveBridge, which is a `git archive` of this "
         "repository at the commit that built the shipped jar (`.SNAPSHOT_OK` holds that commit). In "
         "`source-index.json` these rows have `\"tuxmineExtra\": true` and a `tuxmine` object (jar, sha256, packs, "
         "`jarClassCoverage` = jar top-level classes that have a source file). The shipped jars' `mcmod.info`, lang "
         "files, mixin configs and refmaps are in `gtnh-src/mods/<dir>/` (see INDEX.md).", "",
         "Generated by `tools/decomp/tuxmine_extras.py` from `tools/decomp/tuxmine-extras.json`; do not edit this "
         "block by hand. It fails on any tuxmine jar without a mapping entry.", "",
         "| mod | jar | packs | version | match | repo | ref | license | path |",
         "|---|---|---|---|---|---|---|---|---|"]
    sourced = [r for r in rows if r["match"] != "none"]
    for r in sourced:
        repo = f"[{r['repoUrl'].removeprefix('https://github.com/')}]({r['repoUrl']})" if r["repoUrl"] else ""
        ref = f"`{r['ref'][:12] if r['refKind'] == 'commit' else r['ref']}` ({r['refKind']})" if r["ref"] else ""
        match = r["match"] if r["match"] == "exact" else f"**{r['match']}**"
        L.append("| " + " | ".join(esc(x) for x in (
            r["name"], f"`{r['jar']}`", packs_txt(r["tuxmine"]["packs"]), r["packVersion"], match, repo, ref,
            r["license"], f"`{r['path']}`" if r["path"] else "")) + " |")
    covered = [it for it in items if it["entry"]["kind"] == "covered"]
    for it in covered:
        r = it["row"]
        L.append("| " + " | ".join(esc(x) for x in (
            r["name"], f"`{it['jar']['name']}`", packs_txt(it["jar"]["packs"]), it["version"],
            "exact (existing checkout)", f"[{r['repoUrl'].removeprefix('https://github.com/')}]({r['repoUrl']})",
            f"`{r['ref']}` ({r['refKind']})", r["license"], f"`{r['path']}`")) + " |")
    L += ["", "### Notes", ""]
    for r in sourced:
        t = r["tuxmine"]
        n = r["notes"]
        for s in r.get("submodules") or []:
            n += f" Submodule `{s['path']}`: {s['repoUrl']} @ `{s['commit'][:12]}` ({s['match']}). {s['notes']}"
        if t.get("classesSourcedElsewhere"):
            n += " Jar classes sourced in other checkouts: " + ", ".join(
                f"{k} ({v})" for k, v in t["classesSourcedElsewhere"].items()) + "."
        if t.get("classesWithoutSource"):
            n += " Jar classes with no source file: " + ", ".join(f"`{c}`" for c in t["classesWithoutSource"]) + "."
        if t.get("generatedClasses"):
            n += " Generated at build time (not in the source): " + ", ".join(
                f"`{c}`" for c in t["generatedClasses"]) + "."
        if n.strip():
            L.append(f"- **{r['name']}** (`{r['jar']}`): {n.strip()}")
    for it in covered:
        L.append(f"- **{it['row']['name']}** (`{it['jar']['name']}`): {it['entry']['notes']}")
    skips = [it for it in items if it["entry"]["kind"] == "skip"]
    L += ["", "### Skipped on purpose", ""]
    L += [f"- `{it['jar']['name']}` ({packs_txt(it['jar']['packs'])}): {it['entry']['reason']}" for it in skips] or \
        ["- none"]
    L += ["", "### Our own mods", "",
          "GregGuns, Lost Cities: New Horizons, Fortunate One and DaveBridge are the owner's mods (listed above). "
          "TrainHorizons is coming; add it to `tools/decomp/tuxmine-extras.json` when it ships in a pack.", "", END]
    return "\n".join(L) + "\n"


def index_block(items):
    L = [BEGIN, "## Tuxmine extras", "",
         "Jars our tuxmine packs add on top of the GTNH pack. The source is in `gtnh-src/source/` (see SOURCE-INDEX.md, "
         "\"Tuxmine extras\"); `mods/<dir>/` holds the shipped jar's text resources (`mcmod.info` with the real "
         "version, lang files, `mixins.*.json`, refmaps), so mixins are visible. They are not decompiled when the "
         "exact source is checked out: a decompile would only duplicate every grep hit. `origin`: `resources-only` "
         "(read the source in `source/`) or `decompiled (...)` (Vineflower + SRG->MCP, for code with no exact public "
         "source). Generated by `tools/decomp/tuxmine_extras.py`.", "",
         "| jar | packs | modid(s) | name | version (mcmod.info) | origin | output dir | files | source |",
         "|---|---|---|---|---|---|---|---|---|"]
    for it in sorted(items, key=lambda i: i["jar"]["name"].lower()):
        e, j = it["entry"], it["jar"]
        if e["kind"] == "skip":
            continue
        info = it.get("mcmod") or []
        modid = ", ".join(m["modid"] for m in info if m.get("modid")) or "-"
        name = e.get("name") or "; ".join(dict.fromkeys(m["name"] for m in info if m.get("name"))) or "-"
        ver = "; ".join(dict.fromkeys(str(m.get("version")) for m in info if m.get("version"))) or "-"
        mods = it.get("mods") or {}
        L.append("| " + " | ".join(esc(x) for x in (
            j["name"], packs_txt(j["packs"]), modid, name, ver, mods.get("origin", ""), f"mods/{it['out']}/",
            mods.get("java_files", 0), f"source/{it['dir']}/")) + " |")
    L += ["", "### Skipped tuxmine jars", ""]
    L += [f"- `{it['jar']['name']}`: {it['entry']['reason']}" for it in items if it["entry"]["kind"] == "skip"] or \
        ["- none"]
    L += ["", END]
    return "\n".join(L) + "\n"


def write_block(path, block, before=None, replace_section=None):
    """Replace the marked block in path, or insert it (replacing `replace_section` up to the next ## heading, else
    before `before`, else at the end)."""
    txt = path.read_text(encoding="utf-8")
    if BLOCK.search(txt):
        txt = BLOCK.sub(lambda _: block, txt, count=1)
    else:
        sec = re.search(rf"^{re.escape(replace_section)}\n.*?(?=^## |\Z)", txt, re.S | re.M) if replace_section \
            else None
        if sec:
            txt = txt[:sec.start()] + block + ("\n" if sec.end() < len(txt) else "") + txt[sec.end():]
        elif before and f"\n{before}\n" in txt:
            i = txt.index(f"\n{before}\n") + 1
            txt = txt[:i] + block + "\n" + txt[i:]
        else:
            txt = txt.rstrip("\n") + "\n\n" + block
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, path)


def patch_journeymap_bullet(path, items):
    """Point the stock-GTNH notes bullet of a covered mod at the extras block (idempotent)."""
    txt = path.read_text(encoding="utf-8")
    for it in items:
        if it["entry"]["kind"] != "covered":
            continue
        name = re.escape(it["row"]["name"])
        pat = re.compile(rf"^(- \*\*{name}\*\* \(`[^`]+`, [^)]*\): .*?)(?: Tuxmine: .*)?$", re.M)
        add = (f" Tuxmine: our packs ship `{it['jar']['name']}` on {' and '.join(it['jar']['packs'])}; its shipped "
               f"resources are in `gtnh-src/mods/{it['out']}/` (see Tuxmine extras).")
        txt = pat.sub(lambda m: m.group(1) + add, txt, count=1)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, path)


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    run(do_stamp="--no-stamp" not in argv, plan_only="--plan" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
