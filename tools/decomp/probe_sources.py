#!/usr/bin/env python3
"""Find same-version -sources.jar artifacts on the GTNH maven for each pack mod jar.

Maps jar filename -> (pack mod name, version, repo) through the DreamAssemblerXXL release manifest
and gtnh-assets.json, then HEADs
  <MAVEN>/com/github/GTNewHorizons/<artifact>/<version>/<artifact>-<version>-sources.jar
for artifact candidates (repo name, pack mod name). Also fetches <artifact>-<version>.jar.sha1 and
compares it with the pack jar's SHA-1 (binary_match).

usage: probe_sources.py PACK_MODS_DIR MANIFEST.json ASSETS.json OUT.json
"""
import hashlib, json, os, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

MAVEN = 'https://nexus.gtnewhorizons.com/repository/public/com/github/GTNewHorizons'


def req(url, method='GET'):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method,
                                    headers={'User-Agent': 'gtnh-src-builder'}), timeout=60) as r:
            return r.status, (r.read() if method == 'GET' else b'')
    except urllib.error.HTTPError as e:
        return e.code, b''
    except Exception:
        return 0, b''


def main(mods, manifest, assets_p, out):
    man = json.load(open(manifest))
    assets = {m['name']: m for m in json.load(open(assets_p))['mods']}
    by_file = {}
    for section in ('github_mods', 'external_mods'):
        for name, v in man.get(section, {}).items():
            a = assets.get(name)
            ver = a and next((x for x in a['versions'] if x['version_tag'] == v['version']), None)
            if ver and ver.get('filename'):
                by_file[ver['filename']] = (name, v['version'], a.get('repo_url') or '')
    jars = sorted(f for f in os.listdir(mods) if f.endswith('.jar'))

    def probe(jb):
        r = {'jar': jb}
        if jb not in by_file:
            r['status'] = 'not-in-manifest'; return r
        name, ver, repo = by_file[jb]
        r.update(pack_name=name, version=ver)
        cands = list(dict.fromkeys(c for c in (repo.rstrip('/').rsplit('/', 1)[-1] if 'GTNewHorizons/' in repo else '', name) if c))
        for art in cands:
            base = f'{MAVEN}/{art}/{ver}/{art}-{ver}'
            st, _ = req(base + '-sources.jar', 'HEAD')
            if st == 200:
                r.update(status='found', artifact=art, sources_url=base + '-sources.jar')
                st2, body = req(base + '.jar.sha1')
                local = hashlib.sha1(open(os.path.join(mods, jb), 'rb').read()).hexdigest()
                r['binary_sha1_maven'] = body.decode().split()[0] if st2 == 200 and body else None
                r['binary_sha1_pack'] = local
                r['binary_match'] = r['binary_sha1_maven'] == local
                return r
        r['status'] = 'no-sources-jar'; r['tried'] = cands
        return r

    with ThreadPoolExecutor(6) as ex:
        res = {r['jar']: r for r in ex.map(probe, jars)}
    json.dump(res, open(out, 'w'), indent=1)
    from collections import Counter
    print(Counter(r['status'] for r in res.values()),
          'binary_match:', Counter(r.get('binary_match') for r in res.values() if r['status'] == 'found'))


if __name__ == '__main__':
    main(*sys.argv[1:5])
