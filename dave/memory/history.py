"""Long-term, versioned history of Dave's memories: a git repository kept outside the memory folder.

In production the history is its own Docker volume (/dave/history, the `dave-memory-history` volume on the host), so
it outlives the `dave-data` volume and image rebuilds. It is never part of the Dave-Agent repo: memories hold player
data, and that repo is public.

    memory folder (DAVE_MEMORY_DIR)  --snapshot-->  bare git repo (DAVE_MEMORY_HISTORY)

- snapshot   commits the memory folder as it is now, under the store lock so it is consistent. The message lists the
             memory writes since the last snapshot (from .log.jsonl). No commit when nothing changed. The container
             runs it at start and every 10 minutes.
- recover    fills an empty memory folder from the newest snapshot (the entrypoint tries this before seeding a
             blank memory, so a lost dave-data volume comes back from history).
- restore    writes a memory's version from a snapshot back as the current one, through the store (logged, indexed).
- log, show  browse the history; bundle writes the whole history to one file for an off-host backup.

Tracked: the memories, INDEX.md, .log.jsonl and saved queries. Not tracked: .lock, temp files and .objects/ (git
already keeps every snapshot's version). Standard library plus the git CLI.

CLI (for the owner):  python3 -I dave/memory/history.py init | snapshot [message] | recover | log [id] [N]
                      | show <rev> [id] | restore <id> <rev> | bundle <file>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dave.memory.store import Store, open_store, parse  # noqa: E402

EXCLUDES = ["/.lock", "/.objects/", ".tmp-*", "*.part"]
AUTHOR = ("Dave", "dave@memory.invalid")
TRAILER = "Memory-Log-Lines:"
MAX_LISTED = 20            # writes named in one commit message; the rest are counted


class HistoryError(Exception):
    pass


class History:
    """A bare git repository at `git_dir` whose work tree is the memory folder of `store`."""

    def __init__(self, store: Store, git_dir):
        self.store = store
        self.git_dir = Path(git_dir)

    def git(self, *args, check=True, work_tree=True, stdin=None):
        cmd = ["git", "--git-dir", str(self.git_dir)]
        if work_tree:
            cmd += ["--work-tree", str(self.store.root)]
        cmd += ["-c", "core.hooksPath=/dev/null", "-c", "user.name=" + AUTHOR[0], "-c", "user.email=" + AUTHOR[1],
                "-c", "commit.gpgsign=false"]
        r = subprocess.run(cmd + list(args), input=stdin, capture_output=True, text=True,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
        if check and r.returncode != 0:
            raise HistoryError("git %s: %s" % (args[0], (r.stderr or r.stdout).strip()))
        return r

    def init(self):
        """Creates the bare repository and its excludes if missing. Idempotent."""
        if not (self.git_dir / "HEAD").exists():
            self.git_dir.mkdir(parents=True, exist_ok=True)
            self.git("init", "--quiet", "--bare", "--initial-branch=main", str(self.git_dir), work_tree=False)
        exclude = self.git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        want = "# Dave memory history: never tracked\n" + "\n".join(EXCLUDES) + "\n"
        if not exclude.exists() or exclude.read_text() != want:
            exclude.write_text(want)

    def has_commits(self):
        return self.git("rev-parse", "--verify", "--quiet", "HEAD", check=False, work_tree=False).returncode == 0

    def _log_lines(self):
        log = self.store.root / ".log.jsonl"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def _last_count(self):
        if not self.has_commits():
            return 0
        body = self.git("log", "-1", "--format=%B", work_tree=False).stdout
        for line in body.splitlines():
            if line.startswith(TRAILER):
                try:
                    return int(line[len(TRAILER):].strip())
                except ValueError:
                    return 0
        return 0

    @staticmethod
    def _describe(entry):
        who = entry.get("asked_by") or entry.get("player")
        return "%s %s%s" % (entry.get("op", "?"), entry.get("id", "?"), " (for %s)" % who if who else "")

    def snapshot(self, message=None):
        """Commits the memory folder if it changed. Returns the new commit id, or None when nothing changed."""
        self.init()
        with self.store._locked():
            self.git("add", "--all", ".")
            if self.has_commits() and self.git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return None
            if not self.has_commits() and not self.git("ls-files", "--cached").stdout.strip():
                return None                      # nothing to record yet
            lines = self._log_lines()
            start = self._last_count()
            if start > len(lines):               # the log was replaced (a recovered or reset folder)
                start = 0
            entries = []
            for raw in lines[start:]:
                try:
                    entries.append(json.loads(raw))
                except ValueError:
                    continue
            subject = message or (
                "%d memory write%s" % (len(entries), "" if len(entries) == 1 else "s") if entries
                else "memory snapshot")
            body = [self._describe(e) for e in entries[:MAX_LISTED]]
            if len(entries) > MAX_LISTED:
                body.append("... and %d more" % (len(entries) - MAX_LISTED))
            text = subject + "\n\n" + ("\n".join(body) + "\n\n" if body else "") + "%s %d\n" % (TRAILER, len(lines))
            self.git("commit", "--quiet", "--file", "-", stdin=text)
            return self.git("rev-parse", "--short", "HEAD", work_tree=False).stdout.strip()

    def is_empty_memory(self):
        root = self.store.root
        return not (root / "INDEX.md").exists() and not any(root.glob("*/*.md"))

    def recover(self):
        """Fills an empty memory folder from the newest snapshot. Returns the number of files, 0 if there was none."""
        self.init()
        if not self.has_commits():
            return 0
        if not self.is_empty_memory():
            raise HistoryError("the memory folder is not empty; recover only fills an empty one")
        with self.store._locked():
            self.git("checkout", "--force", "HEAD", "--", ".")
        return len(self.git("ls-files", "--cached").stdout.split())

    def log(self, mem_id=None, n=20):
        args = ["log", "-%d" % n, "--date=iso-strict", "--format=%h %ad %s"]
        if mem_id:
            args += ["--", str(self.store._path(mem_id).relative_to(self.store.root))]
        return self.git(*args).stdout

    def show(self, rev, mem_id=None):
        if mem_id:
            rel = self.store._path(mem_id).relative_to(self.store.root).as_posix()
            return self.git("show", "%s:%s" % (rev, rel), work_tree=False).stdout
        return self.git("show", "--stat", "--format=%h %ad%n%B", "--date=iso-strict", rev, work_tree=False).stdout

    def restore(self, mem_id, rev):
        """Writes `mem_id` as it was at `rev` back as the current version (logged and indexed), then snapshots."""
        meta, body = parse(self.show(rev, mem_id))
        with self.store._locked():
            self.store._write(mem_id, meta, body, "restore", by="owner", note="restored from history " + rev)
            self.store.write_index()
        self.snapshot("restore %s from %s" % (mem_id, rev))
        return mem_id

    def bundle(self, path):
        """The whole history in one file (`git clone <file>` reads it). For an off-host backup."""
        self.git("bundle", "create", str(Path(path).resolve()), "--all", work_tree=False)
        return Path(path)


def history_dir(cfg):
    return cfg["paths"].get("memory_history") or (cfg["root"] / "data" / "memory-history.git")


def open_history(cfg=None):
    if cfg is None:
        from dave import config
        cfg = config.load()
    return History(open_store(cfg, actor="owner"), history_dir(cfg))


def main(argv):
    h = open_history()
    cmd, args = (argv[0] if argv else ""), argv[1:]
    if cmd == "init" and not args:
        h.init()
        print("history at", h.git_dir)
    elif cmd == "snapshot" and len(args) <= 1:
        rev = h.snapshot(args[0] if args else None)
        print("snapshot", rev if rev else "skipped: nothing changed")
    elif cmd == "recover" and not args:
        n = h.recover()
        print("recovered %d files from history" % n if n else "no history to recover from")
        return 0 if n else 1
    elif cmd == "log" and len(args) <= 2:
        mem_id = next((a for a in args if not a.isdigit()), None)
        n = next((int(a) for a in args if a.isdigit()), 20)
        sys.stdout.write(h.log(mem_id, n))
    elif cmd == "show" and len(args) in (1, 2):
        sys.stdout.write(h.show(*args))
    elif cmd == "restore" and len(args) == 2:
        print("restored", h.restore(*args))
    elif cmd == "bundle" and len(args) == 1:
        print("wrote", h.bundle(args[0]))
    else:
        print(__doc__.strip().splitlines()[-2].strip() + "\n" + __doc__.strip().splitlines()[-1].strip())
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except HistoryError as e:
        print("history:", e, file=sys.stderr)
        sys.exit(1)
