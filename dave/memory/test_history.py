"""Tests for dave/memory/history.py (needs the git CLI).

    python3 -m unittest dave.memory.test_history
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dave.memory import store as st  # noqa: E402
from dave.memory.history import History, HistoryError  # noqa: E402


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.s = st.Store(base / "memory", "2.9.0")
        self.h = History(self.s, base / "history" / "memory.git")

    def tearDown(self):
        self.tmp.cleanup()

    def commits(self):
        return self.h.git("log", "--format=%s", work_tree=False).stdout.splitlines() if self.h.has_commits() else []

    def test_snapshot_records_writes_and_skips_when_unchanged(self):
        self.assertIsNone(self.h.snapshot())                      # empty folder: nothing to record
        self.s.save("playbook", "Best nitrogen at HV", "Use the air distillation chain.", by="dave")
        self.s.player_note("11111111-2222-3333-4444-555555555555", "base at 100 64 -200", field="base",
                           name="Steve", asked_by="Steve")
        rev = self.h.snapshot()
        self.assertTrue(rev)
        self.assertIsNone(self.h.snapshot())                      # unchanged: no new commit
        msg = self.h.git("log", "-1", "--format=%B", work_tree=False).stdout
        self.assertIn("save playbook/best-nitrogen-at-hv", msg)
        self.assertIn("(for Steve)", msg)
        self.assertRegex(msg, r"Memory-Log-Lines: \d+")
        self.s.update("playbook/best-nitrogen-at-hv", body="Use the air distillation chain, then a centrifuge.")
        self.h.snapshot()
        self.assertEqual(2, len(self.commits()))
        self.assertTrue(self.commits()[0].startswith("1 memory write"))

    def test_lock_objects_and_temp_files_are_not_tracked(self):
        self.s.save("lessons", "Check the cleanroom", "Laser engraving wafers needs a cleanroom.")
        (self.s.root / "lessons" / ".tmp-abc.part").write_text("half written")
        self.h.snapshot()
        tracked = self.h.git("ls-files").stdout.split()
        self.assertIn("lessons/check-the-cleanroom.md", tracked)
        self.assertIn("INDEX.md", tracked)
        self.assertIn(".log.jsonl", tracked)
        self.assertFalse(any(t.startswith(".objects/") or t == ".lock" or ".tmp-" in t for t in tracked), tracked)

    def test_restore_brings_back_an_old_version_through_the_store(self):
        self.s.save("server", "Spawn rules", "No building within 50 blocks of spawn.")
        first = self.h.snapshot()
        self.s.update("server/spawn-rules", body="Build anywhere.")
        self.h.snapshot()
        self.h.restore("server/spawn-rules", first)
        self.assertIn("No building within 50 blocks", self.s.get("server/spawn-rules")[1])
        log = (self.s.root / ".log.jsonl").read_text()
        self.assertIn("restored from history " + first, log)
        self.assertTrue(self.commits()[0].startswith("restore server/spawn-rules"))

    def test_recover_fills_an_empty_folder_and_refuses_a_full_one(self):
        self.s.save("playbook", "Steel", "Electric Blast Furnace at MV.")
        self.h.snapshot()
        with self.assertRaises(HistoryError):
            self.h.recover()
        shutil.rmtree(self.s.root)                                # the data volume was lost
        fresh = st.Store(self.s.root, "2.9.0")
        h2 = History(fresh, self.h.git_dir)
        self.assertGreater(h2.recover(), 0)
        self.assertIn("Electric Blast Furnace", fresh.get("playbook/steel")[1])
        self.assertIsNone(h2.snapshot())                          # recovered state is the snapshot: no change

    def test_recover_without_history(self):
        self.assertEqual(0, self.h.recover())

    def test_bundle_is_a_clonable_backup(self):
        self.s.save("lessons", "Fluids need ids", "Use the fluid id, not its name.")
        self.h.snapshot()
        out = Path(self.tmp.name) / "memory.bundle"
        self.h.bundle(out)
        clone = Path(self.tmp.name) / "clone"
        import subprocess
        subprocess.run(["git", "clone", "--quiet", str(out), str(clone)], check=True)
        self.assertTrue((clone / "lessons" / "fluids-need-ids.md").exists())


if __name__ == "__main__":
    unittest.main()
