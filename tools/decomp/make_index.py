#!/usr/bin/env python3
"""Generate gtnh-src/INDEX.md.

usage: make_index.py CONFIG.json
CONFIG keys: pack_mods, results, src_root, manifest, assets, header_md (path to a markdown file
with the preamble), out
"""
import json, os, re, sys, zipfile


def lenient_json(txt):
    txt = txt.lstrip('\ufeff')
    for attempt in (txt, re.sub(r',\s*([\]}])', r'\1', re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', txt))):
        try:
            return json.loads(attempt, strict=False)
        except Exception:
            pass
    return None


def mcmod_info(jar):
    try:
        z = zipfile.ZipFile(jar)
        n = next((n for n in z.namelist() if n.lower() == 'mcmod.info'), None)
        if not n:
            return []
        raw = z.read(n).decode('utf-8', 'replace')
    except Exception:
        return []
    d = lenient_json(raw)
    if isinstance(d, dict):
        d = d.get('modList') or d.get('modlist') or [d]
    if isinstance(d, list):
        return [m for m in d if isinstance(m, dict)]
    # regex fallback
    return [{'modid': a, 'name': b, 'version': ''} for a, b in
            re.findall(r'"modid"\s*:\s*"([^"]+)"[\s\S]*?"name"\s*:\s*"([^"]*)"', raw)]


MOD_ANN = re.compile(r'@Mod\(\s*(?:[^)]*?\b)?modid\s*=\s*"([^"]+)"', re.S)
MOD_ANN_CONST = re.compile(r'@Mod\(\s*(?:[^)]*?\b)?modid\s*=\s*([A-Za-z_][\w.]*)', re.S)


def mod_annotations(d):
    ids = set()
    for dp, _, fs in os.walk(d):
        for f in fs:
            if f.endswith(('.java', '.kt')):
                try:
                    s = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
                except Exception:
                    continue
                if '@Mod(' in s:
                    ids.update(MOD_ANN.findall(s))
    return sorted(ids)


def esc(s):
    return str(s).replace('|', '\\|').replace('\n', ' ').strip()


def main(cfg_path):
    c = json.load(open(cfg_path))
    results = json.load(open(c['results']))
    man = json.load(open(c['manifest']))
    assets = {m['name']: m for m in json.load(open(c['assets']))['mods']}
    by_file = {}
    for section in ('github_mods', 'external_mods'):
        for name, v in man.get(section, {}).items():
            a = assets.get(name)
            if not a:
                continue
            ver = next((x for x in a['versions'] if x['version_tag'] == v['version']), None)
            if ver and ver.get('filename'):
                url = a.get('repo_url') or a.get('external_url') or ''
                tag = ''
                if a.get('repo_url') and 'github.com' in a['repo_url']:
                    tag = f"{a['repo_url']}/tree/{v['version']}"
                by_file[ver['filename']] = {'pack_name': name, 'url': url, 'tag_url': tag,
                                            'license': a.get('license', ''), 'side': v.get('side', '')}
    rows = []; failed = []; skipped = []
    for jb in sorted(results, key=str.lower):
        r = results[jb]
        jar = os.path.join(c['pack_mods'], r['rel'])
        infos = mcmod_info(jar)
        meta = by_file.get(jb, {})
        out_rel = f"mods/{r['out']}/"
        ann = mod_annotations(os.path.join(c['src_root'], 'mods', r['out'])) if r['status'] == 'ok' else []
        modids = [m.get('modid', '') for m in infos if m.get('modid')]
        modid = ', '.join(modids) if modids else (', '.join(ann) + ' (@Mod)' if ann else '-')
        name = '; '.join(dict.fromkeys(m.get('name', '') for m in infos if m.get('name'))) or meta.get('pack_name', '-')
        ver = '; '.join(dict.fromkeys(str(m.get('version', '')) for m in infos if m.get('version'))) or '-'
        src = meta.get('tag_url') or meta.get('url') or ''
        if not src:
            urls = [m.get('url', '') for m in infos if 'github.com' in str(m.get('url', ''))]
            src = (urls[0] + ' (mcmod.info)') if urls else ''
        status = r['status']
        if status == 'skipped':
            skipped.append(jb)
        elif status != 'ok':
            failed.append(jb)
        origin = r.get('origin', status)
        if origin == 'sources-jar':
            origin = f"sources-jar ({r['sources_url']})"
            nfiles = r.get('source_files', 0)
        else:
            nfiles = r.get('java_files', 0)
        if r.get('note'):
            origin += ' - ' + r['note']
        rows.append((jb, modid, name, ver, origin, out_rel if status == 'ok' else f'({status})',
                     nfiles, meta.get('pack_name', ''), src))
    lines = ['Verified real source: see SOURCE-INDEX.md', '', open(c['header_md']).read().rstrip(), '', '## Mod jars', '',
             f'{len(rows)} jars in the pack `mods/`. `origin`: `sources-jar` = the maven `-sources.jar` of the exact '
             'version shipped (pack jar SHA-1 == maven jar SHA-1), extracted as-is with MCP names; '
             '`decompiled` = Vineflower output with SRG->MCP remap. `files` = source files written '
             '(.java/.kt/.scala; for decompiled jars, top-level classes). `pack name` comes from the GTNH '
             'DreamAssemblerXXL 2.9.0 release manifest; the last column is an UNVERIFIED HINT taken from that '
             'manifest / mcmod.info, not a checked source location.', '',
             '| jar | modid(s) | name | version (mcmod.info) | origin | output dir | files | pack name | upstream repo (unverified hint) |',
             '|---|---|---|---|---|---|---|---|---|']
    for row in rows:
        lines.append('| ' + ' | '.join(esc(x) for x in row) + ' |')
    reasons = {'forgelin-2.0.3-GTNH.jar': 'Kotlin stdlib + kotlinx.coroutines/reflect (3,793 classes of third-party library code)',
               '+unimixins-all-1.7.10-0.3.1.jar': 'SpongePowered Mixin + MixinExtras framework and shaded libraries (3,621 classes); upstream LegacyModdingMC/UniMixins'}
    lines += ['', '## Skipped jars', ''] + ([f'- `{s}`: {reasons.get(s, "")}' for s in skipped] or ['- none'])
    lines += ['', '## Failed jars', ''] + ([f'- `{s}`' for s in failed] or ['- none'])
    # Keep the "Tuxmine extras" block that tools/decomp/tuxmine_extras.py appends: regenerating the GTNH part must
    # not drop it. Rerun tuxmine_extras.py after a pack update to refresh it.
    extras = ''
    if os.path.isfile(c['out']):
        m = re.search(r'<!-- tuxmine-extras:begin -->.*?<!-- tuxmine-extras:end -->\n?', open(c['out']).read(), re.S)
        extras = m.group(0) if m else ''
    with open(c['out'], 'w') as f:
        f.write('\n'.join(lines) + '\n' + ('\n' + extras if extras else ''))
    print(f'rows={len(rows)} skipped={len(skipped)} failed={len(failed)} no_hint={sum(1 for r in rows if not r[8])}')


if __name__ == '__main__':
    main(sys.argv[1])
