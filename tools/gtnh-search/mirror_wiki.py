"""Keeps an offline copy of wiki.gtnewhorizons.com for the `wiki` search kind: from Miraheze XML dumps, or (only with
the admins' permission) through the MediaWiki API.

  python3 -I tools/gtnh-search/mirror_wiki.py --check            robots.txt and license only (two requests)
  python3 -I tools/gtnh-search/mirror_wiki.py                    mirror or update (resumable); refuses if robots.txt
                                                                 disallows the API
  python3 -I tools/gtnh-search/mirror_wiki.py --ignore-robots    the same, overriding robots.txt: only with the wiki
                                                                 admins' permission
  python3 -I tools/gtnh-search/mirror_wiki.py --from-dump F.xml[.gz]  import a MediaWiki XML export (no network); this is
                                                                 how the wiki is fed, see update_wiki.py
  python3 -I tools/gtnh-search/mirror_wiki.py --reconvert        re-render text/ from raw/ after a converter change

Output in <corpus>/wiki/: raw/<file>.wiki (wikitext), text/<file>.txt (plain text, headings as Markdown) and
manifest.json (title -> file, pageid, revid, timestamp, url, categories). The wiki is CC BY-SA 4.0; keep the
attribution in the manifest. Politeness: one request at a time, about one per second, maxlag=5, and back-off on
errors and Retry-After. Page content is untrusted data: it is converted to text, never executed.
"""

import argparse
import gzip
import hashlib
import http.client
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semsearch as s  # noqa: E402

SITE = "https://wiki.gtnewhorizons.com"
API = SITE + "/w/api.php"
USER_AGENT = "Dave-Agent offline mirror (private, non-commercial)"
MIN_INTERVAL = 1.0
BATCH = 50
NAMESPACES = (0,)
# From the wiki's footer, checked 2026-10-31. Dumps don't carry it, so imports record it here.
LICENSE = "CC BY-SA 4.0 (wiki.gtnewhorizons.com)"


# Wikitext to plain text

def strip_nested(text, open_, close, repl):
    """Replaces innermost open_..close spans until none remain; repl gets the inner text."""
    pat = re.compile(re.escape(open_) + r"((?:(?!" + re.escape(open_) + r").)*?)" + re.escape(close), re.S)
    for _ in range(50):
        new = pat.sub(lambda m: repl(m.group(1)), text)
        if new == text:
            return new
        text = new
    return text


