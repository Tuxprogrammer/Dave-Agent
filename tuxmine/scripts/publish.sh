#!/usr/bin/env bash
# Publish the tuxmine packs and the newest Prism instance zip to the Caddy pack host.
#
#   tuxmine/scripts/publish.sh [--dry-run] [--zip PATH] TARGET
#
# TARGET is an rsync destination, e.g. deploy@game-host.example.net:/opt/gtnh/packs/
# There is deliberately no default: the script refuses to run without one. TARGET must be the
# pack root: it must already hold the marker file .tuxmine-packs (create it once on the host:
# `touch /opt/gtnh/packs/.tuxmine-packs`), and an empty remote path ("host:"), "/", "~" and
# "." are refused outright, because the sync deletes whatever else is in TARGET.
#
# Steps:
#   0. Check TARGET (above).
#   1. `packwiz refresh` a scratch copy of both packs; fail if that changed anything (the
#      committed index was stale) or, in a git checkout, if either pack has uncommitted changes.
#      The packs themselves are never modified, so a failed run fails again until fixed.
#   2. Assemble .work/tuxmine/publish/<token>/: client/ and server/ (pack.toml, index.toml and
#      only the files the index lists, so .packwizignore'd files never leave), the instance zip,
#      index.html. Everything lives under the secret token path; nothing is published at the root,
#      so the host answers 404 to anyone without the link (scanners, crawlers).
#      Refuses: known secret files and anything that looks like a secret; a zip whose
#      pre-launch URL carries a different token; a jar or zip that is already published under
#      the same name with different content (both are served cacheable for a day).
#   3. rsync it to TARGET. New files land first and are swapped in together (--delay-updates);
#      stale files are deleted afterwards, at most TUXMINE_MAX_DELETE (default 60) of them.
#      Older tuxmine-*.zip in the current <token>/ are kept; everything else, including the
#      directory of a rotated-out token, is deleted.
#
# The token never appears in this script's output: it is shown as <token>.
#
# The token is a shared secret, not per player. It comes from tuxmine/deploy/secrets/pack-token
# (git-ignored; create it with `python3 -c 'import secrets; print(secrets.token_hex(16))'`).
# build-instance.py bakes the same token into the instance's pre-launch URL, and the server's
# PACKWIZ_URL carries it too. Rotating it means rebuilding the zip and updating PACKWIZ_URL.
#
# Environment: PACKWIZ (default ~/go/bin/packwiz); TUXMINE_PACKS (folder holding client/ and
# server/, default tuxmine/; the local test points it at scratch copies); TUXMINE_PACK_TOKEN
# (overrides the token file); TUXMINE_MAX_DELETE (default 60).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUXMINE="$(dirname "$HERE")"
ROOT="$(dirname "$TUXMINE")"
WORK="$ROOT/.work/tuxmine"
STAGE="$WORK/publish"
PACKWIZ="${PACKWIZ:-$HOME/go/bin/packwiz}"
PACKS="${TUXMINE_PACKS:-$TUXMINE}"
# Site settings: $TUXMINE_PUBLIC_BASE, else deploy/secrets/public-base (git-ignored), else the example.
PUBLIC_BASE="${TUXMINE_PUBLIC_BASE:-$(cat "$TUXMINE/deploy/secrets/public-base" 2>/dev/null || true)}"
PUBLIC_BASE="${PUBLIC_BASE:-https://pack.example.net}"
PUBLIC_BASE="${PUBLIC_BASE%/}"
TOKEN_FILE="$TUXMINE/deploy/secrets/pack-token"
MARKER=".tuxmine-packs"
MAX_DELETE="${TUXMINE_MAX_DELETE:-60}"

die() { echo "publish: $*" >&2; exit 1; }
usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

