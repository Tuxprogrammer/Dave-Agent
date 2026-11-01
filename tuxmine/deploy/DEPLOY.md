# Deploying the tuxmine pack host

For the owner of `game-host` (root on `/opt/gtnh`).

**Status (2026-11-01): live.**
- Step 1: DNS already resolves through the `*.example.net` wildcard (DNS only).
- Steps 2-5 and 7 are done. Step 6 was covered by the local test, and the live switch went cleanly. Everything is now published under the secret `<token>/` path.
- Step 2: NPM proxy host 54 exists, with the rate limits (step 2b). Backups on store: `database.sqlite.bak-tuxmine-ratelimit-20261101`, `http.conf.bak-…`, `proxy_host-54.conf.bak-…`.
- **Open:**
  - Create the publish marker (step 3): `publish.sh` now refuses a target without `/opt/gtnh/packs/.tuxmine-packs`.
  - Re-paste `npm/advanced.conf` into host 54's Advanced tab (step 2b). It now sets the 429 status itself.
- Rollback points: `docker-compose.yaml.bak-pre-tuxmine-packwiz`, and the ZFS snapshot `rpool/ROOT/cos@gtnh-pre-tuxmine-packwiz` (taken with the server stopped).

When you're done:

```
player ──HTTPS──> Nginx Proxy Manager (proxy-host.example.net, :443, TLS) ──HTTP──> desktop :8073 ── caddy ── /opt/gtnh/packs (read-only)
gtnh_2 ──HTTP──> caddy:8073 (inside the gtnh stack network)
```

- **Caddy only serves plain HTTP, on port 8073.** It has no certificates, no secrets and no Cloudflare module.
- **TLS ends at NPM.** The public URLs are:
  - `https://pack.example.net/<token>/client/pack.toml`
  - `https://pack.example.net/<token>/server/pack.toml`
  - `https://pack.example.net/<token>/tuxmine-<version>.zip`
  - `https://pack.example.net/<token>/`, the player instructions.
  - Everything else, `https://pack.example.net/` included, is a 404.
- **Ports 80 and 443 on the desktop stay untouched.**
- **No router port forward is needed.** NPM reaches the desktop over the LAN.

Files in this folder:

| File | Goes to |
|---|---|
| `Caddyfile` | `/opt/gtnh/Caddyfile` |
| `compose.snippet.yaml` | merged by hand into `/opt/gtnh/docker-compose.yaml` |
| `npm/http.tuxmine.conf` | appended to `/data/nginx/custom/http.conf` in NPM on store (step 2b) |
| `npm/advanced.conf` | NPM proxy host 54, **Advanced** tab (step 2b) |

## 1. DNS for pack.example.net

Point `pack.example.net` wherever your other NPM-fronted names point: an A record to the router's public IP, or a CNAME to an existing name.

If example.net is on Cloudflare, prefer **DNS only (grey cloud)** for this name. The instance zip is about 714 MiB, which is over Cloudflare's per-file cache limit, and the free plan's terms frown on proxying large non-web downloads. It works either way, but grey cloud keeps Cloudflare out of the path.

## 2. Nginx Proxy Manager: proxy host

**Hosts → Proxy Hosts → Add Proxy Host**:

- **Details**
  - Domain Names: `pack.example.net`
  - Scheme: `http`
  - Forward Hostname/IP: the desktop's LAN IP (`getent hosts game-host.example.net`)
  - Forward Port: `8073`
  - Cache Assets: **off**. Caddy sends its own `Cache-Control`: `pack.toml` and `index.toml` must always be revalidated.
  - Block Common Exploits: on is fine
  - Websockets: not needed
- **SSL**: request a Let's Encrypt certificate, then turn on Force SSL and HTTP/2.
- **Advanced**: the contents of `npm/advanced.conf` (step 2b). Also check this for the big zip download:
  - `client_max_body_size` doesn't matter: it limits uploads, and nothing is uploaded.
  - By default nginx buffers proxied responses and spools large ones to a temp file, capped at `proxy_max_temp_file_size`, 1 GiB by default. A slow player download can also hit the read timeout.
  - If downloads of the zip stall or cut off, add these below the rate-limit block:

    ```nginx
    proxy_max_temp_file_size 0;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    ```
  - **Never add `proxy_buffering off`.** Unbuffered, nginx ignores `limit_rate`, and zips go out at full line speed (measured: ~950 MB/s instead of 26 MB/s). `scripts/test-ratelimit.sh` fails if `advanced.conf` turns it off.

## 2b. Nginx Proxy Manager: rate limits

