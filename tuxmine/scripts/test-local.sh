#!/usr/bin/env bash
# Local end-to-end test of tuxmine pack distribution. Touches nothing outside .work/tuxmine/test/
# (plus one throwaway Docker container), and never the real packs or the real server.
#
#   tuxmine/scripts/test-local.sh
#
#  1. Copy both packs to scratch, publish them with publish.sh into a local folder.
#  2. Serve that folder with the pinned Caddy image and the real deploy/Caddyfile (plain HTTP,
#     exactly as on the desktop), on 127.0.0.1:$PORT.
#  3. Server: packwiz-installer (the maven dist jar itzg uses, same main class) -g -s server
#     into a scratch /data. Expect davebridge, GregGuns, Fortunate One, WorldEdit,
#     DiscordIntegration, JourneyMap Unlimited and fortunateone.cfg.
#  4. Client: extract the instance zip like Prism would and run the bundled bootstrap with
#     -g -s client from its .minecraft. Expect davebridge, GregGuns, Fortunate One, WorldEdit + CUI,
#     JourneyMap Unlimited (the zip dropped GTNH's fairplay one) and our configs, no server-only mods, GTNH's own mods untouched.
#  5. Re-run both: no-op. Change a jar without refreshing: publish must refuse (drift) and leave
#     the pack untouched. publish must also refuse secrets, a jar changed under the same name and a
#     zip built for another token. Then bump the version with a new jar + a new client config:
#     both sides update, old jar deleted, stale root/old-token files deleted, this token's older
#     zip kept. Remove a mod and the config: deleted on the next sync.
#  6. The compose snippet merged onto a stub stack: gtnh_2 fetches over the stack network, and the
#     snippet leaves MODS unset.
# Also, before any of that: publish refuses unsafe TARGETs (empty remote path, "/", no
# .tuxmine-packs marker) and stops at --max-delete. Nothing here ever prints the token.
#
# Needs: docker, java, python3, rsync, ~/go/bin/packwiz, network (GitHub for the bootstrap's
# installer download, CurseForge/Modrinth CDNs for the server pack's URL mods).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUXMINE="$(dirname "$HERE")"
ROOT="$(dirname "$TUXMINE")"
# The public pack URL the built zip should carry: the same site setting publish.sh and build-instance.py read.
PUBLIC_BASE="${TUXMINE_PUBLIC_BASE:-$(cat "$TUXMINE/deploy/secrets/public-base" 2>/dev/null || true)}"
PUBLIC_BASE="${PUBLIC_BASE:-https://pack.example.net}"
PUBLIC_BASE="${PUBLIC_BASE%/}"
WORK="$ROOT/.work/tuxmine"
T="$WORK/test"
PORT="${PORT:-18073}"
PACKWIZ="${PACKWIZ:-$HOME/go/bin/packwiz}"
CADDY_IMAGE="caddy:2.11.7-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5"
CONTAINER="tuxmine-caddy-test"
INSTALLER_VER="v0.5.14"
INSTALLER_URL="https://maven.packwiz.infra.link/repository/release/link/infra/packwiz/packwiz-installer/$INSTALLER_VER/packwiz-installer-$INSTALLER_VER-dist.jar"
INSTALLER_SHA256="c9f646908d340d84773948a9a7d98bc1dae250d35e1016dc6e2b8459760b5598"
TOKEN_FILE="$TUXMINE/deploy/secrets/pack-token"
# The DaveBridge jar the packs ship now; the update step replaces it with a fake davebridge-9.9.9-test.jar.
DB="$(basename "$(ls "$TUXMINE"/client/mods/davebridge-*.jar | head -n1)")"
TOK="${TUXMINE_PACK_TOKEN:-$(cat "$TOKEN_FILE" 2>/dev/null || true)}"
[[ "$TOK" =~ ^[A-Za-z0-9]{24,}$ ]] || { echo "no pack token in $TOKEN_FILE" >&2; exit 1; }
export TUXMINE_PACK_TOKEN="$TOK"   # compose interpolation in step 6, as /opt/gtnh/.env does live
ROOTURL="http://127.0.0.1:$PORT"
BASE="$ROOTURL/$TOK"
mask() { sed "s/$TOK/<token>/g"; }   # never print the token, even on failure

