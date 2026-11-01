#!/usr/bin/env bash
# Functional test of the NPM rate limits in deploy/npm/ (http.tuxmine.conf + advanced.conf),
# against a stock nginx with those two files included exactly as NPM includes them: the zones
# at http level, advanced.conf at server level of a proxy host whose `location /` proxies to a
# backend (here a second server block standing in for Caddy). Nothing else sets the 429 status:
# advanced.conf must, as it has to on store.
#
#   tuxmine/scripts/test-ratelimit.sh
#
# Two throwaway docker networks: "out" (198.18.0.0/24, not in the LAN geo list, so limited) and
# "lan" (10.250.0.0/24, exempt). Touches nothing but its own containers, networks and
# .work/tuxmine/ratelimit/. Checks:
#   out: zip speed ~25 MB/s; a 2nd concurrent zip from one IP is refused; the 4th zip request in a
#        minute is refused; a 4th concurrent zip across IPs is refused; pack-file bursts above 60
#        are refused, all with 429.
#   lan: none of the above applies.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUXMINE="$(dirname "$HERE")"
W="$(dirname "$TUXMINE")/.work/tuxmine/ratelimit"
NGINX_IMAGE="nginx:1.27.5-alpine"
CURL_IMAGE="curlimages/curl:8.13.0"
P="tuxmine-rl"