On store (NPM's data directory, as root). Back up first, as with the existing `*.bak-tuxmine-ratelimit-20261101` files:

1. Append `npm/http.tuxmine.conf` to `/data/nginx/custom/http.conf` (http level, next to the other custom zones). Do this once; on a later change, replace the block between `# --- tuxmine pack host` and `# --- end tuxmine`.
2. In host 54's **Advanced** tab, paste the whole of `npm/advanced.conf` (it is stored in NPM's database, so the GUI is the place to change it). It includes `limit_req_status 429` and `limit_conn_status 429`, so it doesn't rely on `http.conf` for those.
3. `nginx -t` inside the NPM container, then reload (`nginx -s reload`). Saving the host in the GUI also reloads.
4. Check from outside the LAN: a zip download runs at about 26 MB/s, and a second parallel zip download from the same address gets a 429. From the LAN, neither applies.

Run `tuxmine/scripts/test-ratelimit.sh` locally before changing either file.

## 3. Folder and Caddyfile on the desktop

```sh
sudo mkdir /opt/gtnh/packs
sudo chown deploy: /opt/gtnh/packs          # publish.sh rsyncs as deploy
touch /opt/gtnh/packs/.tuxmine-packs            # as deploy: the marker publish.sh requires
sudo cp tuxmine/deploy/Caddyfile /opt/gtnh/Caddyfile
```

Caddy mounts both read-only. The marker tells `publish.sh` that this folder is the pack root. It refuses any target without it, because the sync deletes everything else in the target. Caddy never serves it (dotfiles are hidden).

## 4. First publish

From this repo, on the laptop:

```sh
python3 -I tuxmine/scripts/build-instance.py      # builds .work/tuxmine/out/tuxmine-<version>.zip
tuxmine/scripts/publish.sh --dry-run deploy@game-host.example.net:/opt/gtnh/packs/
tuxmine/scripts/publish.sh           deploy@game-host.example.net:/opt/gtnh/packs/
```

`publish.sh` refuses to run without a target, or with one that lacks `.tuxmine-packs`. It fails if `packwiz refresh` would change either pack, which means the index is stale. It never prints the token; the player page is `https://pack.example.net/<token>/`.

## 5. Add the caddy service, and only that

Back up first:

```sh
cd /opt/gtnh
sudo cp -n docker-compose.yaml docker-compose.yaml.bak-pre-tuxmine-packwiz   # -n: never overwrite the existing rollback point
```

Merge **only the `caddy:` service** from `compose.snippet.yaml` into `docker-compose.yaml`. Leave `gtnh_2` alone for now. Then:

```sh
sudo docker compose config --quiet                # syntax check
sudo docker compose up -d caddy                   # creates caddy only; gtnh_2 is not touched
sudo docker compose ps caddy                      # wait for "healthy"
```

Check it:

```sh
curl -sI http://localhost:8073/<token>/server/pack.toml    # 200, application/toml, Cache-Control: no-cache
curl -sI http://localhost:8073/server/pack.toml            # 404: nothing without the token
curl -sI http://localhost:8073/                             # 404
curl -s  http://localhost:8073/healthz                      # ok
curl -sI https://pack.example.net/<token>/client/pack.toml          # same headers, through NPM
curl -so /dev/null -w '%{http_code} %{size_download}\n' https://pack.example.net/<token>/tuxmine-<version>.zip
                                                            # 200 and the full size; check it from outside the LAN too
sudo ss -ltnp | grep -E ':(80|443)\b'                       # nothing new on 80/443
```

## 6. Test the server side on a throwaway container

Don't test on the live server. `gregguns-test-server` is a standalone container on the default bridge network, so it can't resolve `caddy`. Use a one-off itzg container on the stack network instead, with a scratch `/data`.

Use the same GTNH server zip the live server is about to run. The live server's `GENERIC_PACK` is currently `/gtnh2-pack/gtnh-server-beta.zip`; substitute the 2.9.0 file once it's there.

```sh
mkdir -p ~/packtest-data
sudo docker run --rm -it --name packtest \
  --network gtnh_default -p 25592:25565 \
  -e EULA=TRUE -e TYPE=CUSTOM -e VERSION=LATEST \
  -e CUSTOM_SERVER=lwjgl3ify-forgePatches.jar \
  -e GENERIC_PACK=/gtnh2-pack/gtnh-server-beta.zip \
  -e PACKWIZ_URL=http://caddy:8073/<token>/server/pack.toml \
  -e MEMORY=6G -e UID=$(id -u) -e GID=$(id -g) \
  -v /opt/gtnh/gtnh2-pack:/gtnh2-pack:ro \
  -v ~/packtest-data:/data \
  itzg/minecraft-server:java25
```

Expect:

