"""The living wiki: the server's own copy of wiki.gtnewhorizons.com, kept in git so official updates never wipe Dave's
edits. See docs/plans/living-wiki.md.

  python3 -I tools/living-wiki/living_wiki.py init                 create the repo from the corpus wiki, only if absent
  python3 -I tools/living-wiki/living_wiki.py sync                 re-materialize the search corpus from `living`
  python3 -I tools/living-wiki/living_wiki.py status
  python3 -I tools/living-wiki/living_wiki.py export [--out F]     write a git bundle of every branch, for backup
  python3 -I tools/living-wiki/living_wiki.py try-merge --page P [--report R] [--merger claude]
                                                                   re-run one conflicted page's merge from a report,
                                                                   print the result, commit nothing

Layout: <state>/wiki-git/ (data/wiki-git/ in dev, or GTNH_WIKI_GIT) is a normal repo checked out on `living`:
  text/<file>.txt   the converted page text that search reads (Dave edits these)
  raw/<file>.wiki   official wikitext (official only)
  manifest.json     official page list, one page per line (official only)
  local.json        pages Dave created (living only)
  reports/          merge reports (living only)
Branch `official` gets one commit per imported dump; `living` is official plus Dave's edits and merges. The search
corpus (<corpus>/wiki) is a snapshot materialized from `living`. The review queue is <state>/wiki-review.jsonl.

The wiki describes what is true now. History belongs in commit messages (Reason / Evidence / Asked-by / Supersedes
trailers), never in page text.
"""

import argparse
import copy
import datetime
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEARCH = HERE.parent / "gtnh-search"
sys.path.insert(0, str(SEARCH))
sys.path.insert(0, str(HERE))
import mirror_wiki as mw  # noqa: E402
import semsearch as s  # noqa: E402
import merger as mg  # noqa: E402

OFFICIAL, LIVING = "official", "living"
IMPORTER = ("GTNH wiki import", "official@living-wiki.invalid")
DAVE = ("Dave", "dave@living-wiki.invalid")
# GIT_OPTIONAL_LOCKS=0: readers outside the wiki lock never take index.lock, so a lock file found under the wiki lock
# is always a crash leftover.
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8",
           "GIT_OPTIONAL_LOCKS": "0"}
GIT_OPTS = ["-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "core.quotepath=off",
            "-c", "user.name=" + DAVE[0], "-c", "user.email=" + DAVE[1], "-c", "gc.auto=0"]
TRAILERS = ("Reason", "Evidence", "Asked-by", "Section", "Supersedes", "Reverts", "Resolves-review", "Dave-edit",
            "Dump-Item", "Dump-File", "Pages")
LOCK_WAIT = 15
VIEW_LIMIT = 40_000  # characters of a page wiki_get shows; longer pages are edited by section
TRUNCATED = "[… truncated; edit by section]"
IN_PROGRESS = ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD", "sequencer")


def today():
    return datetime.date.today().isoformat()


def one_line(v, limit=1000):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def repo_dir(ctx):
    return ctx.living_wiki()


def history_warnings(text):
    """History phrasing in page text: the wiki states current fact; the story goes in `reason`."""
    found = sorted({m.group(0).lower() for m in mg.HISTORY_PHRASES.finditer(text or "")})
    return found


def parse_trailers(body):
    """Trailer lines (Key: value) from the last paragraph of a commit message."""
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    out = {}
    if paras:
        for line in paras[-1].splitlines():
            m = re.match(r"^([A-Za-z][A-Za-z-]*):\s?(.*)$", line.strip())
            if m and m.group(1) in TRAILERS:
                out[m.group(1)] = m.group(2).strip()
    return out


def message(subject, trailers, body=""):
    lines = [one_line(subject, 200), ""]
    if body:
        lines += [body.rstrip(), ""]
    lines += ["%s: %s" % (k, one_line(v)) for k, v in trailers if v not in (None, "")]
    return "\n".join(lines) + "\n"


def canonical_manifest(meta, pages):
    """Official manifest with one page per line, sorted, so a dump update changes only the lines of changed pages."""
    head = json.dumps({k: v for k, v in meta.items() if k != "pages"}, sort_keys=True, ensure_ascii=False)
    rows = ",\n".join("%s: %s" % (json.dumps(t, ensure_ascii=False), json.dumps(p, sort_keys=True, ensure_ascii=False))
                      for t, p in sorted(pages.items()))
    return '{"meta": %s,\n"pages": {\n%s\n}}\n' % (head, rows)