pass=0
ok()   { echo "  PASS  $*"; pass=$((pass + 1)); }
fail() { echo "  FAIL  $*" >&2; exit 1; }
step() { echo; echo "== $*"; }
sha()  { sha256sum "$1" | cut -d' ' -f1; }

COMPOSE_PROJECT="tuxmine-composetest"
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  [[ -f "$T/compose/docker-compose.yaml" ]] && docker compose -p "$COMPOSE_PROJECT" --project-directory "$T/compose" \
    -f "$T/compose/docker-compose.yaml" -f "$TUXMINE/deploy/compose.snippet.yaml" -f "$T/compose/test-override.yaml" \
    down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

command -v docker >/dev/null && docker info >/dev/null 2>&1 || fail "docker is not available"

# Fresh scratch area
rm -rf "$T"
mkdir -p "$T/packs" "$T/srv" "$T/server-data" "$T/logs"
touch "$T/srv/.tuxmine-packs"   # the marker publish.sh requires in TARGET (/opt/gtnh/packs/.tuxmine-packs live)
cp -a "$TUXMINE/client" "$TUXMINE/server" "$T/packs/"
# An ignored file in the pack folder must never be published.
echo "not part of the pack" > "$T/packs/client/README.md"

export TUXMINE_PACKS="$T/packs"
publish() { "$HERE/publish.sh" "$@" "$T/srv/" > "$T/logs/publish.log" 2>&1; }
publish_to_srv() { "$HERE/publish.sh" "$T/srv/"; }
refresh() { (cd "$T/packs/$1" && "$PACKWIZ" refresh >/dev/null); }
set_version() { sed -i "s/^version = \".*\"/version = \"$2\"/" "$T/packs/$1/pack.toml"; }

# Tools
installer="$WORK/cache/packwiz-installer-$INSTALLER_VER-dist.jar"
if [[ ! -f "$installer" ]]; then curl -fsSL -o "$installer.part" "$INSTALLER_URL" && mv "$installer.part" "$installer"; fi
[[ "$(sha "$installer")" == "$INSTALLER_SHA256" ]] || fail "packwiz-installer dist jar hash mismatch"

zip="$(ls -t "$WORK"/out/tuxmine-*.zip 2>/dev/null | head -n1 || true)"
if [[ -z "$zip" ]]; then python3 -I "$HERE/build-instance.py"; zip="$(ls -t "$WORK"/out/tuxmine-*.zip | head -n1)"; fi

# Expected hashes come from the pack sources, not from what gets served.
index_hash() { # pack file -> sha256 from index.toml (plain files) or the metafile (URL mods)
  python3 -I - "$T/packs/$1" "$2" <<'PY'
import sys, tomllib
from pathlib import Path
d, want = Path(sys.argv[1]), sys.argv[2]
idx = tomllib.loads((d / "index.toml").read_text())
for f in idx["files"]:
    if f.get("metafile"):
        m = tomllib.loads((d / f["file"]).read_text())
        if m["filename"] == want.split("/")[-1]:
            print(m["download"]["hash"]); break
    elif f["file"] == want:
        print(f["hash"]); break
PY
}
expect_file() { # dir relpath pack [packrel]
  local f="$1/$2" want; want="$(index_hash "$3" "${4:-$2}")"
  [[ -f "$f" ]] || fail "$2 missing in $(basename "$1")"
  [[ -n "$want" && "$(sha "$f")" == "$want" ]] || fail "$2 hash $(sha "$f") != index $want"
  ok "$(basename "$1"): $2 present, sha256 matches the pack"
}
expect_absent() { [[ ! -e "$1/$2" ]] || fail "$2 should not be in $(basename "$1")"; ok "$(basename "$1"): $2 absent"; }
# expect_refusal WHAT PATTERN CMD...: CMD (a publish) must fail, with PATTERN in its output
expect_refusal() {
  local what="$1" pat="$2"; shift 2
  if "$@" > "$T/logs/refusal.log" 2>&1; then fail "publish accepted $what"; fi
  grep -q -- "$pat" "$T/logs/refusal.log" || { mask < "$T/logs/refusal.log"; fail "publish refused $what, but not with '$pat'"; }
  ! grep -qF "$TOK" "$T/logs/refusal.log" || fail "publish printed the token while refusing $what"
  ok "publish refuses $what"
}
snapshot() { (cd "$1" && find . -type f ! -name 'packwiz.json' ! -path './logs/*' -printf '%p %s %T@\n' | sort); }