pass=0
ok()   { echo "  PASS  $*"; pass=$((pass + 1)); }
fail() { echo "  FAIL  $*" >&2; exit 1; }
cleanup() {
  docker rm -f $(docker ps -aq --filter "name=^$P-") >/dev/null 2>&1 || true
  docker network rm "$P-out" "$P-lan" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

rm -rf "$W"; mkdir -p "$W/srv/tok/client"
truncate -s 400M "$W/srv/tok/tuxmine-9.9.9.zip"
echo 'name = "rl-test"' > "$W/srv/tok/client/pack.toml"
cat > "$W/nginx.conf" <<'EOF'
events {}
http {
    include /etc/tuxmine/http.tuxmine.conf;
    # Like an NPM proxy host: advanced.conf at server level, location / proxies upstream.
    # proxy_max_temp_file_size 0 only keeps the test from spooling 400 MB per download to disk.
    server {
        listen 80;
        include /etc/tuxmine/advanced.conf;
        location / {
            proxy_pass http://127.0.0.1:8073;
            proxy_set_header Host $host;
            proxy_max_temp_file_size 0;
        }
    }
    # Stand-in for Caddy: unlimited static files.
    server {
        listen 127.0.0.1:8073;
        root /srv;
        location / { }
    }
}
EOF

docker network create --subnet 198.18.0.0/24 "$P-out" >/dev/null
docker network create --subnet 10.250.0.0/24 "$P-lan" >/dev/null
docker run -d --name "$P-nginx" --network "$P-out" --ip 198.18.0.2 \
  -v "$W/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$TUXMINE/deploy/npm:/etc/tuxmine:ro" -v "$W/srv:/srv:ro" \
  "$NGINX_IMAGE" >/dev/null
docker network connect --ip 10.250.0.2 "$P-lan" "$P-nginx"
sleep 1
docker exec "$P-nginx" nginx -t >/dev/null 2>&1 || { docker logs "$P-nginx"; fail "nginx -t rejected the snippets"; }
ok "nginx -t accepts http.tuxmine.conf + advanced.conf"

# c NET IP ARGS...: curl from a fresh container with a fixed source address
c() { local net="$1" ip="$2"; shift 2; docker run --rm --network "$P-$net" --ip "$ip" "$CURL_IMAGE" -s "$@"; }
# csh NET IP SCRIPT: run a shell script with curl from one container (one source address)
csh() { local net="$1" ip="$2"; shift 2; docker run --rm --network "$P-$net" --ip "$ip" --entrypoint sh "$CURL_IMAGE" -c "$1"; }
cbg() { local name="$1" net="$2" ip="$3"; shift 3; docker run -d --name "$P-$name" --network "$P-$net" --ip "$ip" "$CURL_IMAGE" -s -o /dev/null "$@" >/dev/null; }
ZIP_OUT="http://198.18.0.2/tok/tuxmine-9.9.9.zip"
ZIP_LAN="http://10.250.0.2/tok/tuxmine-9.9.9.zip"
PACK_OUT="http://198.18.0.2/tok/client/pack.toml"

echo "== outside client (198.18.0.0/24)"
# 25m = 25 MiB/s = 26.2 MB/s. nginx gives a response a one-second head start (it allows
# rate * (elapsed + 1) bytes), so 8 s average out at up to 26.2 * 9/8 = 29.5 MB/s. This also
# fails if anything in advanced.conf turns proxy_buffering off: unbuffered, limit_rate is ignored.
speed="$(c out 198.18.0.10 -o /dev/null --max-time 8 -w '%{speed_download}' "$ZIP_OUT" || true)"
mbs=$(( ${speed%.*} / 1000000 ))
(( mbs >= 20 && mbs <= 31 )) || fail "zip speed ${mbs} MB/s, want ~26 (25 MiB/s)"
ok "zip download capped at ~${mbs} MB/s"

code="$(csh out 198.18.0.11 "curl -s -o /dev/null --max-time 6 $ZIP_OUT & sleep 1; curl -s -o /dev/null -w '%{http_code}' -r 0-0 $ZIP_OUT; kill %1 2>/dev/null")"
[[ "$code" == 429 ]] || fail "2nd concurrent zip from one IP got $code, want 429"
ok "2nd concurrent zip from the same IP: 429"

codes=""; for _ in 1 2 3 4; do codes+="$(c out 198.18.0.12 -o /dev/null -w '%{http_code}' -r 0-0 "$ZIP_OUT") "; done
[[ "$codes" == "206 206 206 429 " ]] || fail "4 quick zip requests from one IP: $codes, want 206 206 206 429"
ok "zip requests per IP per minute: $codes"

for i in 1 2 3; do cbg "all$i" out "198.18.0.2$i" --max-time 20 "$ZIP_OUT"; done; sleep 1
code="$(c out 198.18.0.30 -o /dev/null -w '%{http_code}' -r 0-0 "$ZIP_OUT")"
[[ "$code" == 429 ]] || fail "4th concurrent zip across IPs got $code, want 429"
ok "4th concurrent zip download across different IPs: 429"
for i in 1 2 3; do docker rm -f "$P-all$i" >/dev/null; done

burst="$(docker run --rm --network "$P-out" --ip 198.18.0.40 --entrypoint sh "$CURL_IMAGE" -c \
  'for i in $(seq 1 80); do curl -s -o /dev/null -w "%{http_code}\n" '"$PACK_OUT"'; done' | sort | uniq -c | tr -s ' ' | tr '\n' ',')"
[[ "$burst" == *" 200"* && "$burst" == *" 429"* ]] || fail "pack-file burst: $burst"
n200="$(echo "$burst" | grep -oE '[0-9]+ 200' | cut -d' ' -f1)"
(( n200 >= 60 && n200 <= 70 )) || fail "pack-file burst let $n200 through, want ~61"
ok "80 rapid pack-file requests: $burst (burst 60 + 10/s)"

echo "== LAN client (10.250.0.0/24)"
speed="$(c lan 10.250.0.10 -o /dev/null --max-time 10 -w '%{speed_download}' "$ZIP_LAN" || true)"
mbs=$(( ${speed%.*} / 1000000 ))
(( mbs > 60 )) || fail "LAN zip speed ${mbs} MB/s, should be unlimited"
ok "LAN zip download unlimited (${mbs} MB/s)"
codes="$(csh lan 10.250.0.11 "curl -s -o /dev/null --limit-rate 1M --max-time 8 $ZIP_LAN & sleep 1; for i in 1 2 3 4 5; do curl -s -o /dev/null -w '%{http_code} ' -r 0-0 $ZIP_LAN; done; kill %1 2>/dev/null")"
[[ "$codes" == "206 206 206 206 206 " ]] || fail "LAN zip requests: $codes"
ok "LAN: 5 zip requests during a running download: $codes"

echo
echo "All $pass checks passed."