dry_run=0
zip=""
target=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run) dry_run=1 ;;
    --zip) [[ $# -ge 2 ]] || usage; zip="$2"; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) [[ -z "$target" ]] || die "only one TARGET allowed"; target="$1" ;;
  esac
  shift
done
[[ -n "$target" ]] || { echo "publish: refusing to run without an explicit TARGET" >&2; usage; }
[[ "$target" == */ ]] || target="$target/"
[[ "$MAX_DELETE" =~ ^[0-9]+$ ]] || die "TUXMINE_MAX_DELETE must be a number"
[[ -x "$PACKWIZ" ]] || die "packwiz not found at $PACKWIZ (set PACKWIZ=...)"
TOKEN="${TUXMINE_PACK_TOKEN:-$(cat "$TOKEN_FILE" 2>/dev/null || true)}"
[[ "$TOKEN" =~ ^[A-Za-z0-9]{24,}$ ]] || die "no usable pack token (24+ letters/digits) in $TOKEN_FILE or TUXMINE_PACK_TOKEN"
mask() { sed "s/$TOKEN/<token>/g"; }   # the token is letters/digits only, so it is sed-safe

# --- 0. target sanity -----------------------------------------------------------------
# rsync treats "host:path" (a colon before any slash) as remote. Everything in TARGET that is
# not ours gets deleted, so refuse anything that isn't clearly a dedicated folder.
if [[ "$target" =~ ^[^/]*: ]]; then remote=1; tpath="${target#*:}"; else remote=0; tpath="$target"; fi
p="$tpath"; while [[ "$p" == */ ]]; do p="${p%/}"; done
case "$p" in
  ""|"~"|"."|".."|*/.|*/..)
    die "refusing TARGET '$target': '$tpath' is not a pack folder (a bare 'host:' would be the
         remote home, which the trailing slash turns into '/'). Name the folder, e.g. host:/opt/gtnh/packs/" ;;
esac
if (( ! remote )); then
  real="$(realpath -m -- "$tpath")"
  [[ "$real" != "/" && "$real" != "$(realpath -m -- "$HOME")" ]] || die "refusing TARGET '$target' ($real)"
  [[ -f "$tpath$MARKER" ]] || die "no $MARKER in $target; refusing to sync (and delete) into a folder that isn't the pack root. Create it there once: touch ${tpath}$MARKER"
else
  rsync --list-only "$target$MARKER" >/dev/null 2>&1 \
    || die "no $MARKER in $target (or the host is unreachable); refusing to sync (and delete) into a folder that isn't the pack root. On the pack host, once: touch ${tpath}$MARKER"
fi

# --- 1. refresh and drift check -------------------------------------------------------
# Refresh a scratch copy, never the pack itself: otherwise the failed run would leave the
# refreshed index behind and a plain re-run would pass without the review it asks for.
in_git=0
git -C "$PACKS" rev-parse --is-inside-work-tree >/dev/null 2>&1 && in_git=1
CHECK="$WORK/refresh-check"
rm -rf "$CHECK"; mkdir -p "$CHECK"
for pack in client server; do
  dir="$PACKS/$pack"
  cp -a "$dir" "$CHECK/$pack"
  (cd "$CHECK/$pack" && "$PACKWIZ" refresh >/dev/null)
  if ! cmp -s "$dir/pack.toml" "$CHECK/$pack/pack.toml" || ! cmp -s "$dir/index.toml" "$CHECK/$pack/index.toml"; then
    diff -u "$dir/index.toml" "$CHECK/$pack/index.toml" >&2 || true
    die "$pack: index drift. 'packwiz refresh' would change $pack/index.toml or pack.toml (diff above),
         so the committed index does not match the files. Review the change, bump 'version' in
         $pack/pack.toml if a file changed, run '$PACKWIZ refresh' in $pack, commit, then re-run.
         (Nothing was changed; this run refreshed a scratch copy.)"
  fi
  if (( in_git )) && [[ -n "$(git -C "$PACKS" status --porcelain -- "$pack")" ]]; then
    git -C "$PACKS" status --short -- "$pack" >&2
    die "$pack: uncommitted changes in the pack; commit them first so what is published is in git"
  fi