class Git:
    def __init__(self, path):
        self.path = Path(path)

    def run(self, *args, input=None, env=None, check=True, binary=False):
        e = dict(os.environ)
        e.update(GIT_ENV)
        e.update(env or {})
        p = subprocess.run(["git", *GIT_OPTS, "-C", str(self.path), *args], input=input, env=e,
                           capture_output=True, text=not binary, encoding=None if binary else "utf-8")
        if check and p.returncode != 0:
            err = p.stderr if not binary else p.stderr.decode("utf-8", "replace")
            raise RuntimeError("git %s failed: %s" % (" ".join(args[:3]), err.strip()[-400:]))
        return p

    def out(self, *args, **kw):
        return self.run(*args, **kw).stdout

    def rev(self, ref):
        p = self.run("rev-parse", "--verify", "-q", ref + "^{commit}", check=False)
        return p.stdout.strip() or None

    def show(self, rev, path):
        p = self.run("show", "%s:%s" % (rev, path), check=False)
        return p.stdout if p.returncode == 0 else None

    def commit_tree(self, tree, parents, msg, who):
        env = {"GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1]}
        args = ["commit-tree", tree]
        for p in parents:
            args += ["-p", p]
        return self.out(*args, input=msg, env=env).strip()

    def tree_from(self, entries, base_tree=None):
        """A tree from {path: blob sha or None (remove)} on top of base_tree, using a throwaway index."""
        with tempfile.TemporaryDirectory() as d:
            env = {"GIT_INDEX_FILE": str(Path(d) / "index")}
            if base_tree:
                self.run("read-tree", base_tree, env=env)
            adds = "".join("100644 %s\t%s\n" % (sha, p) for p, sha in entries.items() if sha)
            if adds:
                self.run("update-index", "--add", "--index-info", input=adds, env=env)
            removes = [p for p, sha in entries.items() if not sha]
            for i in range(0, len(removes), 200):
                self.run("update-index", "--force-remove", "--", *removes[i:i + 200], env=env)
            return self.out("write-tree", env=env).strip()

    def cat(self, oid):
        """A blob's text, or "" for no oid."""
        return self.out("cat-file", "blob", oid) if oid else ""

    def blob(self, text):
        return self.out("hash-object", "-w", "--stdin", input=text).strip()

    def blobs(self, paths):
        """Writes files as blobs; returns their shas in order."""
        if not paths:
            return []
        return self.out("hash-object", "-w", "--stdin-paths", input="".join(str(p) + "\n" for p in paths)).split()

    def log(self, *args):
        """[(sha, iso date, full message)] for git log args."""
        raw = self.out("log", "--format=%H%x1f%aI%x1f%B%x1e", *args)
        return [tuple(r.strip("\n").split("\x1f", 2)) for r in raw.split("\x1e") if r.strip()]


class LivingWiki:
    def __init__(self, ctx):
        self.ctx = ctx
        self.dir = repo_dir(ctx)
        self.git = Git(self.dir)
        self.lock_path = self.dir.with_name(self.dir.name + ".lock")
        self.review_path = self.dir.with_name("wiki-review.jsonl")
        self.reports_dir = self.dir.with_name("wiki-reports")

    # ---------------------------------------------------------------- repo state

    def exists(self):
        return (self.dir / ".git").is_dir() and self.git.rev(LIVING) and self.git.rev(OFFICIAL)

    def lock(self, wait=None):
        """Context manager: the wiki lock, retried for `wait` seconds (default LOCK_WAIT). Yields True when held."""
        wait = LOCK_WAIT if wait is None else wait

        class _L:
            def __enter__(inner):
                deadline = time.time() + wait
                while True:
                    inner.cm = s.file_lock(self.lock_path)
                    held = inner.cm.__enter__()
                    if held or time.time() >= deadline:
                        return held
                    inner.cm.__exit__(None, None, None)
                    time.sleep(0.5)

            def __exit__(inner, *exc):
                return inner.cm.__exit__(*exc)
        return _L()

    def official_manifest(self, rev=OFFICIAL):
        raw = self.git.show(rev, "manifest.json")
        return json.loads(raw) if raw else {"meta": {}, "pages": {}}

    def local_pages(self, rev=LIVING):
        raw = self.git.show(rev, "local.json")
        return json.loads(raw)["pages"] if raw else {}

    def pages(self, rev=LIVING):
        """title -> {"file", "local"?} for every page on rev."""
        out = {t: {"file": p["file"]} for t, p in self.official_manifest(rev).get("pages", {}).items()}
        for t, p in self.local_pages(rev).items():
            out[t] = {"file": p["file"], "local": True, "created": p.get("created")}
        present = set(self.git.out("ls-tree", "-r", "--name-only", rev, "--", "text/").split("\n"))
        return {t: p for t, p in out.items() if "text/" + p["file"] in present}

    def official_item(self):
        """(item, YYYYMMDD) of the newest dump on `official`."""
        if not self.git.rev(OFFICIAL):
            return None, None
        for _, _, msg in self.git.log("-1", OFFICIAL):
            item = parse_trailers(msg).get("Dump-Item")
            return item, dump_date(item)
        return None, None

    def ensure_clean(self, log=lambda m: None):
        """The worktree belongs to this module; anything left by a crash is discarded. Call it only under the wiki lock:
        every git writer holds that lock, so lock files found here are leftovers of a killed git process."""
        gd = self.dir / ".git"
        for f in [gd / "index.lock", gd / "HEAD.lock", gd / "packed-refs.lock", *(gd / "refs" / "heads").glob("*.lock")]:
            if f.exists():
                log("removing stale %s" % f)
                f.unlink()
        reset = False
        if self.git.run("symbolic-ref", "-q", "HEAD", check=False).stdout.strip() != "refs/heads/" + LIVING:
            log("HEAD was not on %s; checking it out" % LIVING)  # edits must never land on `official`
            self.git.run("symbolic-ref", "HEAD", "refs/heads/" + LIVING)
            reset = True
        if reset or any((gd / n).exists() for n in IN_PROGRESS) or self.git.out("status", "--porcelain"):
            self.git.run("reset", "--hard", "-q")
            self.git.run("clean", "-fdq")
            shutil.rmtree(gd / "sequencer", ignore_errors=True)

    # ---------------------------------------------------------------- official imports

    def official_commit(self, snapshot, item, file_name, parent):
        """Commits a Store-format snapshot (manifest.json, raw/, text/) as an official commit on top of parent, without
        moving any branch. Returns the commit sha."""
        snapshot = Path(snapshot)
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        pages = manifest.get("pages", {})
        paths = []
        for p in pages.values():
            stem = p["file"][:-4]
            paths += [snapshot / "text" / p["file"], snapshot / "raw" / (stem + ".wiki")]
        paths = [p for p in paths if p.is_file()]
        shas = self.git.blobs(paths)
        entries = {str(p.relative_to(snapshot)): sha for p, sha in zip(paths, shas)}
        meta = {k: v for k, v in manifest.items() if k not in ("pages", "updated_at", "living_commit", "official_commit")}
        entries["manifest.json"] = self.git.blob(canonical_manifest(meta, pages))
        old = set()
        if parent:
            old = {p for p in self.git.out("ls-tree", "-r", "--name-only", parent, "--", "text/", "raw/").split("\n") if p}
        for p in old - set(entries):
            entries[p] = None
        tree = self.git.tree_from(entries, self.git.out("rev-parse", parent + "^{tree}").strip() if parent else None)
        msg = message("official: import %s" % item, [("Dump-Item", item), ("Dump-File", file_name),
                                                       ("Pages", str(len(pages)))])
        return self.git.commit_tree(tree, [parent] if parent else [], msg, IMPORTER)

    def init_from(self, snapshot, item, file_name, log=lambda m: None):
        """Creates the repo with `official` and `living` both at the snapshot. Only when no repo exists."""
        if self.exists():
            return False
        if self.dir.exists() and any(self.dir.iterdir()):
            raise RuntimeError("%s exists but is not a living-wiki repo; refusing to touch it" % self.dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.git.run("init", "-q", "-b", LIVING)
        c = self.official_commit(snapshot, item, file_name, None)
        self.git.run("update-ref", "refs/heads/" + OFFICIAL, c)
        self.git.run("update-ref", "refs/heads/" + LIVING, c)
        self.git.run("reset", "--hard", "-q", LIVING)
        log("living wiki created at %s from %s" % (self.dir, item))
        return True

    # ---------------------------------------------------------------- merging an official update

    def dave_edits(self, base, head, path):
        out = []
        for sha, date, msg in self.git.log("%s..%s" % (base, head), "--no-merges", "--", path):
            t = parse_trailers(msg)
            if t.get("Dave-edit") == "true":
                out.append({"commit": sha[:10], "date": date[:10], "reason": t.get("Reason", ""),
                            "evidence": t.get("Evidence", ""), "asked_by": t.get("Asked-by", ""),
                            "section": t.get("Section", ""), "supersedes": t.get("Supersedes", "")})
        return out

    def merge(self, new_official, item, merger, log=lambda m: None):
        """Merges new_official into living without moving any branch. Returns (merge commit, report).

        Rename detection is off: page files are named after titles, so an upstream page move is a delete plus an add.
        A moved page Dave edited takes the deleted-but-edited path (kept and flagged, with the likely new title), never
        a rename merge. Conflicted pages are read from merge-tree's own stage blobs, not by path."""
        living = self.git.rev(LIVING)
        base = self.git.out("merge-base", living, new_official).strip()
        p = self.git.run("-c", "merge.renames=false", "merge-tree", "--write-tree", "-z", "--no-messages", living,
                         new_official, check=False)  # config, not -X no-renames: works on git 2.38/2.39 too
        if p.returncode not in (0, 1):
            raise RuntimeError("git merge-tree failed: %s" % p.stderr.strip()[-300:])
        parts = p.stdout.split("\0")
        tree, stages = parts[0], {}
        for rec in parts[1:]:
            if "\t" not in rec:
                continue
            info, path = rec.split("\t", 1)
            mode, oid, stage = info.split()
            stages.setdefault(path, {})[int(stage)] = oid

        def names(a, b, flt=None):
            args = ["diff", "--name-only", "--no-renames"] + (["--diff-filter=" + flt] if flt else []) + [a, b, "--", "text/"]
            return {x for x in self.git.out(*args).split("\n") if x}

        off_changed, dave_changed = names(base, new_official), names(base, living)
        off_deleted, off_added = names(base, new_official, "D"), names(base, new_official, "A")
        titles = {"text/" + p["file"]: t for t, p in self.pages(living).items()}
        titles.update({"text/" + p["file"]: t for t, p in self.official_manifest(new_official)["pages"].items()})
        title = lambda path: titles.get(path, path)  # noqa: E731
        rep = {"item": item, "date": today(), "merger": merger.name, "base": base, "official_new": new_official,
               "living_before": living, "pages": {k: [] for k in (
                   "clean", "auto_merged", "llm_merged", "fallback", "flagged", "deleted", "kept_deleted")},
               "conflicts": {}}
        entries, review, blocks = {}, [], []
        local = self.local_pages(living)
        base_pages = self.official_manifest(base).get("pages", {})
        for path in sorted(off_changed - dave_changed - off_deleted):
            rep["pages"]["clean"].append(title(path))
        for path in sorted(off_deleted - dave_changed):
            rep["pages"]["deleted"].append(title(path))
        for path in sorted(stages):
            st = stages[path]
            if not path.startswith("text/"):
                entries[path] = st.get(3) or st.get(2)  # official-only files: take official
                continue
            page = title(path)
            if 3 not in st:  # deleted officially, edited by Dave: keep it as a server page and flag
                entries[path] = st[2]
                local[page] = {"file": path[5:], "created": today(), "kept_from_official": item,
                               "official_revid": base_pages.get(page, {}).get("revid")}
                rep["pages"]["kept_deleted"].append(page)
                moved = self.moved_to(self.git.cat(st.get(1)), new_official, off_added, title)
                reason = "deleted in the official wiki%s but edited by Dave; kept" % (
                    " (probably moved to %r)" % moved if moved else "")
                rep["pages"]["flagged"].append({"page": page, "reason": reason})
                review.append({"page": page, "reason": reason, "losing_text": ""})
                blocks.append((page, "kept (deleted officially)", "", reason))
                rep["conflicts"][page] = {"resolution": "kept_deleted", "moved_to": moved, "base_blob": st.get(1),
                                          "living_blob": st[2]}
                continue
            if 2 not in st:
                entries[path] = st[3]
                continue
            b_text, n_text, l_text = self.git.cat(st.get(1)), self.git.cat(st[3]), self.git.cat(st[2])
            edits = self.dave_edits(base, living, path)
            how = "llm_merged"
            try:
                result = merger.merge(page, b_text, n_text, l_text, edits)
                problems = mg.check(result, b_text, n_text, l_text)
                if problems:
                    raise ValueError("; ".join(problems))
            except Exception as e:  # any merger failure falls back to the lossless section merge
                log("%s: merger output rejected (%s); using the fallback" % (page, e))
                result, how = mg.fallback(b_text, n_text, l_text, str(e)), "fallback"
            entries[path] = self.git.blob(result["merged_text"])
            rep["pages"][how].append(page)
            # Every input stays reachable (the blobs are in the parents' trees); an LLM merge also keeps Dave's whole
            # text in the report, so nothing it replaced depends on the merger's own account of it.
            rep["conflicts"][page] = {"resolution": how, "base_blob": st.get(1), "official_blob": st[3],
                                      "living_blob": st[2]}
            if how == "llm_merged":
                rep["conflicts"][page]["living_text"] = l_text
            if result.get("flag"):
                rep["pages"]["flagged"].append({"page": page, "reason": result.get("flag_reason", "")})
                review.append({"page": page, "reason": result.get("flag_reason", ""),
                               "losing_text": result.get("losing_text", ""), "dave_edits": edits})
            blocks.append((page, how, result.get("commit_note", ""), result.get("flag_reason", "") if result.get("flag") else ""))
        conflicted = {title(p) for p in stages if p.startswith("text/")}
        rep["pages"]["auto_merged"] = sorted(title(p) for p in (off_changed & dave_changed) - off_deleted
                                             if title(p) not in conflicted)
        rep["counts"] = {k: len(v) for k, v in rep["pages"].items()}
        rep["counts"]["official_changed"] = len(off_changed)
        rep["counts"]["conflicted"] = len(conflicted)
        rep["review"] = review
        rep["summary"] = summary_line(rep)
        if rep["pages"]["kept_deleted"]:
            entries["local.json"] = self.git.blob(json.dumps({"pages": local}, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        report_path = "reports/merge-%s.json" % item
        entries[report_path] = self.git.blob(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        tree = self.git.tree_from(entries, tree)
        body = [rep["summary"], ""]
        for page, how, note, flag in blocks:
            body.append("Page: %s\nResolution: %s" % (page, how))
            if note:
                body.append("Note: " + one_line(note, 600))
            if flag:
                body.append("Flag: " + one_line(flag, 600))
            body.append("")
        body.append("The losing alternatives are in %s and the review queue." % report_path)
        msg = message("merge official %s into living" % item, [("Dump-Item", item)], "\n".join(body))
        commit = self.git.commit_tree(tree, [living, new_official], msg, IMPORTER)
        return commit, rep

    def moved_to(self, old_text, new_official, added, title, limit=300):
        """The title of the officially added page most like old_text (an upstream page move), or None."""
        if not old_text.strip():
            return None
        best, score = None, 0.6
        for path in sorted(added)[:limit]:
            sm = difflib.SequenceMatcher(None, old_text, self.git.show(new_official, path) or "", autojunk=False)
            if sm.real_quick_ratio() > score and sm.quick_ratio() > score and sm.ratio() > score:
                best, score = title(path), sm.ratio()
        return best

    # ---------------------------------------------------------------- the search corpus

    def materialize(self, dest, rev=LIVING, official=OFFICIAL):
        """Writes the search corpus for rev into dest (Store layout: manifest.json + text/), with Dave-edit metadata."""
        dest = Path(dest)
        if dest.exists():
            shutil.rmtree(dest)
        (dest / "text").mkdir(parents=True)
        data = self.git.out("archive", "--format=tar", rev, "text", binary=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for m in tar.getmembers():
                parts = m.name.split("/")
                if m.isfile() and len(parts) == 2 and parts[0] == "text" and parts[1] not in ("", ".", ".."):
                    (dest / m.name).write_bytes(tar.extractfile(m).read())
        man = self.official_manifest(rev)
        pages = {t: dict(p) for t, p in man.get("pages", {}).items()}
        for t, p in self.local_pages(rev).items():
            pages[t] = {"file": p["file"], "local": True}
        pages = {t: p for t, p in pages.items() if (dest / "text" / p["file"]).is_file()}
        by_file = {"text/" + p["file"]: t for t, p in pages.items()}
        changed = [x for x in self.git.out("diff", "--name-only", "--no-renames", official, rev, "--", "text/").split("\n") if x]
        for path in changed:
            t = by_file.get(path)
            if not t:
                continue
            living_text = (dest / path).read_text(encoding="utf-8")
            official_text = self.git.show(official, path) or ""
            pages[t]["dave_lines"] = changed_lines(official_text, living_text)
            last = next((m for m in self.git.log(rev, "--no-merges", "--", path)
                         if parse_trailers(m[2]).get("Dave-edit") == "true"), None)
            pages[t]["edited_by_dave"] = last[1][:10] if last else today()
            if last:
                pages[t]["dave_reason"] = one_line(parse_trailers(last[2]).get("Reason", ""), 200)
        meta = man.get("meta", {})
        out = {"site": meta.get("site", mw.SITE), "source": meta.get("source"), "license": meta.get("license"),
               "living_commit": self.git.rev(rev), "official_commit": self.git.rev(official), "pages": pages}
        (dest / "manifest.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        return out

    def sync(self, log=lambda m: None):
        """Re-materializes <corpus>/wiki when it doesn't match `living`, under the wiki lock (so it never races an update's
        own materialize or swap), and replays the newest merge's report and review rows if a crash lost them. Returns
        True when it rewrote the corpus; False when current or when the lock is busy (the holder brings it up to date)."""
        if not self.exists():
            return False
        with self.lock() as held:
            if not held:
                log("living wiki busy; corpus sync skipped")
                return False
            self.replay_report(log)
            target = self.ctx.wiki_dir
            s.recover_dir(target)
            m = target / "manifest.json"
            if m.is_file() and json.loads(m.read_text(encoding="utf-8")).get("living_commit") == self.git.rev(LIVING):
                return False
            new = s.staged(target, "new")
            try:
                self.materialize(new)
                s.swap_dir(new, target)
            finally:
                if new.is_dir():
                    shutil.rmtree(new, ignore_errors=True)
            log("search corpus updated from living %s" % self.git.rev(LIVING)[:10])
            return True

    # ---------------------------------------------------------------- the whole monthly update

    def upgrade(self, snapshot, item, file_name, merger, embedder, profile=s.DEFAULT_PROFILE, log=lambda m: None):
        """Imports snapshot onto `official`, merges it into `living`, rebuilds the index incrementally, and only then
        moves both branches (one ref transaction) and swaps in the new corpus and index. Any failure before the ref
        transaction changes nothing.

        Every merger call happens in a first pass without the wiki lock, so Dave can keep editing while models run;
        the merge is then redone under the lock with the answers replayed, and only pages Dave edited in between
        reach the merger again."""
        ctx = self.ctx
        old_official = self.git.rev(OFFICIAL)
        new_official = self.official_commit(snapshot, item, file_name, old_official)
        merger = mg.Cached(merger)
        self.merge(new_official, item, merger)  # unreferenced objects only; the locked pass below logs
        with self.lock(wait=600) as held:
            if not held:
                raise RuntimeError("the living wiki is locked by another process")
            self.ensure_clean(log)
            if self.git.rev(OFFICIAL) != old_official:
                raise RuntimeError("the official branch moved during the update; run it again")
            old_living = self.git.rev(LIVING)
            merged, rep = self.merge(new_official, item, merger, log)
            rep["merged"] = merged
            path = s.index_path(ctx, profile)
            new_dir = s.staged(ctx.wiki_dir, "new")
            next_index = path.with_name(path.stem + ".next.npz")
            index = None
            try:
                self.materialize(new_dir, merged, new_official)
                if embedder is not None:
                    with s.file_lock(path.with_suffix(".lock"), blocking=True):
                        if path.is_file():
                            shutil.copyfile(path, next_index)
                        bctx = copy.copy(ctx)
                        bctx.wiki_dir = new_dir
                        index = s.build(bctx, embedder, next_index, profile, log=log)
                        if index is None:
                            raise RuntimeError("index build was skipped")
                        rep["index"] = {k: index["meta"][k] for k in ("chunks", "embedded", "cost")}
                        self.commit_refs(old_official, new_official, old_living, merged, log)
                        self.write_report(rep)
                        s.swap_dir(new_dir, ctx.wiki_dir)
                        os.replace(next_index, path)
                else:
                    self.commit_refs(old_official, new_official, old_living, merged, log)
                    self.write_report(rep)
                    s.swap_dir(new_dir, ctx.wiki_dir)
            finally:
                for p in (new_dir, next_index, next_index.with_suffix(".lock"), next_index.with_suffix(".tmp.npz")):
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                    elif p.exists():
                        p.unlink()
            return rep

    def commit_refs(self, old_official, new_official, old_living, merged, log=lambda m: None):
        """Moves `official` and `living` in one ref transaction (both or neither, each checked against its old value),
        then brings the worktree up to `living`. A failed worktree reset is repaired by the next ensure_clean."""
        zero = "0" * len(new_official)
        self.git.run("update-ref", "--stdin", input="start\nupdate refs/heads/%s %s %s\nupdate refs/heads/%s %s %s\n"
                     "prepare\ncommit\n" % (OFFICIAL, new_official, old_official or zero, LIVING, merged, old_living))
        p = self.git.run("reset", "--hard", "-q", check=False)
        if p.returncode != 0:
            log("worktree reset after the merge failed (%s); the next write repairs it" % p.stderr.strip()[-200:])

    def write_report(self, rep):
        """The report copy and the review rows. Idempotent: rows for a dump item already in the queue are not added
        again, so replay_report can run it after a crash."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        out = self.reports_dir / ("merge-%s.json" % rep["item"])
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out)
        if any(r.get("item") == rep["item"] and r.get("kind") == "merge" for r in self.review_rows()):
            return
        with open(self.review_path, "a", encoding="utf-8") as f:
            for r in rep.get("review", []):
                f.write(json.dumps(dict(r, item=rep["item"], date=rep["date"], kind="merge", status="open"),
                                   ensure_ascii=False) + "\n")

    def replay_report(self, log=lambda m: None):
        """Writes the newest merge's report copy and review rows from the copy in its commit, when a crash between the
        ref transaction and write_report lost them."""
        for sha, _, msg in self.git.log("-1", "--merges", LIVING):
            item = parse_trailers(msg).get("Dump-Item")
            if not item or not msg.startswith("merge official") or (self.reports_dir / ("merge-%s.json" % item)).is_file():
                return
            raw = self.git.show(sha, "reports/merge-%s.json" % item)
            if raw:
                rep = json.loads(raw)
                rep["merged"] = sha
                self.write_report(rep)
                log("replayed the report and review rows of %s" % item)

    # ---------------------------------------------------------------- Dave's edits

    def find(self, page):
        pages = self.pages()
        if page in pages:
            return page, pages[page]
        low = {t.lower(): t for t in pages}
        t = low.get(page.strip().lower()) or low.get(page.strip().replace("_", " ").lower())
        return (t, pages[t]) if t else (None, None)

    def text(self, page):
        title, p = self.find(page)
        if not title:
            return None, None
        return title, (self.dir / "text" / p["file"]).read_text(encoding="utf-8")

    def history(self, page, limit=20):
        title, p = self.find(page)
        if not title:
            return None, []
        out = []
        for sha, date, msg in self.git.log("-%d" % limit, LIVING, "--", "text/" + p["file"]):
            t = parse_trailers(msg)
            kind = "dave" if t.get("Dave-edit") == "true" else ("merge" if msg.startswith("merge official") else "official")
            out.append({"commit": sha[:10], "date": date[:10], "kind": kind, "subject": msg.split("\n", 1)[0],
                        "reason": t.get("Reason", ""), "evidence": t.get("Evidence", ""), "asked_by": t.get("Asked-by", ""),
                        "supersedes": t.get("Supersedes", ""), "item": t.get("Dump-Item", "")})
        return title, out

    def review_rows(self):
        if not self.review_path.is_file():
            return []
        return [json.loads(l) for l in self.review_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def open_reviews(self, page=None):
        """Open flags. The queue is append-only, so a 'resolved' row settles only flags written before it: the dump items
        it lists, or (older rows without a list) all of that page's earlier flags. Later merges flag the page afresh."""
        open_rows = []
        for r in self.review_rows():
            if r.get("status") == "open":
                open_rows.append(r)
            elif r.get("status") == "resolved":
                items = r.get("items")
                open_rows = [o for o in open_rows if not (o["page"] == r["page"] and (
                    items is None and (r.get("item") is None or o.get("item") == r.get("item"))
                    or items is not None and o.get("item") in items))]
        return [r for r in open_rows if page is None or r["page"] == page]

    def commit_edit(self, files, subject, trailers):
        self.git.run("add", "-A", "--", *files)
        if not self.git.out("diff", "--cached", "--name-only"):
            raise ValueError("the edit changes nothing")
        msg = message(subject, trailers)
        env = {"GIT_AUTHOR_NAME": DAVE[0], "GIT_AUTHOR_EMAIL": DAVE[1], "GIT_COMMITTER_NAME": DAVE[0], "GIT_COMMITTER_EMAIL": DAVE[1]}
        self.git.run("commit", "-q", "-F", "-", input=msg, env=env)
        return self.git.rev("HEAD")

    def edit(self, page, new_text, reason, evidence, asked_by=None, section=None, supersedes=None,
             resolves_review=False, confirm_whole_page=False):
        if not one_line(reason) or not one_line(evidence):
            raise ValueError("reason and evidence are both required")
        with self.lock() as held:
            if not held:
                raise RuntimeError("the wiki is being updated; try again in a minute")
            self.ensure_clean()
            title, p = self.find(page)
            if not title:
                raise KeyError("no page %r; use wiki_search_titles, or wiki_create for a new page" % page)
            f = self.dir / "text" / p["file"]
            old = f.read_text(encoding="utf-8")
            if TRUNCATED in new_text:
                raise ValueError("the text contains wiki_get's truncation marker; edit the page by section instead")
            if not section and not confirm_whole_page and truncation_shaped(old, new_text):
                raise ValueError("%s is %d characters and wiki_get shows only the first %d, but this whole-page edit "
                                 "drops most of the rest. Edit it by section, or resend with confirm_whole_page: true if "
                                 "removing that text is intended." % (title, len(old), VIEW_LIMIT))
            new = replace_section(old, section, new_text) if section else new_text.strip() + "\n"
            f.write_text(new, encoding="utf-8")
            sha = self.commit_edit(["text/" + p["file"]], "wiki: edit %s%s" % (title, " / " + section if section else ""), [
                ("Reason", reason), ("Evidence", evidence), ("Asked-by", asked_by or "dave (no player)"),
                ("Section", section), ("Supersedes", supersedes), ("Resolves-review", "true" if resolves_review else None),
                ("Dave-edit", "true")])
            if resolves_review:
                self.resolve(title, sha)
            return title, sha

    def create(self, page, text, reason, evidence, asked_by=None):
        if not one_line(reason) or not one_line(evidence):
            raise ValueError("reason and evidence are both required")
        title = one_line(page, 200)
        if not title:
            raise ValueError("page title is required")
        with self.lock() as held:
            if not held:
                raise RuntimeError("the wiki is being updated; try again in a minute")
            self.ensure_clean()
            if self.find(title)[0]:
                raise ValueError("page %r exists; use wiki_edit" % title)
            name = mw.safe_name(title) + ".txt"
            (self.dir / "text").mkdir(exist_ok=True)
            body = text.strip()
            if not body.startswith("#"):
                body = "# %s\n\n%s" % (title, body)
            (self.dir / "text" / name).write_text(body + "\n", encoding="utf-8")
            local = self.local_pages("HEAD") if self.git.show("HEAD", "local.json") else {}
            local[title] = {"file": name, "created": today()}
            (self.dir / "local.json").write_text(json.dumps({"pages": local}, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
            sha = self.commit_edit(["text/" + name, "local.json"], "wiki: create %s" % title, [
                ("Reason", reason), ("Evidence", evidence), ("Asked-by", asked_by or "dave (no player)"), ("Dave-edit", "true")])
            return title, sha

    def revert(self, commit, reason, asked_by=None):
        if not one_line(reason):
            raise ValueError("reason is required")
        with self.lock() as held:
            if not held:
                raise RuntimeError("the wiki is being updated; try again in a minute")
            self.ensure_clean()
            full = self.git.rev(commit)
            if not full:
                raise KeyError("no commit %r" % commit)
            msg = self.git.out("log", "-1", "--format=%B", full)
            if parse_trailers(msg).get("Dave-edit") != "true":
                raise ValueError("only Dave's own edits can be reverted; %s is an official import or a merge" % commit)
            if self.git.run("merge-base", "--is-ancestor", full, LIVING, check=False).returncode != 0:
                raise ValueError("%s is not on the living branch" % commit)
            p = self.git.run("revert", "--no-commit", full, check=False)
            if p.returncode != 0:
                self.git.run("revert", "--abort", check=False)
                self.ensure_clean()
                raise RuntimeError("revert conflicts with later changes; edit the page instead")
            if self.git.run("diff", "--cached", "--quiet", check=False).returncode == 0:
                self.ensure_clean()
                raise ValueError("nothing to revert: the changes of %s are already undone" % full[:10])
            env = {"GIT_AUTHOR_NAME": DAVE[0], "GIT_AUTHOR_EMAIL": DAVE[1], "GIT_COMMITTER_NAME": DAVE[0], "GIT_COMMITTER_EMAIL": DAVE[1]}
            self.git.run("commit", "-q", "-F", "-", env=env, input=message(
                "wiki: revert %s" % full[:10], [("Reason", reason), ("Evidence", "revert of " + full[:10]),
                                                ("Asked-by", asked_by or "dave (no player)"), ("Reverts", full), ("Dave-edit", "true")]))
            return self.git.rev("HEAD")

    def resolve(self, page, commit):
        """Settles the page's flags open now (by dump item); flags from later merges stay open."""
        items = sorted({r.get("item") for r in self.open_reviews(page)}, key=str)
        with open(self.review_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page": page, "status": "resolved", "items": items, "commit": commit[:10],
                                "date": today()}, ensure_ascii=False) + "\n")

    def export(self, out=None):
        out = Path(out) if out else self.dir.with_name("exports") / ("living-wiki-%s.bundle" % today())
        out.parent.mkdir(parents=True, exist_ok=True)
        self.git.run("bundle", "create", "-q", str(out), "--all")
        return out


def replace_section(text, section, new_body):
    """Replaces the text directly under the heading named `section` (case-insensitive) up to the next heading of any
    level, keeping the heading line. Subsections are separate sections, so editing a page's H1 changes only its intro."""
    lines = text.split("\n")
    want = section.strip().lstrip("#").strip().lower()
    heads = mg.heading_lines(text)  # outside code fences, the same headings the merge sees
    hits = [i for i, _, h in heads if h.lower() == want]
    if not hits:
        raise KeyError("no section %r on this page; headings are: %s" % (section, ", ".join(mg.headings(text))[:500]))
    if len(hits) > 1:
        raise KeyError("section %r appears %d times; edit the whole page instead" % (section, len(hits)))
    i = hits[0]
    end = next((j for j, _, _ in heads if j > i), len(lines))
    body = new_body.strip("\n").split("\n")
    if body and mg.HEADING.match(body[0]) and mg.HEADING.match(body[0]).group(2).strip().lower() == want:
        body = body[1:]
    while body and not body[0].strip():
        body = body[1:]
    return "\n".join(lines[:i + 1] + [""] + [l for l in body] + [""] + lines[end:]).rstrip("\n") + "\n"


def truncation_shaped(old, new):
    """True when old is longer than wiki_get shows and new keeps under half of the significant lines past that point:
    the shape of a whole-page edit made from the truncated view."""
    if len(old) <= VIEW_LIMIT:
        return False
    tail = [l for l in old[VIEW_LIMIT:].split("\n")[1:] if mg.significant(l)]  # [1:]: the line the cut split
    if not tail:
        return False
    have = mg._Lines(new)
    return sum(1 for l in tail if have.has(l)) < 0.5 * len(tail)


def changed_lines(old, new):
    """1-based inclusive line ranges of new that differ from old."""
    out = []
    sm = difflib.SequenceMatcher(None, old.split("\n"), new.split("\n"), autojunk=False)
    for tag, _, _, j1, j2 in sm.get_opcodes():
        if tag != "equal" and j2 > j1:
            out.append([j1 + 1, j2])
    return out


def dump_date(name):
    m = re.search(r"gtnhwiki-(\d{8})", name or "")
    return m.group(1) if m else None


def summary_line(rep):
    c = rep["counts"]
    return ("living wiki %s: %d official page changes: %d clean, %d auto-merged, %d conflicted (%d merged by %s, %d "
            "fallback); %d flagged; %d deleted, %d kept because Dave edited them"
            % (rep["item"], c["official_changed"], c["clean"], c["auto_merged"], c["conflicted"], c["llm_merged"],
               rep["merger"], c["fallback"], c["flagged"], c["deleted"], c["kept_deleted"]))


def snapshot_item(wiki_dir):
    """(item, file) recorded in a Store-format wiki dir's manifest source."""
    m = Path(wiki_dir) / "manifest.json"
    if not m.is_file():
        return None, None
    src = json.loads(m.read_text(encoding="utf-8")).get("source") or ""
    date = dump_date(src)
    if not date:
        return None, None
    item = re.search(r"(miraheze-wiki-gtnhwiki-\d{8})", src)
    return (item.group(1) if item else "miraheze-wiki-gtnhwiki-" + date), "gtnhwiki-%s.xml.gz" % date


def ensure(ctx, log=lambda m: None):
    """Creates the living wiki from the corpus wiki snapshot (the image's baked dump) only when none exists."""
    lw = LivingWiki(ctx)
    if lw.exists():
        return lw, False
    snap = s.live_dir(ctx.wiki_dir)
    item, file_name = snapshot_item(snap)
    if not item:
        return lw, False
    with lw.lock() as held:
        if not held or lw.exists():
            return lw, False
        lw.init_from(snap, item, file_name, log)
    lw.sync(log)
    return lw, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("init", "sync", "status", "export", "try-merge"))
    ap.add_argument("--out")
    ap.add_argument("--page")
    ap.add_argument("--report", help="merge report JSON (default: the newest in <state>/wiki-reports)")
    ap.add_argument("--merger", choices=("stub", "claude"), default="claude")
    ap.add_argument("--model", default=mg.DEFAULT_MODEL)
    a = ap.parse_args()
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    ctx = s.Context()
    if a.command == "init":
        lw, created = ensure(ctx, log)
        print("created %s" % lw.dir if created else ("%s already exists" % lw.dir if lw.exists() else "no wiki snapshot to start from"))
        return 0 if lw.exists() else 1
    lw = LivingWiki(ctx)
    if not lw.exists():
        print("no living wiki at %s; run init" % lw.dir, file=sys.stderr)
        return 1
    if a.command == "sync":
        print("updated" if lw.sync(log) else "current")
        return 0
    if a.command == "status":
        item, _ = lw.official_item()
        dave = [m for m in lw.git.log(LIVING, "--no-merges") if parse_trailers(m[2]).get("Dave-edit") == "true"]
        print("repo %s\nofficial: %s (%s)\nliving: %s, %d Dave edits\npages: %d\nopen reviews: %d"
              % (lw.dir, item, lw.git.rev(OFFICIAL)[:10], lw.git.rev(LIVING)[:10], len(dave), len(lw.pages()), len(lw.open_reviews())))
        return 0
    if a.command == "export":
        out = lw.export(a.out)
        print("%s\nrestore or inspect: git clone %s living-wiki && git -C living-wiki log --oneline living" % (out, out))
        return 0
    if a.command == "try-merge":
        reports = sorted(lw.reports_dir.glob("merge-*.json"))
        path = Path(a.report) if a.report else (reports[-1] if reports else None)
        if not path or not a.page:
            print("need --page and a merge report", file=sys.stderr)
            return 1
        rep = json.loads(path.read_text(encoding="utf-8"))
        title, p = lw.find(a.page)
        f = "text/" + (p["file"] if p else mw.safe_name(a.page) + ".txt")
        c = rep.get("conflicts", {}).get(title or a.page, {})
        if c.get("base_blob") or c.get("official_blob"):
            base, new, living = (lw.git.cat(c.get(k)) for k in ("base_blob", "official_blob", "living_blob"))
        else:
            base, new, living = (lw.git.show(rep[k], f) or "" for k in ("base", "official_new", "living_before"))
        edits = lw.dave_edits(rep["base"], rep["living_before"], f)
        m = mg.make(a.merger, a.model)
        try:
            result = m.merge(title or a.page, base, new, living, edits)
        except Exception as e:
            print("merge failed: %s\n(the weekly job would use the lossless fallback here)" % e, file=sys.stderr)
            return 1
        problems = mg.check(result, base, new, living)
        print(json.dumps({"validation": problems or "ok", "result": result}, indent=1, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
