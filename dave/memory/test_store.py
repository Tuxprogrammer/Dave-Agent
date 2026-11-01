"""Offline tests for the memory store and the dave-memory MCP server.

Run:  python3 -I dave/memory/test_store.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from dave.memory import store as st  # noqa: E402

UUID = "069a79f4-44e9-4726-a5be-fca90e38aaf5"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s = st.Store(self.root, "2.9.0")

    def tearDown(self):
        self.tmp.cleanup()

    def log(self):
        return [json.loads(x) for x in (self.root / ".log.jsonl").read_text().splitlines()]

    def test_frontmatter_round_trip(self):
        meta = {"title": "3", "tags": ["a", "b"], "revision": 2, "flag": True, "note": "x: y", "q": "\"quoted"}
        meta2, body = st.parse(st.render(meta, "Body text\n\n## H\n- x"))
        self.assertEqual(meta2, meta)
        self.assertEqual(body, "Body text\n\n## H\n- x\n")

    def test_save_recall_get(self):
        mid = self.s.save("playbook", "Best nitrogen source at HV", "Question: N2 at HV\nAnswer: centrifuge air",
                          tags=["nitrogen", "HV"], player="Alex")
        self.assertEqual(mid, "playbook/best-nitrogen-source-at-hv")
        self.s.save("server", "Spawn has a shared EBF", "Anyone may use it.")
        hits = self.s.recall("nitrogen hv")
        self.assertEqual(hits[0][1]["id"], mid)
        meta, body, status = self.s.get(mid)
        self.assertEqual((status, meta["pack"], meta["player_name"], meta["tags"]), ("active", "2.9.0", "Alex", ["hv", "nitrogen"]))
        self.assertIn("INDEX.md", os.listdir(self.root))
        self.assertIn(mid, (self.root / "INDEX.md").read_text())
        self.assertEqual(self.s.recall("nitrogen", kind="server"), [])

    def test_near_duplicate_refused(self):
        mid = self.s.save("playbook", "Best nitrogen source at HV", "x")
        with self.assertRaises(st.DuplicateError) as cm:
            self.s.save("playbook", "Best Nitrogen source at HV!", "y")
        self.assertEqual(cm.exception.existing_id, mid)
        self.assertIn("memory_update", str(cm.exception))
        other = self.s.save("playbook", "Best nitrogen source at EV", "z")   # another tier is another question
        self.assertNotEqual(other, mid)
        new = self.s.save("playbook", "Best nitrogen source at HV", "better", supersedes=mid)
        self.assertEqual(self.s.get(mid)[2], "superseded")
        self.assertEqual(self.s.get(mid)[0]["superseded_by"], new)

    def test_update_logs_and_restore(self):
        mid = self.s.save("lessons", "Centrifuge needs circuit 2", "The HV centrifuge recipe for X needs circuit 2.")
        self.s.update(mid, body="Needs programmed circuit 2, not 1.", tags=["centrifuge"], note="clarify")
        meta, body, _ = self.s.get(mid)
        self.assertEqual((meta["revision"], meta["tags"]), (2, ["centrifuge"]))
        entries = self.log()
        self.assertEqual([e["op"] for e in entries], ["save", "update"])
        self.assertIsNone(entries[0]["before"])
        self.assertEqual(entries[1]["before"], entries[0]["after"])
        self.s.restore(mid, entries[0]["after"])
        self.assertIn("circuit 2.", self.s.get(mid)[1])
        self.assertEqual(self.log()[-1]["op"], "restore")

    def test_correct_playbook_supersedes(self):
        self.s.ensure_player(UUID, "Alex")
        mid = self.s.save("playbook", "Best nitrogen source at HV", "Answer: electrolyze saltpeter")
        new = self.s.correct(mid, "Air centrifuge is cheaper", "Alex", body="Answer: centrifuge air")
        self.assertNotEqual(new, mid)
        old_meta, _, old_status = self.s.get(mid)
        new_meta, new_body, new_status = self.s.get(new)
        self.assertEqual((old_status, old_meta["superseded_by"]), ("superseded", new))
        self.assertEqual((new_status, new_meta["supersedes"]), ("active", mid))
        self.assertEqual(new_meta["corrections"][0]["by"], "Alex")
        self.assertEqual(new_meta["corrections"][0]["uuid"], UUID)
        self.assertIn("centrifuge air", new_body)
        self.assertEqual([d["id"] for _, d in self.s.recall("nitrogen")], [new])
        with self.assertRaises(st.MemoryStoreError):
            self.s.correct(mid, "again", "Alex")

    def test_correct_in_place_for_other_kinds(self):
        mid = self.s.save("server", "Nether portal at spawn", "At 0,0.")
        self.assertEqual(self.s.correct(mid, "It moved to 100,64,-20", "Bea"), mid)
        meta, body, _ = self.s.get(mid)
        self.assertIn("Corrected by Bea", body)
        self.assertEqual(meta["revision"], 2)

    def test_forget_archives(self):
        mid = self.s.save("server", "Rule: no lag machines", "No chunk-loaded mob farms.")
        self.s.forget(mid, "rule dropped")
        self.assertTrue(self.s._path(mid).exists())
        meta, _, status = self.s.get(mid)
        self.assertEqual((status, meta["archived_reason"]), ("archived", "rule dropped"))
        self.assertEqual(self.s.recall("lag machines"), [])
        self.assertEqual(self.s.list("server"), [])
        self.assertEqual(len(self.s.list("server", "archived")), 1)
        self.assertNotIn(mid, (self.root / "INDEX.md").read_text())

    def test_stale_on_pack_change(self):
        mid = self.s.save("playbook", "EBF steel chain", "Answer: ...")
        newer = st.Store(self.root, "2.9.1")
        self.assertEqual(newer.get(mid)[2], "stale")
        self.assertEqual(newer.recall("steel"), [])
        self.assertEqual(newer.recall("steel", include_stale=True)[0][1]["status"], "stale")
        newer.update(mid, reverify=True)
        self.assertEqual(newer.get(mid)[2], "active")
        self.assertEqual(self.s.get(mid)[2], "stale")      # and stale for the old pack now

    def test_players(self):
        with self.assertRaises(st.MemoryStoreError):
            self.s.player_note("Nobody", "likes bees")
        pid, _ = self.s.player_note(UUID, "HV", field="tier", name="Alex")
        self.assertEqual(pid, "players/" + UUID)
        self.s.player_note("alex", "has a cleanroom", field="setup")
        self.assertEqual(self.s.player_note("Alex", "Has a cleanroom", field="setup")[1], "already noted")
        self.s.player_note(UUID.replace("-", "").upper(), "EV", field="tier")
        meta, body, _ = self.s.get(pid)
        self.assertEqual(meta["tier"], "EV")
        self.assertNotIn("HV", body)
        self.assertIn("has a cleanroom (since", body)
        self.s.ensure_player(UUID, "Alexander")
        self.assertEqual(self.s.find_player("Alex"), pid)          # old name still resolves
        self.assertEqual(self.s.get(pid)[0]["name"], "Alexander")
        with self.assertRaises(st.MemoryStoreError):
            self.s.save("players", "x", "y")

    def test_turn_context(self):
        self.s.player_note(UUID, "HV", field="tier", name="Alex")
        self.s.player_note(UUID, "prefers short answers", field="preferences")
        self.s.save("server", "Server rules", "Be nice. No lag machines.", tags=["pinned"])
        self.s.save("server", "Shared oxygen line at spawn", "A free oxygen pipe runs to the spawn workshop.")
        self.s.save("lessons", "Saltpeter nitrogen is a trap", "Always compare against the air centrifuge.")
        self.s.save("playbook", "Best nitrogen source at HV", "Answer: centrifuge air")
        ctx = st.load_turn_context(UUID, "best nitrogen source? I have oxygen", store=self.s)
        self.assertLessEqual(len(ctx), 1500)
        for needle in ("Alex", "HV", "prefers short answers", "Server rules", "Shared oxygen", "Saltpeter",
                       "playbook/best-nitrogen-source-at-hv"):
            self.assertIn(needle, ctx)
        self.assertLessEqual(len(st.load_turn_context(UUID, "x", limit=200, store=self.s)), 200)
        self.assertIn("no profile yet", st.load_turn_context(None, None, player_name="Zed", store=self.s))

    def test_asked_by_logged(self):
        mid = self.s.save("server", "Spawn portal", "At 0,0.", player="Alex")
        self.s.update(mid, body="At 10,0.", asked_by="Bea")
        self.s.forget(mid, "moved away", asked_by="Cy")
        self.s.correct(self.s.save("lessons", "Circuit 2", "x"), "it is circuit 3", "Dee")
        self.s.player_note(UUID, "HV", field="tier", name="Eve", asked_by="Eve")
        self.assertEqual([e.get("asked_by") for e in self.log()], ["Alex", "Bea", "Cy", None, "Dee", None, "Eve"])

    def test_bad_ids(self):
        for bad in ("../x", "playbook/../../etc", "nope/x", "playbook/"):
            with self.assertRaises(st.MemoryStoreError):
                self.s.get(bad)


    def test_temp_files_are_never_memories(self):
        mid = self.s.save("playbook", "Best nitrogen source at HV", "Answer: air centrifuge")
        text = (self.root / (mid + ".md")).read_text()
        # A writer killed after writing its temp file but before the rename, in the old naming and the new one.
        old_md = self.root / "playbook" / ".tmp-dead1.md"
        old_part = self.root / "playbook" / ".tmp-dead2.part"
        young = self.root / "playbook" / ".tmp-live.part"
        for f in (old_md, old_part, young):
            f.write_text(text)
        for f in (old_md, old_part):
            os.utime(f, (1, 1))
        self.s.forget(mid, "wrong")
        self.assertEqual(self.s.recall("nitrogen"), [], "a temp copy must not bring a forgotten memory back")
        self.assertNotIn(".tmp", (self.root / "INDEX.md").read_text())
        self.s.save("playbook", "Best nitrogen source at HV", "Answer: something else")   # no duplicate refusal
        st.Store(self.root, "2.9.0")                       # opening the store removes dead writers' leftovers
        self.assertFalse(old_md.exists() or old_part.exists())
        self.assertTrue(young.exists(), "a young temp file may be a live write: kept")

    def test_writes_never_leave_md_named_temp_files(self):
        seen = []
        real = st.tempfile.mkstemp

        def spy(*a, **kw):
            fd, name = real(*a, **kw)
            seen.append(name)
            return fd, name
        st.tempfile.mkstemp = spy
        try:
            self.s.save("lessons", "Check the coil tier", "EBF recipes need the right coils.")
        finally:
            st.tempfile.mkstemp = real
        self.assertTrue(seen)
        self.assertTrue(all(not n.endswith(".md") for n in seen), seen)

    def test_file_vanishing_mid_listing_is_skipped(self):
        self.s.save("server", "Server rules", "Be nice.")
        (self.root / "server" / "ghost.md").symlink_to(self.root / "server" / "nowhere.md")
        self.assertEqual([m["id"] for m in self.s.list("server")], ["server/server-rules"])
        self.assertTrue(self.s.recall("rules"))

    def test_profile_text_outside_sections_is_kept(self):
        pid = self.s.ensure_player(UUID, "Alex")
        self.s.update(pid, body="# Alex\nLives at the big castle at 100,64,200. Prefers short answers.")
        self.s.correct(pid, "actually Alex is on EV now", "Alex")
        self.s.player_note(UUID, "has a cleanroom", "setup")
        _, body, _ = self.s.get(pid)
        self.assertIn("Lives at the big castle", body)
        self.assertIn("actually Alex is on EV now", body)
        self.assertIn("## Setup\n- has a cleanroom", body)
        self.assertEqual(body.count("# Alex"), 1)
        ctx = st.load_turn_context(UUID, None, "Alex", store=self.s)
        self.assertIn("big castle", ctx)
        self.assertIn("Corrections: Corrected by Alex", ctx)
        self.s.player_note(UUID, "likes trains", "preferences")   # a second rewrite keeps everything too
        _, body2, _ = self.s.get(pid)
        self.assertIn("Lives at the big castle", body2)
        self.assertIn("actually Alex is on EV now", body2)


class ServerTest(unittest.TestCase):
    def test_json_rpc_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, DAVE_MEMORY_DIR=tmp, DAVE_PACK_VERSION="2.9.0")
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_save", "arguments": {
                    "kind": "playbook", "title": "Best nitrogen source at HV", "body": "Answer: centrifuge air",
                    "player": "Alex"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "memory_recall", "arguments": {"query": "nitrogen"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "memory_save", "arguments": {
                    "kind": "playbook", "title": "best nitrogen source at hv", "body": "dup"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "nope"},
            ]
            proc = subprocess.run([sys.executable, "-I", str(HERE / "server.py")], env=env, capture_output=True,
                                  text=True, timeout=30, input="".join(json.dumps(m) + "\n" for m in msgs))
            replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
            self.assertEqual(sorted(replies), [1, 2, 3, 4, 5, 6], proc.stderr)
            self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "dave-memory")
            names = {t["name"] for t in replies[2]["result"]["tools"]}
            self.assertEqual(names, {"memory_recall", "memory_get", "memory_save", "memory_update", "memory_correct",
                                     "memory_forget", "player_get", "player_note", "memory_list"})
            self.assertFalse(replies[3]["result"]["isError"])
            self.assertIn("playbook/best-nitrogen-source-at-hv", replies[4]["result"]["content"][0]["text"])
            self.assertTrue(replies[5]["result"]["isError"])
            self.assertIn("memory_update", replies[5]["result"]["content"][0]["text"])
            self.assertEqual(replies[6]["error"]["code"], -32601)
            self.assertTrue((Path(tmp) / "playbook" / "best-nitrogen-source-at-hv.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