def split_params(inner):
    """Splits template parameters on the pipes that aren't inside a [[link|label]], so a linked field stays whole.
    Nested templates are already gone (strip_nested replaces innermost first)."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(inner):
        two = inner[i:i + 2]
        if two == "[[":
            depth, i = depth + 1, i + 2
        elif two == "]]" and depth:
            depth, i = depth - 1, i + 2
        else:
            if inner[i] == "|" and not depth:
                parts.append(inner[start:i])
                start = i + 1
            i += 1
    return parts + [inner[start:]]


def template(inner):
    """Block templates (infoboxes) keep their named fields as 'key: value' lines; inline templates are dropped."""
    parts = [p.strip() for p in split_params(inner)]
    if "\n" not in inner or len(parts) < 2:
        return ""
    fields = []
    for p in parts[1:]:
        k, sep, v = p.partition("=")
        if sep and v.strip() and not re.search(r"(image|icon|caption|style|width|color)", k, re.I):
            fields.append("%s: %s" % (k.strip(), v.strip()))
    return ("\n" + "\n".join(fields) + "\n") if fields else ""


def link(inner, cats):
    target, _, label = inner.partition("|")
    t = target.strip()
    low = t.lower().lstrip(":")
    if low.startswith("category:"):
        if not t.startswith(":"):
            cats.append(t.split(":", 1)[1].strip())
            return ""
        return label or t.split(":", 1)[1]
    if low.startswith(("file:", "image:", "media:")):
        return ""
    return (label or t.split("#")[0] or t).strip()


def table(block):
    rows, cur = [], []
    for line in block.split("\n")[1:]:
        line = line.strip()
        if line.startswith("|}"):
            break
        if line.startswith("|-") or line.startswith("|+"):
            if cur:
                rows.append(" | ".join(cur))
            cur = [] if line.startswith("|-") else [line[2:].strip()]
            continue
        if line[:1] in ("|", "!"):
            for cell in re.split(r"\|\||!!", line[1:]):
                cell = cell.split("|", 1)[-1] if re.match(r"^\s*[\w-]+\s*=\s*\"", cell) else cell
                if cell.strip():
                    cur.append(cell.strip())
        elif line and cur:
            cur[-1] += " " + line
    if cur:
        rows.append(" | ".join(cur))
    return "\n" + "\n".join(rows) + "\n"


def wikitext_to_text(wt):
    """Returns (plain text with '## ' headings, categories)."""
    cats = []
    t = wt.replace("\r\n", "\n")
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<(gallery|math|syntaxhighlight|source|timeline|imagemap)[^>]*>.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"__[A-Z]+__", "", t)
    t = strip_nested(t, "{{", "}}", template)
    t = re.sub(r"\{\|.*?\n\|\}", lambda m: table(m.group(0)), t, flags=re.S)
    t = strip_nested(t, "[[", "]]", lambda inner: link(inner, cats))
    t = re.sub(r"\[(?:https?:)?//\S+\s+([^\]]+)\]", r"\1", t)
    t = re.sub(r"\[(?:https?:)?//\S+\]", "", t)
    t = re.sub(r"'''''|'''|''", "", t)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)
    out = []
    for line in t.split("\n"):
        m = re.match(r"^(={1,6})\s*(.*?)\s*\1\s*$", line)
        if m:
            out += ["", "#" * len(m.group(1)) + " " + m.group(2), ""]
            continue
        m = re.match(r"^([*#:;]+)\s*(.*)$", line)
        if m:
            line = "  " * (len(m.group(1)) - 1) + "- " + m.group(2)
        out.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text, list(dict.fromkeys(cats))


# Storage

def safe_name(title):
    """A file stem for a page title: no path separators, at most 100 bytes of title in UTF-8 (so the full name stays
    under the usual 255-byte limit whatever the script), plus a hash of the exact title."""
    stem = re.sub(r"[^\w.-]+", "_", title).encode("utf-8")[:100].decode("utf-8", "ignore")
    return stem + "-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]


class Store:
    def __init__(self, base):
        self.base = base
        self.path = base / "manifest.json"
        if self.path.is_file():
            self.manifest = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.manifest = {"site": SITE, "license": None, "pages": {}}

    def save(self):
        self.base.mkdir(parents=True, exist_ok=True)
        self.manifest["updated_at"] = int(time.time())
        with s.atomic_file(self.path) as f:
            f.write(json.dumps(self.manifest, indent=1, ensure_ascii=False))

    def put(self, title, pageid, revid, timestamp, wikitext):
        name = safe_name(title)
        for sub in ("raw", "text"):
            (self.base / sub).mkdir(parents=True, exist_ok=True)
        (self.base / "raw" / (name + ".wiki")).write_text(wikitext, encoding="utf-8")
        text, cats = wikitext_to_text(wikitext)
        (self.base / "text" / (name + ".txt")).write_text(text, encoding="utf-8")
        self.manifest["pages"][title] = {
            "file": name + ".txt", "pageid": pageid, "revid": revid, "timestamp": timestamp,
            "url": SITE + "/wiki/" + urllib.parse.quote(title.replace(" ", "_")), "categories": cats,
        }

    def drop(self, title):
        page = self.manifest["pages"].pop(title, None)
        if page:
            stem = page["file"][:-4]
            for f in (self.base / "text" / page["file"], self.base / "raw" / (stem + ".wiki")):
                if f.is_file():
                    f.unlink()

    def reconvert(self):
        for title, page in self.manifest["pages"].items():
            raw = self.base / "raw" / (page["file"][:-4] + ".wiki")
            if raw.is_file():
                text, cats = wikitext_to_text(raw.read_text(encoding="utf-8"))
                (self.base / "text" / page["file"]).write_text(text, encoding="utf-8")
                page["categories"] = cats


# Network

class Client:
    def __init__(self):
        self.last = 0.0
        self.requests = 0

    def get(self, url, params=None):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(8):
            wait = MIN_INTERVAL - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(req, timeout=60) as f:
                    body = f.read().decode("utf-8", "replace")
                    retry = f.headers.get("Retry-After")
            except urllib.error.HTTPError as e:
                retry = e.headers.get("Retry-After") if e.headers else None
                if e.code not in (429, 500, 502, 503, 504) or attempt == 7:
                    raise RuntimeError("HTTP %d for %s" % (e.code, url)) from None
                time.sleep(backoff(retry, attempt))
                continue
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if attempt == 7:
                    raise
                time.sleep(backoff(None, attempt))
                continue
            if params and params.get("format") == "json":
                data = json.loads(body)
                err = data.get("error") or {}
                if err.get("code") == "maxlag":
                    time.sleep(backoff(retry or "5", attempt))
                    continue
                if err:
                    raise RuntimeError("API error: %s" % json.dumps(err)[:300])
                return data
            return body
        raise RuntimeError("gave up on %s" % url)

    def api(self, **params):
        params.update({"format": "json", "formatversion": "2", "maxlag": "5"})
        return self.get(API, params)


def backoff(retry_after, attempt):
    try:
        return max(1.0, float(retry_after))
    except (TypeError, ValueError):
        return min(120.0, 2.0 ** (attempt + 1))


def robots_allows_api(client):
    text = client.get(SITE + "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    probe = API + "?action=query&list=allpages&format=json"
    return rp.can_fetch(USER_AGENT, probe), text


def site_license(client):
    html = client.get(SITE + "/wiki/Main_Page")
    m = re.search(r'id="footer-info-copyright"[^>]*>(.*?)</li>', html, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


def list_pages(client, namespaces):
    """title -> (pageid, lastrevid) for every non-redirect page in the namespaces."""
    pages = {}
    for ns in namespaces:
        cont = {}
        while True:
            data = client.api(action="query", generator="allpages", gapnamespace=str(ns), gapfilterredir="nonredirects",
                              gaplimit="500", prop="info", **cont)
            for p in (data.get("query") or {}).get("pages", []):
                pages[p["title"]] = (p["pageid"], p.get("lastrevid"))
            if "continue" not in data:
                break
            cont = {k: v for k, v in data["continue"].items()}
    return pages


def fetch(client, store, titles, log):
    for i in range(0, len(titles), BATCH):
        batch = titles[i:i + BATCH]
        data = client.api(action="query", prop="revisions", rvprop="ids|timestamp|content", rvslots="main",
                          titles="|".join(batch))
        for p in (data.get("query") or {}).get("pages", []):
            if p.get("missing") or not p.get("revisions"):
                continue
            rev = p["revisions"][0]
            content = (rev.get("slots") or {}).get("main", {}).get("content", rev.get("content", ""))
            store.put(p["title"], p["pageid"], rev.get("revid"), rev.get("timestamp"), content)
        store.save()
        log("fetched %d/%d" % (min(i + BATCH, len(titles)), len(titles)))


def open_dump(path):
    """A MediaWiki XML export, plain or gzip-compressed (Miraheze's archive.org backups are .xml.gz)."""
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


def import_dump(store, path, namespaces, log, source=None):
    """Imports every non-redirect page in the namespaces, keeping each page's newest revision (Miraheze dumps carry
    the full history). Returns the page count."""
    count, page, best = 0, {}, None
    with open_dump(path) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            tag = el.tag.rsplit("}", 1)[-1]
            if tag in ("title", "ns"):
                page[tag] = el.text
            elif tag == "redirect":
                page["redirect"] = True
            elif tag == "id" and "pageid" not in page:
                page["pageid"] = int(el.text)
            elif tag == "revision":
                rev = {c.tag.rsplit("}", 1)[-1]: c.text for c in el}
                revid = int(rev.get("id") or 0)
                if best is None or revid >= best[0]:
                    best = (revid, rev.get("timestamp"), rev.get("text") or "")
                el.clear()
            elif tag == "page":
                if best and not page.get("redirect") and int(page.get("ns") or 0) in namespaces and page.get("title"):
                    store.put(page["title"], page.get("pageid"), best[0], best[1], best[2])
                    count += 1
                page, best = {}, None
                el.clear()
    store.manifest["source"] = source or "dump:" + Path(path).name
    store.manifest["license"] = store.manifest.get("license") or LICENSE
    store.save()
    log("imported %d pages from %s" % (count, path))
    return count


def import_dump_atomic(wiki_dir, path, namespaces, log, source=None):
    """Imports into a fresh staging directory and swaps it in only when the import finished, so a crash or a bad dump
    never leaves a half-updated wiki corpus. Returns (page count, staging dir); the caller swaps it in with
    semsearch.swap_dir once everything that depends on it has succeeded."""
    new = s.staged(wiki_dir, "new")
    try:
        count = import_dump(Store(new), path, namespaces, log, source)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    return count, new


def living_wiki_refusal(ctx):
    """Why this tool must not write <corpus>/wiki, or None. Once a living wiki exists the corpus wiki is its snapshot;
    a dump or API write here would hide Dave's edits from search until the next sync."""
    if (ctx.living_wiki() / ".git").is_dir():
        return ("%s exists, so the corpus wiki is the living wiki's snapshot. Import dumps with update_wiki.py "
                "(--force ITEM for a given dump) instead." % ctx.living_wiki())
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--from-dump")
    ap.add_argument("--reconvert", action="store_true")
    ap.add_argument("--namespaces", default=",".join(str(n) for n in NAMESPACES))
    ap.add_argument("--limit", type=int, default=0, help="fetch at most this many changed pages (for a trial run)")
    a = ap.parse_args()
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    namespaces = tuple(int(n) for n in a.namespaces.split(","))
    ctx = s.Context()
    refusal = None if a.check else living_wiki_refusal(ctx)
    if refusal:
        log(refusal)
        return 1
    s.recover_dir(ctx.wiki_dir)
    store = Store(ctx.wiki_dir)

    if a.reconvert:
        store.reconvert()
        store.save()
        log("reconverted %d pages" % len(store.manifest["pages"]))
        return 0
    if a.from_dump:
        with s.file_lock(ctx.jobs_lock()) as held:
            if not held:
                log("another job is updating the corpus; try again later")
                return 1
            count, new = import_dump_atomic(ctx.wiki_dir, a.from_dump, namespaces, log)
            if not count:
                shutil.rmtree(new, ignore_errors=True)
                log("no pages in %s; the corpus is unchanged" % a.from_dump)
                return 1
            s.swap_dir(new, ctx.wiki_dir)
        return 0

    client = Client()
    allowed, _ = robots_allows_api(client)
    lic = site_license(client)
    print("robots.txt allows %s for %r: %s" % (API, USER_AGENT, "yes" if allowed else "NO"))
    print("license: %s" % lic)
    if a.check:
        return 0
    if not allowed and not a.ignore_robots:
        print("robots.txt disallows the API, so nothing was mirrored. Ask the wiki admins for permission (then use "
              "--ignore-robots) or for an XML dump (--from-dump).", file=sys.stderr)
        return 3
    store.manifest["license"] = lic
    listing = list_pages(client, namespaces)
    known = store.manifest["pages"]
    changed = sorted(t for t, (_, rev) in listing.items() if t not in known or known[t].get("revid") != rev)
    gone = sorted(t for t in known if t not in listing)
    for t in gone:
        store.drop(t)
    if a.limit:
        changed = changed[:a.limit]
    log("%d pages listed, %d to fetch, %d removed" % (len(listing), len(changed), len(gone)))
    fetch(client, store, changed, log)
    store.manifest["source"] = "api"
    store.save()
    log("done: %d pages, %d requests" % (len(store.manifest["pages"]), client.requests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
