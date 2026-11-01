#!/usr/bin/env python3
"""Prep + decompile every mod jar with Vineflower, in parallel under a memory budget.

usage: decompile_mods.py PACK_MODS_DIR WORK_DIR OUT_MODS_DIR VINEFLOWER_JAR [--skip a.jar,b.jar] [--only x.jar]
Writes WORK_DIR/results.json (per-jar status) and WORK_DIR/logs/<name>.log.
"""
import argparse, json, os, re, shutil, subprocess, sys, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDES = {
    'industrialcraft-2-2.2.828-experimental': 'industrialcraft-2',
    'appliedenergistics2-rv3-beta-1095-GTNH': 'appliedenergistics2',
}
VERSIONISH = re.compile(r'^(v|mc|rv|r)?\d+([._]\d+)*([._-]?(gtnh|beta|alpha|rc\d*|experimental|universal|mapless|jenkins\d+|carrot|backhand|GTNH|final))*$', re.I)
TAGS = {'gtnh', 'beta', 'alpha', 'experimental', 'universal', 'mapless', 'carrot', 'all', 'backhand'}


def out_name(jar):
    stem = os.path.basename(jar)[:-4].lstrip('+')
    if stem in OVERRIDES:
        return OVERRIDES[stem]
    parts = re.findall(r'\[([^\]]*)\]', stem)
    base = re.split(r'[\[]', stem)[0].rstrip('-_ ')
    toks, keep = base.split('-'), []
    for i, t in enumerate(toks):
        if i > 0 and (VERSIONISH.match(t) or t.lower() in TAGS or re.match(r'^\d', t)):
            break
        keep.append(t)
    name = '-'.join(keep)
    name = re.sub(r'(?<=[A-Za-z])\d+\.\d.*$', '', name)  # JourneyMapServer1.0.5_MC1.7.10
    extra = [p for p in parts if not re.match(r'^(v|mc)?[\d.]+$', p, re.I)]
    if extra:
        name += '_' + '_'.join(extra)
    return name or stem


def class_count(jar):
    with zipfile.ZipFile(jar) as z:
        return sum(1 for n in z.namelist() if n.endswith('.class'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mods'); ap.add_argument('work'); ap.add_argument('out'); ap.add_argument('vf')
    ap.add_argument('--skip', default=''); ap.add_argument('--only', default='')
    ap.add_argument('--mem-budget-mb', type=int, default=16000)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=0, help='override per-jar heap (MB)')
    ap.add_argument('--threads', type=int, default=0, help='override per-jar Vineflower threads')
    a = ap.parse_args()
    skip = {s for s in a.skip.split(',') if s}
    jars = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(a.mods) for f in fs if f.endswith('.jar'))
    if a.only:
        jars = [j for j in jars if os.path.basename(j) in a.only.split(',')]
    names = {}
    for j in jars:
        n = out_name(j)
        if n in names.values():
            n = os.path.basename(j)[:-4]
        names[j] = n
    os.makedirs(os.path.join(a.work, 'prep'), exist_ok=True)
    os.makedirs(os.path.join(a.work, 'logs'), exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    res_path = os.path.join(a.work, 'results.json')
    results = json.load(open(res_path)) if os.path.exists(res_path) else {}
    lock = threading.Lock(); cond = threading.Condition(lock); used = [0]

    def run(j):
        jb = os.path.basename(j); name = names[j]
        r = {'jar': jb, 'rel': os.path.relpath(j, a.mods), 'out': name}
        if jb in skip:
            r['status'] = 'skipped'; return r
        prep = os.path.join(a.work, 'prep', name + '.jar')
        stats = os.path.join(a.work, 'prep', name + '.json')
        subprocess.run([sys.executable, '-I', os.path.join(HERE, 'prep_jar.py'), j, prep, stats], check=True)
        r['prep'] = json.load(open(stats))
        n = r['prep']['classes_out']
        mem = 6000 if n > 4000 else 3500 if n > 1500 else 2000 if n > 400 else 1200
        thr = 8 if n > 4000 else 4 if n > 400 else 2
        mem, thr = a.mem_mb or mem, a.threads or thr
        with cond:
            while used[0] + mem > a.mem_budget_mb and used[0] > 0:
                cond.wait()
            used[0] += mem
        dest = os.path.join(a.out, name)
        shutil.rmtree(dest, ignore_errors=True)
        t0 = time.time()
        log = os.path.join(a.work, 'logs', name + '.log')
        try:
            with open(log, 'w') as lf:
                p = subprocess.run(['java', f'-Xmx{mem}m', '-jar', a.vf, '--folder', '--log-level=warn',
                                    f'--thread-count={thr}', '--indent-string=    ',
                                    '--dump-bytecode-on-error=false', prep, dest],
                                   stdout=lf, stderr=subprocess.STDOUT, timeout=3600)
            r['rc'] = p.returncode
        except subprocess.TimeoutExpired:
            r['rc'] = 'timeout'
        finally:
            with cond:
                used[0] -= mem; cond.notify_all()
        r['secs'] = round(time.time() - t0, 1)
        java = sum(1 for dp, _, fs in os.walk(dest) for f in fs if f.endswith(('.java', '.kt')))
        r['java_files'] = java
        with open(log, errors='replace') as lf:
            txt = lf.read()
        r['errors'] = txt.count('ERROR') + txt.count('Exception')
        r['status'] = 'ok' if r['rc'] == 0 and (java > 0 or n == 0) else 'failed'
        print(f"[{r['status']}] {jb} -> {name}: {java}/{n} java, {r['secs']}s, rc={r['rc']}", flush=True)
        return r

    order = sorted(jars, key=lambda j: -class_count(j))
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(run, order):
            results[r['jar']] = r
            with open(res_path, 'w') as f:
                json.dump(results, f, indent=1)


if __name__ == '__main__':
    main()