done
(( in_git )) || echo "publish: note: not a git checkout, so only the refresh-drift check ran"

# --- 2. assemble the publish tree -----------------------------------------------------
rm -rf "$STAGE"
OUT="$STAGE/$TOKEN"
mkdir -p "$OUT"
for pack in client server; do
  python3 -I - "$PACKS/$pack" "$OUT/$pack" <<'PY'
import hashlib, re, shutil, sys, tomllib
from pathlib import Path, PurePosixPath
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
pack = tomllib.loads((src / "pack.toml").read_text())
idx_name = pack["index"]["file"]
index = tomllib.loads((src / idx_name).read_text())
files = [idx_name, "pack.toml"]
# Files that hold secrets or per-player/server state by design, whatever they contain today:
# DaveBridge's own configs (authToken; the per-player clientEvalAllowed opt-in), the Discord
# bot config (config/Chikachi/), server.properties (RCON), player lists, keys, env files.
secret_file = re.compile(
    r'(?i)(^|/)(davebridge\.cfg|server\.properties|ops\.json|whitelist\.json|banned-(ips|players)\.json'
    r'|usercache\.json|\.env|[^/]*\.env|pack-token|[^/]*\.(pem|key|p12|pfx|jks|keystore))$'
    r'|(^|/)(secrets?|chikachi)/|^config/(.*/)?[^/]*discordintegration[^/]*$')
for f in index.get("files", []):
    p = PurePosixPath(f["file"])
    if p.is_absolute() or ".." in p.parts:
        sys.exit(f"publish: bad path in index: {p}")
    if p.as_posix().lower() == "config/davebridge-client.cfg":
        sys.exit("publish: config/davebridge-client.cfg must never be shipped (per-player opt-in)")
    if secret_file.search(p.as_posix()):
        sys.exit(f"publish: {src.name}/{p} is a file that holds secrets or server state; never ship it")
    algo = f.get("hash-format", index.get("hash-format", "sha256"))
    data = (src / p).read_bytes()
    if hashlib.new(algo, data).hexdigest() != f["hash"]:
        sys.exit(f"publish: {src.name}/{p}: hash does not match index.toml")
    files.append(p.as_posix())
# Last-ditch secret scan over every text file (no NUL in the first 8 KiB): the packs are public.
# Any key ending in token / apikey / password / passwd / secret, quoted (JSON) or not, with a
# value of 12+ token-ish characters: S:authToken=..., "token": "...", rcon.password=..., etc.
secret = re.compile(rb'(?i)(token|api_?key|passw(or)?d|secret)["\']?\s*[:=]\s*["\']?[A-Za-z0-9_\-./+]{12,}')
for rel in files:
    data = (src / rel).read_bytes()
    if b"\0" not in data[:8192] and secret.search(data):
        sys.exit(f"publish: {src.name}/{rel} looks like it contains a secret; refusing")
    (dst / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / rel, dst / rel)
print(f"publish: {src.name}: {len(files) - 2} files, version {pack['version']}")
PY
done

if [[ -z "$zip" ]]; then
  zip="$(ls -t "$WORK"/out/tuxmine-*.zip 2>/dev/null | head -n1 || true)"
  [[ -n "$zip" ]] || die "no instance zip in $WORK/out/; run tuxmine/scripts/build-instance.py or pass --zip"