run_server() { (cd "$T/server-data" && java -cp "$installer" link.infra.packwiz.installer.Main -g -s server "$BASE/server/pack.toml") > "$T/logs/server-$1.log" 2>&1 || { mask < "$T/logs/server-$1.log"; fail "server sync ($1) failed"; }; }
run_client() { (cd "$MC" && java -jar packwiz-installer-bootstrap.jar -g -s client "$BASE/client/pack.toml") > "$T/logs/client-$1.log" 2>&1 || { mask < "$T/logs/client-$1.log"; fail "client sync ($1) failed"; }; }

step "0. publish refuses unsafe targets (RSYNC_RSH=false: nothing can connect anywhere)"
export RSYNC_RSH=false
expect_refusal "an empty remote path (host:, the remote home, becomes host:/)" "refusing TARGET" "$HERE/publish.sh" example.invalid:
expect_refusal "a remote '/'" "refusing TARGET" "$HERE/publish.sh" example.invalid:/
expect_refusal "a remote '~'" "refusing TARGET" "$HERE/publish.sh" example.invalid:~
expect_refusal "a remote folder without .tuxmine-packs" "no .tuxmine-packs" "$HERE/publish.sh" example.invalid:/srv/x/
expect_refusal "a local '/'" "refusing TARGET" "$HERE/publish.sh" /
mkdir -p "$T/nomarker"; touch "$T/nomarker/keep-me"
expect_refusal "a local folder without .tuxmine-packs" "no .tuxmine-packs" "$HERE/publish.sh" "$T/nomarker/"
[[ -f "$T/nomarker/keep-me" ]] || fail "a refused publish deleted files"
unset RSYNC_RSH

step "1. publish scratch packs with publish.sh"
publish || { mask < "$T/logs/publish.log"; fail "publish failed"; }
P="$T/srv/$TOK"
[[ -f "$P/client/pack.toml" && -f "$P/server/pack.toml" && -f "$P/index.html" && -f "$P/$(basename "$zip")" ]] || fail "publish tree incomplete"
ok "published <token>/client/, server/, index.html, $(basename "$zip")"
[[ -z "$(find "$T/srv" -mindepth 1 -maxdepth 1 ! -name "$TOK" ! -name .tuxmine-packs)" ]] || fail "something published outside the token dir: $(ls -A "$T/srv" | mask)"
ok "nothing published at the root, only the token dir (and the marker kept)"
! grep -qF "$TOK" "$T/logs/publish.log" || fail "publish output shows the token"
ok "publish output never shows the token"
grep -qF "/$TOK/$(basename "$zip")" "$P/index.html" && ok "index.html (behind the token) carries the zip link" || fail "index.html has no zip link"
mkdir -p "$T/srv/junk"; for i in $(seq 1 10); do touch "$T/srv/junk/f$i"; done
if TUXMINE_MAX_DELETE=5 publish; then fail "publish deleted 11 stray entries with TUXMINE_MAX_DELETE=5"; fi
grep -q "stopped deleting" "$T/logs/publish.log" || { mask < "$T/logs/publish.log"; fail "max-delete run failed for another reason"; }
[[ -f "$P/client/pack.toml" && -f "$T/srv/.tuxmine-packs" ]] || fail "max-delete run lost published files"
ok "--max-delete stops a publish that would delete more than TUXMINE_MAX_DELETE entries"
rm -rf "$T/srv/junk"
[[ ! -e "$P/client/README.md" && ! -e "$P/client/.packwizignore" ]] || fail ".packwizignore'd file was published"
ok ".packwizignore'd files not published"