- `Running packwiz installer against URL: http://caddy:8073/<token>/server/pack.toml`, then the generic pack.
- `~/packtest-data/mods/` has `davebridge-*.jar`, `gregguns-2ea0ea5.jar`, `DiscordIntegrationUnoffical-…jar` and `journeymap-1.7.10-5.2.23-unlimited.jar` exactly once, next to GTNH's mods.
- The server reaches "Done". Join it on port 25592 with an instance imported from the zip.
- Stop it with Ctrl-C, run it again, and the log says `Modpack is already up to date!`.

Clean up afterwards: `rm -rf ~/packtest-data`.

## 7. Switch gtnh_2 to the server pack, in a planned restart window

Edit `gtnh_2` in `docker-compose.yaml` as in the snippet:

- **Add** `PACKWIZ_URL: "http://caddy:8073/<token>/server/pack.toml"`.
- **Delete the `MODS` entry entirely.**
  - Don't leave it as `MODS: ""`. An empty-but-set `MODS` makes itzg's `mcopy` clean up the jars it installed before. Those have the same file names packwiz just installed, so DiscordIntegration and JourneyMap would be deleted until the next restart.
  - A removed `MODS` is never looked at. packwiz adopts the existing identical jars ("already exists (validated)"), so there is one copy of each.
- **Add** `depends_on: caddy: condition: service_healthy`.
- GregGuns ships through the server pack (`gregguns-2ea0ea5.jar`). If the hand-placed jar in `/data/mods` has a different name by then, delete it in the same window.

Then:

```sh
sudo docker compose config --quiet
sudo docker compose up -d gtnh_2                  # recreates gtnh_2 with the new env
sudo docker compose logs -f gtnh_2                # look for the packwiz lines, then normal startup
```

**If the pack can't be fetched, the server won't start.** With `PACKWIZ_URL` set, itzg exits when packwiz-installer fails. A broken publish or a stopped caddy blocks the server's next start. Keep caddy running, and test publishes with the throwaway container in step 6 when in doubt.

- **After a reboot**, `depends_on` doesn't apply: docker restarts containers itself, in no particular order. If `gtnh_2` comes up before caddy, packwiz fails and itzg exits; `restart: unless-stopped` starts it again, with a growing delay, until caddy answers.
- **URL mods** (DiscordIntegration from edge.forgecdn.net, JourneyMap Unlimited from cdn.modrinth.com, WorldEdit and Fortunate One from github.com) are downloaded from those hosts, not from caddy, whenever one is missing or changed. If such a host is down right after a pack change or a `mods/` wipe, the server doesn't start until it's back. Ordinary restarts download nothing.

## Rollback

Each level is independent. Stop at the first one that fixes it.

1. **Bad pack contents.** Fix the pack in the repo, bump `version`, run `publish.sh` again, then restart gtnh_2. To go back to the previous pack, put back the previous pack files, bump the version past the broken one, refresh, and publish.
   - The repo isn't in git, so keep that copy yourself: before changing a pack, `cp -a tuxmine/server .work/tuxmine/server-<version>` (same for `client`).
   - Without a copy, the host still has the last published pack until you publish again: `rsync -r deploy@game-host.example.net:/opt/gtnh/packs/<token>/server/ .work/tuxmine/server-restore/` (it holds `pack.toml`, `index.toml` and every listed file, so it is a complete pack folder).
2. **gtnh_2 won't start because of packwiz.** Restore the backup and recreate gtnh_2:
   ```sh
   sudo cp docker-compose.yaml.bak-pre-tuxmine-packwiz docker-compose.yaml
   sudo docker compose up -d gtnh_2
   ```
   The old `MODS` list downloads DiscordIntegration and JourneyMap again. DaveBridge and other pack-only jars that packwiz put in `/data/mods` stay there, because nothing removes them. Delete them by hand if you want them gone.
3. **Remove the pack host altogether.**
   ```sh
   sudo docker compose stop caddy && sudo docker compose rm -f caddy
   ```
   Then delete the `caddy:` service from the compose file. Remove the NPM proxy host and the DNS record. `/opt/gtnh/packs` and `/opt/gtnh/Caddyfile` can stay or go.
4. **Players.** With the pack host down, packwiz-installer reports the error and Prism stops the launch ("Pre-Launch command failed"). Nothing already installed is lost. Players can clear **Edit → Settings → Custom commands → Pre-launch command** to play stock GTNH plus whatever was last synced.

## Updating Caddy

The image is pinned by tag and digest in `compose.snippet.yaml`, which is the same pin `tuxmine/scripts/test-local.sh` uses. To move to a newer `caddy:2.x.y-alpine`:

1. Update both pins.
2. Run `tuxmine/scripts/test-local.sh`.
3. Merge the new pin and run `sudo docker compose up -d caddy`.
