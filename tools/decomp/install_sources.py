#!/usr/bin/env python3
"""Replace decompiled output with same-version -sources.jar content where available.

For each jar with status 'found' in the probe file:
  1. download the sources jar into DL_DIR (skipped if already present with the right size)
  2. move SRC_ROOT/mods/<out>/ to SRC_ROOT/_decompiled/<out>/ (kept as fallback)
  3. extract source files (.java/.kt/.scala/.groovy) + small text resources into SRC_ROOT/mods/<out>/
  4. overlay the non-source files from the decompiled dir (they come from the shipped binary jar:
     mcmod.info with the real version, lang files, mixin configs, refmaps)
Updates RESULTS (results.json) with origin / sources_url.

usage: install_sources.py PROBE.json RESULTS.json SRC_ROOT DL_DIR
"""
import json, os, shutil, sys, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

SRC_EXT = ('.java', '.kt', '.scala', '.groovy')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep_jar import KEEP_EXT, DROP_DIRS  # same resource filter as the decompile path


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    tmp = dest + '.part'
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'gtnh-src-builder'}), timeout=600) as r, open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)


def safe_member(n):
    return not (n.startswith('/') or '..' in n.split('/') or '\\' in n or ':' in n)


def install(p, r, root, dl):
    out = r['out']
    jar = os.path.join(dl, os.path.basename(p['sources_url']))
    download(p['sources_url'], jar)
    mods_dir = os.path.join(root, 'mods', out)
    dec_dir = os.path.join(root, '_decompiled', out)
    # mods/<out> is either a fresh decompile or our own earlier install of this sources jar.
    # decompile_mods.py rewrites a jar's results entry (dropping 'origin') whenever it decompiles
    # it again, so origin == 'sources-jar' means mods/<out> is still our install. Only a fresh
    # decompile may become the _decompiled/ fallback, and it must replace any older one: on a
    # regeneration a stale fallback would overlay the previous version's mcmod.info, mixin
    # configs and refmaps onto the new sources.
    if os.path.isdir(mods_dir) and r.get('origin') != 'sources-jar':
        shutil.rmtree(dec_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(dec_dir), exist_ok=True)
        shutil.move(mods_dir, dec_dir)
    shutil.rmtree(mods_dir, ignore_errors=True)
    os.makedirs(mods_dir)
    n_src = 0
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            n = info.filename
            if n.endswith('/') or not safe_member(n):
                continue
            ext = os.path.splitext(n)[1].lower()
            is_src = n.endswith(SRC_EXT)
            keep_res = (ext in KEEP_EXT or os.path.basename(n).lower() in ('mcmod.info', 'pack.mcmeta')) \
                and not DROP_DIRS.search(n) and info.file_size < 8 * 1024 * 1024
            if not (is_src or keep_res):
                continue
            dest = os.path.join(mods_dir, n)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as s, open(dest, 'wb') as d:
                shutil.copyfileobj(s, d)
            n_src += is_src
    n_res = 0
    if os.path.isdir(dec_dir):  # overlay shipped (binary-jar) resources
        for dp, _, fs in os.walk(dec_dir):
            for f in fs:
                if f.endswith(SRC_EXT):
                    continue
                s = os.path.join(dp, f)
                d = os.path.join(mods_dir, os.path.relpath(s, dec_dir))
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d); n_res += 1
    return out, n_src, n_res


def main(probe_p, results_p, root, dl):
    os.makedirs(dl, exist_ok=True)
    probe = json.load(open(probe_p)); results = json.load(open(results_p))
    todo = [(probe[j], results[j]) for j in results if probe.get(j, {}).get('status') == 'found'
            and results[j]['status'] == 'ok']
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(install, p, r, root, dl): r['jar'] for p, r in todo}
        for f in futs:
            jb = futs[f]
            try:
                out, n_src, n_res = f.result()
                results[jb].update(origin='sources-jar', sources_url=probe[jb]['sources_url'],
                                   source_files=n_src, decompiled_fallback=f'_decompiled/{out}/',
                                   binary_sha1_match=probe[jb]['binary_match'])
            except Exception as e:
                results[jb]['sources_error'] = repr(e)
                print('ERROR', jb, e, flush=True)
    for r in results.values():
        r.setdefault('origin', 'decompiled' if r['status'] == 'ok' else r['status'])
    json.dump(results, open(results_p, 'w'), indent=1)
    from collections import Counter
    print(Counter(r['origin'] for r in results.values()))


if __name__ == '__main__':
    main(*sys.argv[1:5])