step "2. Caddy ($CADDY_IMAGE) on $ROOTURL/<token>"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
# Same hardening as deploy/compose.snippet.yaml.
docker run -d --name "$CONTAINER" -p "127.0.0.1:$PORT:8073" \
  --read-only --tmpfs /data --tmpfs /config --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --health-cmd 'wget -q -O /dev/null http://127.0.0.1:8073/healthz' --health-interval 1s --health-start-period 1s \
  -v "$TUXMINE/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$T/srv:/srv/packs:ro" \
  "$CADDY_IMAGE" >/dev/null
for _ in $(seq 1 60); do [[ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" == healthy ]] && break; sleep 0.5; done
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" == healthy ]] || { docker logs "$CONTAINER" 2>&1 | mask; fail "caddy not healthy"; }
ok "caddy healthy (read-only rootfs, all caps dropped but NET_BIND_SERVICE, /healthz)"
header() { curl -fsSI "$BASE/$1" | tr -d '\r' | awk -v h="$2" 'tolower($0) ~ "^"tolower(h)":" {sub(/^[^:]*: */,""); print}'; }
check_header() {
  local got; got="$(header "$1" "$2")"
  [[ "$got" == "$3" ]] || fail "$1: $2 is '$got', want '$3'"
  ok "/${1}  $2: $got"
}
check_header client/pack.toml   Content-Type  "application/toml; charset=utf-8"
check_header client/pack.toml   Cache-Control "no-cache"
check_header server/index.toml  Cache-Control "no-cache"
check_header client/mods/$DB Content-Type  "application/java-archive"
check_header client/mods/$DB Cache-Control "public, max-age=86400"
check_header "$(basename "$zip")" Content-Type "application/zip"
check_header "" Cache-Control "no-cache"
code="$(curl -s -o /dev/null -w '%{http_code}' -H 'If-None-Match: '"$(header client/pack.toml ETag)" "$BASE/client/pack.toml")"
[[ "$code" == 304 ]] || fail "conditional GET on pack.toml returned $code, want 304"; ok "pack.toml revalidation: 304 Not Modified"
# hide .*: dotfiles that do exist (the marker; rsync's --delay-updates staging dir mid-publish)
# must 404, while the same file under a plain name is served (so the 404 is the hide rule).
mkdir -p "$P/.~tmp~/client" "$P/hidecontrol/client"
cp "$P/client/pack.toml" "$P/.~tmp~/client/pack.toml"; cp "$P/client/pack.toml" "$P/hidecontrol/client/pack.toml"
code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/hidecontrol/client/pack.toml")"
[[ "$code" == 200 ]] || fail "control file returned $code, want 200"
code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/.~tmp~/client/pack.toml")"
[[ "$code" == 404 ]] || fail "file in rsync's .~tmp~ dir served ($code)"
code="$(curl -s -o /dev/null -w '%{http_code}' "$ROOTURL/.tuxmine-packs")"
[[ "$code" == 404 ]] || fail "marker .tuxmine-packs served ($code)"
rm -rf "$P/.~tmp~" "$P/hidecontrol"
ok "dotfiles hidden: .~tmp~/client/pack.toml and /.tuxmine-packs 404, the same file under a plain name 200"
nm="${TOK:0:31}$([[ "${TOK:31:1}" == x ]] && echo y || echo x)${TOK:32}"
for u in "" index.html client/pack.toml server/pack.toml "$(basename "$zip")" "$nm/client/pack.toml"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --path-as-is "$ROOTURL/$u")"
  [[ "$code" == 404 ]] || fail "without the token, /${u/$nm/<near-miss token>} returned $code, want 404"
done
ok "without the token: /, /index.html, old paths, the zip and a near-miss token all 404"
code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/client/")"
[[ "$code" == 404 ]] || fail "directory listing at <token>/client/ returned $code"; ok "no directory listings (<token>/client/ 404)"
docker port "$CONTAINER" | grep -qvE '8073/tcp' && fail "unexpected published port" || ok "only 8073 published: $(docker port "$CONTAINER" | tr '\n' ' ')"

step "3. server pack -> scratch /data (packwiz-installer $INSTALLER_VER dist, -g -s server)"
run_server initial
expect_file "$T/server-data" mods/$DB server
expect_file "$T/server-data" mods/DiscordIntegrationUnoffical-mc1.7.10-3.1.1_3.8.3_464.jar server
expect_file "$T/server-data" mods/journeymap-1.7.10-5.2.23-unlimited.jar server
expect_file "$T/server-data" mods/gregguns-2ea0ea5.jar server
expect_file "$T/server-data" mods/fortunateone-v1.1.10.jar server
expect_file "$T/server-data" mods/worldedit-v0.0.9.jar server
expect_file "$T/server-data" config/fortunateone.cfg server
expect_absent "$T/server-data" mods/WorldEditCuiFe-v1.0.7-mf-1.7.10-10.13.4.1566.jar

step "4. client pack -> extracted instance zip's .minecraft (bundled bootstrap, -g -s client)"
python3 -I - "$zip" "$T/instance" <<'PY'
import sys, zipfile
from pathlib import Path, PurePosixPath
z, dest = zipfile.ZipFile(sys.argv[1]), Path(sys.argv[2]).resolve()
for i in z.infolist():
    p = PurePosixPath(i.filename)
    assert not p.is_absolute() and ".." not in p.parts, i.filename
    z.extract(i, dest)
PY
INST="$(dirname "$(find "$T/instance" -maxdepth 2 -name instance.cfg | head -n1)")"
MC="$INST/.minecraft"
grep -qx 'OverrideCommands=true' "$INST/instance.cfg" || fail "OverrideCommands not set"
pre="$(grep '^PreLaunchCommand=' "$INST/instance.cfg")"
[[ "$pre" == 'PreLaunchCommand=\"$INST_JAVA\" -jar packwiz-installer-bootstrap.jar '"$PUBLIC_BASE/$TOK"'/client/pack.toml' ]] || fail "PreLaunchCommand: $(mask <<<"$pre")"
ok "instance.cfg: PreLaunchCommand uses the token URL"
[[ -f "$MC/packwiz-installer-bootstrap.jar" ]] || fail "bootstrap jar missing"; ok "instance: .minecraft/packwiz-installer-bootstrap.jar"
expect_absent "$MC" mods/journeymap-1.7.10-5.2.23-fairplay.jar
ls "$MC/mods" | sort > "$T/logs/gtnh-mods-before.txt"
snapshot "$MC/mods" > "$T/logs/gtnh-mods-snap-before.txt"
run_client initial
expect_file "$MC" mods/$DB client
expect_file "$MC" mods/gregguns-2ea0ea5.jar client
expect_file "$MC" mods/journeymap-1.7.10-5.2.23-unlimited.jar client
expect_file "$MC" mods/fortunateone-v1.1.10.jar client
expect_file "$MC" mods/worldedit-v0.0.9.jar client
expect_file "$MC" mods/WorldEditCuiFe-v1.0.7-mf-1.7.10-10.13.4.1566.jar client
expect_file "$MC" config/findit.cfg client
expect_file "$MC" config/fortunateone.cfg client
expect_absent "$MC" mods/DiscordIntegrationUnoffical-mc1.7.10-3.1.1_3.8.3_464.jar
added="$(comm -13 "$T/logs/gtnh-mods-before.txt" <(ls "$MC/mods" | sort) | tr '\n' ' ')"
removed="$(comm -23 "$T/logs/gtnh-mods-before.txt" <(ls "$MC/mods" | sort) | tr '\n' ' ')"
want_added="$(printf '%s\n' $DB gregguns-2ea0ea5.jar fortunateone-v1.1.10.jar worldedit-v0.0.9.jar \
  WorldEditCuiFe-v1.0.7-mf-1.7.10-10.13.4.1566.jar journeymap-1.7.10-5.2.23-unlimited.jar | sort | tr '\n' ' ')"
[[ "$added" == "$want_added" && -z "$removed" ]] || fail "client mods changed beyond the pack's: +[$added] -[$removed]"
ok "client: GTNH's $(wc -l < "$T/logs/gtnh-mods-before.txt") mods untouched, only the pack's 6 jars added"

step "5a. unchanged pack: re-run is a no-op"
s_before="$(snapshot "$T/server-data")"; c_before="$(snapshot "$MC")"
run_server noop; run_client noop
[[ "$(snapshot "$T/server-data")" == "$s_before" ]] || fail "server re-run changed files"
[[ "$(snapshot "$MC")" == "$c_before" ]] || fail "client re-run changed files"
grep -qi "up to date" "$T/logs/server-noop.log" && grep -qi "up to date" "$T/logs/client-noop.log" || fail "no 'up to date' message on re-run"
ok "server: $(grep -i 'up to date' "$T/logs/server-noop.log" | head -n1 | sed 's/^.*\] *//')"
ok "client: $(grep -i 'up to date' "$T/logs/client-noop.log" | head -n1 | sed 's/^.*\] *//'); no file touched on either side"

step "5b. changed jar without refresh: publish refuses (index drift)"
newjar() { # src dst: a different, still valid jar
  python3 -I - "$1" "$2" <<'PY'
import shutil, sys, zipfile
shutil.copyfile(sys.argv[1], sys.argv[2])
with zipfile.ZipFile(sys.argv[2], "a") as z:
    z.writestr("tuxmine-test-marker.txt", "0.1.1 test build\n")
PY
}
for p in client server; do
  newjar "$T/packs/$p/mods/$DB" "$T/packs/$p/mods/davebridge-9.9.9-test.jar"
  rm "$T/packs/$p/mods/$DB"
done
idx_before="$(sha256sum "$T/packs/client/index.toml" "$T/packs/client/pack.toml")"
if publish; then fail "publish accepted a stale index"; fi
grep -q "index drift" "$T/logs/publish.log" || { mask < "$T/logs/publish.log"; fail "publish failed for another reason"; }
ok "publish: $(grep -m1 'index drift' "$T/logs/publish.log" | sed 's/^publish: //')"
[[ "$(sha256sum "$T/packs/client/index.toml" "$T/packs/client/pack.toml")" == "$idx_before" ]] || fail "the drift check modified the pack"
if publish; then fail "publish accepted a stale index on the second try"; fi
ok "the drift check leaves the pack untouched, so a plain re-run is refused again"

step "5b2. publish refuses secrets, a same-name jar change and a zip built for another token"
refresh client; refresh server   # past the drift check from here on
mkdir -p "$T/packs/client/config/Chikachi"
for f in config/davebridge.cfg config/Chikachi/DiscordIntegration.json server.properties; do
  mkdir -p "$(dirname "$T/packs/client/$f")"; echo '# harmless' > "$T/packs/client/$f"; refresh client
  expect_refusal "a known secret file ($f), whatever it holds" "never ship it" publish_to_srv
  rm "$T/packs/client/$f"
done
rmdir "$T/packs/client/config/Chikachi"
for s in '{"discord": {"token": "MTAxMjM0NTY3ODkw.Gabcde.fghijklmnopqrstuv"}}' '{"authToken": "0123456789abcdef0123"}' 'S:token=0123456789abcdef0123' 'rcon.password=correcthorsebattery'; do
  printf '%s\n' "$s" > "$T/packs/client/config/tuxmine-secret-test.json"; refresh client
  expect_refusal "a secret-looking value (${s%%[:=]*}...)" "looks like it contains a secret" publish_to_srv
done
rm "$T/packs/client/config/tuxmine-secret-test.json"
cp "$T/packs/client/mods/gregguns-2ea0ea5.jar" "$T/gregguns.orig"
newjar "$T/gregguns.orig" "$T/packs/client/mods/gregguns-2ea0ea5.jar"; refresh client
expect_refusal "a jar changed under its published file name" "same name with different content" publish_to_srv
cp "$T/gregguns.orig" "$T/packs/client/mods/gregguns-2ea0ea5.jar"; rm "$T/gregguns.orig"; refresh client
python3 -I - "$T/tuxmine-0.0.0-othertoken.zip" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("tuxmine (test)/instance.cfg",
               'PreLaunchCommand=\\"$INST_JAVA\\" -jar packwiz-installer-bootstrap.jar '
               "https://pack.example.net/0123456789abcdef0123456789abcdef/client/pack.toml\n")
PY
expect_refusal "a zip built for another token" "not built for the current pack token" \
  "$HERE/publish.sh" --zip "$T/tuxmine-0.0.0-othertoken.zip" "$T/srv/"

step "5c. update: davebridge 0.1.1 + new client config, versions bumped to test version 99.0.1"
mkdir -p "$T/packs/client/config"
printf '# tuxmine local test config\nhello=1\n' > "$T/packs/client/config/tuxmine-test.cfg"
for p in client server; do set_version $p 99.0.1; refresh $p; done
# Strays the protect filter must not keep: a zip at the root (pre-token layout) and a rotated-out
# token's directory, zip included. This token's older zip must be kept.
OLDTOK="oldtokenoldtokenoldtoken0000"
mkdir -p "$T/srv/$OLDTOK/client"
touch "$T/srv/tuxmine-0.0.1.zip" "$T/srv/tuxmine-0.0.1.zip.sha256" "$T/srv/$OLDTOK/tuxmine-0.0.1.zip" \
      "$T/srv/$OLDTOK/client/pack.toml" "$P/tuxmine-0.0.1.zip" "$P/tuxmine-0.0.1.zip.sha256"
publish || { mask < "$T/logs/publish.log"; fail "publish after refresh failed"; }
ok "publish accepted the refreshed, bumped packs"
[[ ! -e "$P/client/mods/$DB" ]] || fail "stale jar left on the pack host"; ok "pack host: old jar deleted by rsync"
[[ ! -e "$T/srv/tuxmine-0.0.1.zip" && ! -e "$T/srv/tuxmine-0.0.1.zip.sha256" ]] || fail "root-level zip kept (protect filter not anchored)"
[[ ! -e "$T/srv/$OLDTOK" ]] || fail "rotated-out token dir kept: $(find "$T/srv/$OLDTOK" | sed "s|$T/srv/||")"
[[ -f "$P/tuxmine-0.0.1.zip" && -f "$P/tuxmine-0.0.1.zip.sha256" && -f "$T/srv/.tuxmine-packs" ]] || fail "this token's older zip or the marker was deleted"
ok "pack host: root-level zip and old token dir deleted; this token's older zip and the marker kept"
rm "$P/tuxmine-0.0.1.zip" "$P/tuxmine-0.0.1.zip.sha256"
run_server update; run_client update
expect_file "$T/server-data" mods/davebridge-9.9.9-test.jar server
expect_absent "$T/server-data" mods/$DB
expect_file "$MC" mods/davebridge-9.9.9-test.jar client
expect_absent "$MC" mods/$DB
expect_file "$MC" config/tuxmine-test.cfg client

step "5d. removal: JourneyMap Unlimited out of the server pack, test config out of the client pack (99.0.2)"
(cd "$T/packs/server" && "$PACKWIZ" remove journeymap-unlimited >/dev/null)
rm "$T/packs/client/config/tuxmine-test.cfg"
for p in client server; do set_version $p 99.0.2; refresh $p; done
publish || { mask < "$T/logs/publish.log"; fail "publish failed"; }
run_server remove; run_client remove
expect_absent "$T/server-data" mods/journeymap-1.7.10-5.2.23-unlimited.jar
expect_file "$T/server-data" mods/DiscordIntegrationUnoffical-mc1.7.10-3.1.1_3.8.3_464.jar server
expect_file "$T/server-data" mods/davebridge-9.9.9-test.jar server
expect_absent "$MC" config/tuxmine-test.cfg
expect_file "$MC" mods/davebridge-9.9.9-test.jar client
ours='davebridge|gregguns-2ea0ea5|fortunateone|worldedit-v0.0.9|WorldEditCuiFe|journeymap-1.7.10-5.2.23-unlimited'
[[ "$(snapshot "$MC/mods" | grep -vE "$ours")" == "$(grep -vE "$ours" "$T/logs/gtnh-mods-snap-before.txt")" ]] \
  || fail "GTNH's own client mods changed during the test"
ok "client: GTNH's own mods byte-for-byte untouched across all syncs"

step "6. compose snippet merged onto a stub stack: gtnh_2 fetches PACKWIZ_URL over the stack network"
mkdir -p "$T/compose"
cp "$TUXMINE/deploy/Caddyfile" "$T/compose/Caddyfile"
cp -al "$T/srv" "$T/compose/packs"
cat > "$T/compose/docker-compose.yaml" <<'YAML'
# Stand-in for /opt/gtnh/docker-compose.yaml after the hand edit (MODS deleted, as DEPLOY.md
# says): gtnh_2 is a busybox that does what itzg's handlePackwiz does first, i.e. fetch
# $PACKWIZ_URL and the files it lists. It fails if MODS is set at all: an empty-but-set MODS
# makes itzg delete the jars packwiz just installed, so the snippet must not (re)introduce it.
services:
  gtnh_2:
    image: busybox:1.37.0
    environment:
      TYPE: CUSTOM
    command: ["sh", "-c", "[ -z \"$${MODS+set}\" ] || { echo MODS-IS-SET; exit 1; }; wget -q -O - \"$$PACKWIZ_URL\" && wget -q -O /dev/null \"$${PACKWIZ_URL%/pack.toml}/mods/davebridge-9.9.9-test.jar\" && echo FETCH-OK"]
YAML
cat > "$T/compose/test-override.yaml" <<'YAML'
services:
  caddy:
    ports: !reset []      # don't grab host port 8073 during the test
YAML
dc() { docker compose -p "$COMPOSE_PROJECT" --project-directory "$T/compose" -f "$T/compose/docker-compose.yaml" \
         -f "$TUXMINE/deploy/compose.snippet.yaml" -f "$T/compose/test-override.yaml" "$@"; }
dc config --quiet || fail "merged compose config is invalid"
ok "snippet merges onto a base compose (docker compose config)"
dc config --format json | python3 -I -c 'import json,sys; e=json.load(sys.stdin)["services"]["gtnh_2"].get("environment") or {}; sys.exit("MODS" in e)' \
  || fail "the merged gtnh_2 environment has MODS; the snippet must not set it"
ok "merged gtnh_2 has no MODS"
dc up --wait -d caddy >/dev/null 2>&1 || { dc logs caddy 2>&1 | mask; fail "caddy service not healthy"; }
ok "caddy service healthy with the snippet's hardening and healthcheck"
dc run --rm gtnh_2 > "$T/logs/compose-gtnh2.log" 2>&1 || { mask < "$T/logs/compose-gtnh2.log"; fail "gtnh_2 stub could not fetch from caddy"; }
grep -q 'name = "tuxmine-server"' "$T/logs/compose-gtnh2.log" && grep -q FETCH-OK "$T/logs/compose-gtnh2.log" \
  || { mask < "$T/logs/compose-gtnh2.log"; fail "unexpected gtnh_2 output"; }
ok "gtnh_2 -> http://caddy:8073/<token>/server/pack.toml and a mod jar fetched inside the stack"
dc down -v --remove-orphans >/dev/null 2>&1

echo
echo "All $pass checks passed. Logs: $T/logs/"