fi
[[ -f "$zip" ]] || die "zip not found: $zip"
zip_name="$(basename "$zip")"
[[ "$zip_name" =~ ^tuxmine-[A-Za-z0-9.+-]+\.zip$ ]] || die "zip must be named tuxmine-<version>.zip, got $zip_name"
# The zip's pre-launch command must point at this token's client pack; a zip built before a
# token rotation would publish fine and then fail every player's first launch.
TUXMINE_CHECK_TOKEN="$TOKEN" python3 -I - "$zip" <<'PY'
import os, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
want = "/" + os.environ["TUXMINE_CHECK_TOKEN"] + "/client/pack.toml"
cfgs = [n for n in z.namelist() if n.count("/") == 1 and n.endswith("/instance.cfg")]
if len(cfgs) != 1:
    sys.exit(f"publish: {os.path.basename(sys.argv[1])}: expected one <top>/instance.cfg, found {len(cfgs)}")
pre = [l for l in z.read(cfgs[0]).decode("utf-8", "replace").splitlines() if l.startswith("PreLaunchCommand=")]
if len(pre) != 1 or not pre[0].rstrip().endswith(want):
    sys.exit(f"publish: {os.path.basename(sys.argv[1])} was not built for the current pack token (its "
             "PreLaunchCommand does not end in /<token>/client/pack.toml); rebuild it with build-instance.py")
PY
ln "$zip" "$OUT/$zip_name" 2>/dev/null || cp "$zip" "$OUT/$zip_name"
zip_sha="$(sha256sum "$zip" | cut -d' ' -f1)"
echo "$zip_sha  $zip_name" > "$OUT/$zip_name.sha256"

# Jars and zips are served cacheable for a day, so a changed one must get a new file name.
# Compare with what is published now (nothing to compare on a first publish or a new token).
PREV="$WORK/previous"
rm -rf "$PREV"; mkdir -p "$PREV"
rsync -rq --include='/client/' --include='/server/' --include='/client/index.toml' --include='/server/index.toml' \
  --include="/$zip_name.sha256" --exclude='*' "$target$TOKEN/" "$PREV/" >/dev/null 2>&1 || true
python3 -I - "$PREV" "$OUT" "$zip_name" "$zip_sha" <<'PY'
import sys, tomllib
from pathlib import Path
prev, new, zip_name, zip_sha = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
bad = []
for pack in ("client", "server"):
    pi = prev / pack / "index.toml"
    if not pi.is_file():
        continue
    old = {f["file"]: f["hash"] for f in tomllib.loads(pi.read_text()).get("files", []) if not f.get("metafile")}
    for f in tomllib.loads((new / pack / "index.toml").read_text()).get("files", []):
        if f["file"].endswith(".jar") and old.get(f["file"], f["hash"]) != f["hash"]:
            bad.append(f"{pack}/{f['file']} (give the new jar a new file name)")
zs = prev / f"{zip_name}.sha256"
if zs.is_file() and zs.read_text().split()[0] != zip_sha:
    bad.append(f"{zip_name} (build it with a new label: build-instance.py --version <new>)")
if bad:
    sys.exit("publish: already published under the same name with different content; jars and zips are\n"
             "         cached for a day by name, so players could get the old bytes:\n  " + "\n  ".join(bad))
PY
zip_mib="$(( $(stat -c %s "$zip") / 1048576 ))"
client_ver="$(python3 -I -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["version"])' "$PACKS/client/pack.toml")"
server_ver="$(python3 -I -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["version"])' "$PACKS/server/pack.toml")"
zip_url="$PUBLIC_BASE/$TOKEN/$zip_name"

