"""Offline tests for tuxmine_extras.py: the mapping file, jar matching, license detection, resource extraction, the
DaveBridge release-commit search and the marked index blocks. No network: nothing here clones or calls ls-remote.

run: python3 -I -m unittest tools/decomp/test_tuxmine_extras.py   (from the repo root)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tuxmine_extras as tx  # noqa: E402

# The jars the packs shipped when the mapping was written: each must match exactly one entry.
KNOWN_JARS = {
    "gregguns-0.4.0-beta.jar": "0.4.0-beta",
    "lostcitiesnh-0.4.1-beta.jar": "0.4.1-beta",
    "fortunateone-v1.1.11.jar": "v1.1.11",
    "ezstorage-1.8.2.jar": "1.8.2",
    "gtnhrates-1.12.0-2.9.jar": "1.12.0-2.9",
    "qz_miner-5.5.1.jar": "5.5.1",
    "qz_uilib-5.0.0-beta5.jar": "5.0.0-beta5",
    "qz_uilib-core-java8-5.0.0-beta5.jar": "5.0.0-beta5",
    "qz_uilib-font-adapter-java8-5.0.0-beta5.jar": "5.0.0-beta5",
    "qz_uilib_compat-1.0.0-beta3.jar": "1.0.0-beta3",
    "worldedit-v0.0.9.jar": "v0.0.9",
    "davebridge-0.2.6.jar": "0.2.6",
    "DiscordIntegrationUnoffical-mc1.7.10-3.1.1_3.8.3_464.jar": "3.1.1_3.8.3_464",
    "journeymap-1.7.10-5.2.23-unlimited.jar": "5.2.23",
    "WorldEditCuiFe-v1.0.7-mf-1.7.10-10.13.4.1566.jar": None,
}

MIT = ("MIT License\n\nCopyright (c) 2024 Someone\n\nPermission is hereby granted, free of charge, to any person "
       "obtaining a copy of this software\n")


def jar(name, **kind):
    return {"name": name, "sha256": "0" * 64, "packs": ["server"], "path": None, "url": None, **kind}


def git(cwd, *args):
    env = dict(tx.GIT_ENV, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tx.load_config()

    def test_every_known_jar_matches_exactly_one_entry_with_its_version(self):
        for name, version in KNOWN_JARS.items():
            hits = [e for e in self.cfg["mods"] if e["_re"].fullmatch(name)]
            self.assertEqual(len(hits), 1, name)
            if version is not None:
                self.assertEqual(hits[0]["_re"].fullmatch(name).group("version"), version, name)

    def test_qz_uilib_entries_do_not_overlap(self):
        e = [x for x in self.cfg["mods"] if x["_re"].fullmatch("qz_uilib-core-java8-5.0.0-beta5.jar")]
        self.assertEqual(e[0]["repo"].rsplit("/", 1)[-1], "Qz-UILib-Core")

    def test_unmapped_jar_fails(self):
        with self.assertRaises(tx.Fail) as cm:
            tx.plan([jar("brandnewmod-1.0.jar")], self.cfg, [])
        self.assertIn("brandnewmod-1.0.jar", str(cm.exception))

    def test_pinned_commit_refuses_another_version(self):
        with self.assertRaises(tx.Fail) as cm:
            tx.plan([jar("DiscordIntegrationUnoffical-mc1.7.10-3.1.2_3.8.3_470.jar")], self.cfg, [])
        self.assertIn("3.1.2_3.8.3_470", str(cm.exception))

    def test_covered_needs_matching_ref(self):
        row = {"modId": "journeymap", "ref": "5.2.22", "path": "gtnh-src/source/journeymap-legacy/"}
        with self.assertRaises(tx.Fail):
            tx.plan([jar("journeymap-1.7.10-5.2.23-unlimited.jar")], self.cfg, [row])
        row["ref"] = "5.2.23"
        items = tx.plan([jar("journeymap-1.7.10-5.2.23-unlimited.jar")], self.cfg, [row])
        self.assertEqual(items[0]["dir"], "journeymap-legacy")

    def test_skip_is_planned_without_network(self):
        items = tx.plan([jar("WorldEditCuiFe-v1.0.7-mf-1.7.10-10.13.4.1566.jar")], self.cfg, [])
        self.assertEqual(items[0]["entry"]["kind"], "skip")


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_license_root(self):
        (self.d / "LICENSE").write_text(MIT)
        self.assertEqual(tx.detect_license(self.d), ("MIT", "LICENSE=MIT"))

    def test_license_template_falls_back_to_shipped_resource(self):
        (self.d / "LICENSE-template").write_text(MIT.replace("2024 Someone", "<year> <copyright holders>"))
        res = self.d / "src/main/resources"
        res.mkdir(parents=True)
        (res / "LICENSE").write_text(MIT.replace("2024 Someone", "[year] [fullname]"))
        lic, note = tx.detect_license(self.d)
        self.assertEqual(lic, "MIT")
        self.assertTrue(note.startswith("src/main/resources/LICENSE=MIT"), note)
        self.assertIn("unfilled template", note)

    def test_license_none_and_gpl_versions(self):
        self.assertEqual(tx.detect_license(self.d)[0], "none")
        (self.d / "COPYING").write_text("GNU LESSER GENERAL PUBLIC LICENSE Version 2.1, February 1999")
        self.assertEqual(tx.detect_license(self.d)[0], "LGPL-2.1")

    def test_token_class(self):
        (self.d / "gradle.properties").write_text("modId = x\ngenerateGradleTokenClass = com.example.x.Tags\n")
        self.assertEqual(tx.token_class(self.d), {"com.example.x.Tags"})
        (self.d / "gradle.properties").write_text("generateGradleTokenClass =\n")
        self.assertEqual(tx.token_class(self.d), set())

    def test_resources_and_classes(self):
        j = self.d / "m.jar"
        with zipfile.ZipFile(j, "w") as z:
            z.writestr("mcmod.info", '[{"modid": "m", "name": "M", "version": "1"},]')
            z.writestr("mixins.m.json", "{}")
            z.writestr("assets/m/lang/en_US.lang", "a=b\n")
            z.writestr("assets/m/textures/x.png", "png")
            z.writestr("com/x/shadow/lib.json", "{}")
            z.writestr("com/x/A.class", "")
            z.writestr("com/x/A$1.class", "")
            z.writestr("com/x/shadow/B.class", "")
            z.writestr("META-INF/versions/17/com/x/C.class", "")
            z.writestr("../evil.lang", "x")
        out = self.d / "out"
        self.assertEqual(tx.extract_resources(j, out), 3)
        self.assertTrue((out / "assets/m/lang/en_US.lang").is_file())
        self.assertFalse((self.d / "evil.lang").exists())
        info, classes = tx.jar_info(j)
        self.assertEqual(info[0]["modid"], "m")
        self.assertEqual(classes, {"com.x.A", "com.x.C"})

    def test_source_classes(self):
        p = self.d / "src/main/java/com/x"
        p.mkdir(parents=True)
        (p / "A.java").write_text("// c\npackage com.x;\nclass A {}\n")
        (p / "K.kt").write_text("package com.x\n")
        self.assertEqual(tx.source_classes(self.d), {"com.x.A", "com.x.K"})


class BlockTest(unittest.TestCase):
    def test_block_replaces_section_then_itself(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "S.md"
            p.write_text("# T\n\n## Mods\n\nrows\n\n## Our own mods\n\nold text\n")
            b1 = f"{tx.BEGIN}\n## Tuxmine extras\none\n{tx.END}\n"
            tx.write_block(p, b1, before="## Our own mods", replace_section="## Our own mods")
            txt = p.read_text()
            self.assertNotIn("old text", txt)
            self.assertIn("rows", txt)
            tx.write_block(p, b1.replace("one", "two"), replace_section="## Our own mods")
            txt = p.read_text()
            self.assertEqual(txt.count(tx.BEGIN), 1)
            self.assertIn("two", txt)
            self.assertNotIn("one", txt)

    def test_make_index_keeps_block(self):
        src = (HERE / "make_index.py").read_text()
        self.assertIn("tuxmine-extras:begin", src)


class ReleaseCommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Path(self.tmp.name)
        git(self.r, "init", "-q")
        (self.r / "DaveBridge").mkdir()
        self.commit("a", "DaveBridge: start")
        self.release = self.commit("b", "Ghost Dave (DaveBridge 1.2.3, packs 0.1.4)")
        self.commit("c", "DaveBridge 1.2.30 is something else")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, content, msg):
        (self.r / "DaveBridge" / "f.txt").write_text(content)
        git(self.r, "add", "-A")
        git(self.r, "commit", "-q", "-m", msg)
        return git(self.r, "rev-parse", "HEAD")

    def test_subject(self):
        commit, how = tx.find_release_commit(self.r, "DaveBridge", "1.2.3")
        self.assertEqual(commit, self.release)
        self.assertIn("subject", how)

    def test_tag_wins(self):
        first = git(self.r, "rev-list", "--max-parents=0", "HEAD")
        git(self.r, "tag", "davebridge-v1.2.3", first)
        self.assertEqual(tx.find_release_commit(self.r, "DaveBridge", "1.2.3")[0], first)

    def test_none_fails(self):
        with self.assertRaises(tx.Fail):
            tx.find_release_commit(self.r, "DaveBridge", "9.9.9")

    def test_snapshot(self):
        dest = self.r / "out" / "DaveBridge"
        self.assertTrue(tx.snapshot(self.r, "DaveBridge", self.release, dest))
        self.assertEqual((dest / "f.txt").read_text(), "b")
        self.assertTrue(tx.snapshot_ok(dest, self.release))
        self.assertFalse(tx.snapshot(self.r, "DaveBridge", self.release, dest))


if __name__ == "__main__":
    unittest.main()