cat > "$OUT/index.html" <<HTML
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>tuxmine pack</title>
<style>
  :root { --bg:#f6f5f2; --fg:#1d1d1b; --muted:#66645e; --card:#fff; --line:#dedbd3; --accent:#2f6b3a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#151614; --fg:#e8e6e0; --muted:#a19e95; --card:#1f201d; --line:#34352f; --accent:#7fc28b; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, sans-serif; }
  main { max-width:44rem; margin:0 auto; padding:2.5rem 16px 3rem; }
  h1 { font-size:1.6rem; margin:0 0 .25rem; }
  .sub { color:var(--muted); margin:0 0 2rem; }
  ol { padding-left:1.25rem; } li { margin:.5rem 0; }
  .link { display:flex; gap:.5rem; align-items:stretch; margin:.5rem 0 0; }
  code, .url { font:14px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .url { flex:1; min-width:0; overflow-wrap:anywhere; background:var(--card); border:1px solid var(--line);
         border-radius:6px; padding:.55rem .7rem; }
  button { font:inherit; border:1px solid var(--accent); background:var(--accent); color:var(--bg);
           border-radius:6px; padding:0 .9rem; cursor:pointer; }
  .note { color:var(--muted); font-size:.92rem; }
  footer { margin-top:2.5rem; border-top:1px solid var(--line); padding-top:1rem; color:var(--muted); font-size:.85rem; }
  footer code { overflow-wrap:anywhere; }
</style>
</head>
<body>
<main>
  <h1>tuxmine</h1>
  <p class="sub">GT New Horizons 2.9.0 with the tuxmine extras. One link sets it up in Prism Launcher.</p>
  <ol>
    <li>Install <a href="https://prismlauncher.org/">Prism Launcher</a> and sign in.</li>
    <li>In Prism: <b>Add Instance &rarr; Import</b>, and paste this link:
      <div class="link"><span class="url" id="u">$zip_url</span><button type="button" id="c">Copy</button></div>
    </li>
    <li>Prism names the instance after the file; rename it if you like. Give it <b>Java 17 or newer</b>
        (Edit &rarr; Settings &rarr; Java) if Prism doesn't pick one.</li>
    <li>Launch. A small window fetches the tuxmine mods first; then the game starts.
        <b>tuxmine</b> is already in the server list.</li>
  </ol>
  <p class="note">This page and the link are only for tuxmine players; please don't post them publicly.</p>
  <p class="note">Our mods update themselves every time you launch. A new GTNH version needs a fresh
     instance from this page; copy your saves and settings across as usual.</p>
  <footer>
    $zip_name &middot; ${zip_mib} MiB &middot; sha256 <code>$zip_sha</code><br>
    client pack $client_ver &middot; server pack $server_ver
  </footer>
</main>
<script>
  document.getElementById('c').addEventListener('click', function () {
    var t = document.getElementById('u').textContent, b = this;
    (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(
      function () { b.textContent = 'Copied'; }, function () { b.textContent = 'Select it'; });
  });
</script>
</body>
</html>
HTML

echo "publish: staged $STAGE (zip $zip_name, sha256 $zip_sha)"
echo "publish: player page: $PUBLIC_BASE/<token>/  (the token is in $TOKEN_FILE)"

# --- 3. rsync -------------------------------------------------------------------------
# Protect only this token's older zips and the marker. Anything else in TARGET that isn't
# staged is deleted, including a rotated-out token's whole directory, its zips too, so the old
# link stops working. --max-delete caps the damage if TARGET is somehow still the wrong folder.
rsync_args=(-rt --chmod=D755,F644 --delete-after --delay-updates --max-delete="$MAX_DELETE"
            --filter="P /$TOKEN/tuxmine-*.zip" --filter="P /$TOKEN/tuxmine-*.zip.sha256"
            --filter="P /$MARKER"
            --itemize-changes --human-readable)
(( dry_run )) && rsync_args+=(--dry-run)
echo "publish: rsync -> $target$( (( dry_run )) && echo ' (dry run)')"
set +e
rsync "${rsync_args[@]}" "$STAGE/" "$target" 2>&1 | mask
rc=${PIPESTATUS[0]}
set -e
(( rc != 25 )) || die "rsync stopped deleting after $MAX_DELETE files (--max-delete), so TARGET may hold
         more than this script expects. Check it with --dry-run; if the deletions are right (e.g. a
         token rotation), re-run with TUXMINE_MAX_DELETE=<n>."
(( rc == 0 )) || die "rsync failed (exit $rc)"
(( dry_run )) && echo "publish: dry run, nothing was copied" || echo "publish: done"
