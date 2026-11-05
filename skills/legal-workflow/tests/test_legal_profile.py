"""Tests of scripts/legal_profile.py on throw-away profiles (the real profile is never touched)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import legal_profile as lp  # noqa: E402

CATALOG = lp.load_catalog()
STATUS_TABLE = """# Integration status

| Step | Status | Updated | Note |
|---|---|---|---|
| firms | done | 2026-11-04 | |
| audience | skipped | 2026-11-04 | |
| modules | done | 2026-11-04 | |
| language | done | 2026-11-04 | |
| side-risk | done | 2026-11-04 | default norms |
"""


def make_profile(root: Path, *, status: str = STATUS_TABLE, modules: dict | None = None) -> Path:
    prof = root / "legal-profile"
    (prof / "context").mkdir(parents=True)
    for name in ("company.md", "language.md", "side-and-risk.md"):
        (prof / "context" / name).write_text("x\n", encoding="utf-8")
    (prof / "context" / "integration-status.md").write_text(status, encoding="utf-8")
    mods = {"schema_version": 1, "privacy": True, "consumer": False} if modules is None else modules
    (prof / "modules.json").write_text(json.dumps(mods), encoding="utf-8")
    return prof


def make_siblings(root: Path, *skills: str) -> Path:
    sib = root / "skills"
    for name in skills:
        (sib / name).mkdir(parents=True)
        (sib / name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    sib.mkdir(exist_ok=True)
    return sib


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ResolveProfile(TmpCase):
    def test_no_config_means_default(self):
        path, source = lp.resolve_profile(self.root / "none.json")
        self.assertEqual(path, lp.DEFAULT_PROFILE)
        self.assertIn("default", source)

    def test_config_path_is_expanded(self):
        cfg = self.root / "c.json"
        cfg.write_text(json.dumps({"profile_dir": "~/firma-legal"}), encoding="utf-8")
        path, source = lp.resolve_profile(cfg)
        self.assertEqual(path, Path.home() / "firma-legal")
        self.assertIn("config", source)

    def test_broken_config_fails_loudly(self):
        cfg = self.root / "c.json"
        cfg.write_bytes(b"\xff")
        with self.assertRaises(lp.ConfigError):
            lp.resolve_profile(cfg)
        for text in ("{not json", json.dumps({"profile_dir": ""}), json.dumps({}), json.dumps([1]),
                     json.dumps({"profile_dir": "relative/path"})):
            cfg.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(lp.ConfigError):
                lp.resolve_profile(cfg)

    def test_profile_inside_engine_is_refused(self):
        cfg = self.root / "c.json"
        for inside in (lp.ENGINE_ROOT, lp.ENGINE_ROOT / "legal-profile"):
            cfg.write_text(json.dumps({"profile_dir": str(inside)}), encoding="utf-8")
            with self.subTest(inside=inside), self.assertRaises(lp.ProfileLocationError):
                lp.resolve_profile(cfg)

    def test_link_inside_profile_into_engine_is_refused(self):
        """Codex review: a matters/ link into the checkout put private intake data in the public repository."""
        (self.root / "matters").symlink_to(lp.ENGINE_ROOT / "skills")
        with self.assertRaises(lp.MatterError):
            lp.matter_new(self.root, "nda", "NDA", "contracts", CATALOG)
        self.assertFalse(any((lp.ENGINE_ROOT / "skills").glob("*-nda")))
        with self.assertRaises(lp.SetupError):
            lp._write_atomic(self.root / "matters" / "x.json", "{}", lp.SetupError)

    def test_log_link_into_engine_is_refused(self):
        (self.root / "matters").mkdir()
        target = lp.ENGINE_ROOT / "skills" / "never-log.md"
        (self.root / "matters" / "log.md").symlink_to(target)
        with self.assertRaises(lp.MatterError):
            lp._append_log(self.root / "matters", "2026-11-05", "m", "contracts", "new", "note")
        self.assertFalse(target.exists())


class Catalog(TmpCase):
    def test_shipped_catalog_is_valid(self):
        self.assertEqual(set(lp.optional_ids(CATALOG)), {"privacy", "consumer", "trademark", "employment"})
        self.assertEqual(CATALOG["steps"]["laws"], "laws/watchlist.yaml")

    def test_broken_catalogs(self):
        bad = [
            "{",
            json.dumps([1]),
            json.dumps({"steps": {}, "modules": {}}),
            json.dumps({"steps": ["a"], "modules": {"m": {"skill": "s", "core": True}}}),
            json.dumps({"steps": {"a": 1}, "modules": {"m": {"skill": "s", "core": True}}}),
            json.dumps({"steps": {"a": None}, "base_needs": ["b"], "modules": {"m": {"skill": "s", "core": True}}}),
            json.dumps({"steps": {"a": None}, "modules": {"m": {"skill": "s"}}}),
            json.dumps({"steps": {"a": None}, "modules": {"m": {"skill": "s", "core": True, "needs": ["z"]}}}),
        ]
        path = self.root / "cat.json"
        for text in bad:
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(lp.CatalogError):
                lp.load_catalog(path)

    def test_missing_catalog(self):
        with self.assertRaises(lp.CatalogError):
            lp.load_catalog(self.root / "none.json")


class Modules(TmpCase):
    def test_missing_file_is_none(self):
        self.assertIsNone(lp.read_modules(self.root, CATALOG))

    def test_unset_optional_modules_are_off(self):
        prof = make_profile(self.root)
        self.assertEqual(lp.read_modules(prof, CATALOG),
                         {"privacy": True, "consumer": False, "trademark": False, "employment": False})

    def test_bad_modules_files(self):
        for content in ("{", json.dumps({"privacy": True}), json.dumps({"schema_version": 2}),
                        json.dumps({"schema_version": 1, "contracts": True}),
                        json.dumps({"schema_version": 1, "privacy": "yes"}), json.dumps([1])):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "modules.json").write_text(content, encoding="utf-8")
                with self.assertRaises(lp.ModulesFileError):
                    lp.read_modules(Path(tmp), CATALOG)


class Steps(TmpCase):
    def test_table_is_read_and_missing_rows_are_pending(self):
        steps = lp.read_steps(make_profile(self.root), CATALOG)
        self.assertEqual(steps["firms"], "done")
        self.assertEqual(steps["audience"], "skipped")
        self.assertEqual(steps["niches"], "pending")

    def test_done_without_file_is_pending(self):
        prof = make_profile(self.root)
        (prof / "context" / "language.md").unlink()
        self.assertEqual(lp.read_steps(prof, CATALOG)["language"], "pending")

    def test_niches_done_without_watchlist_is_pending(self):
        prof = make_profile(self.root, status=STATUS_TABLE + "| niches | done | | |\n")
        self.assertEqual(lp.read_steps(prof, CATALOG)["niches"], "pending")
        (prof / "laws").mkdir()
        (prof / "laws" / "watchlist.yaml").write_text("acts: []\n", encoding="utf-8")
        self.assertEqual(lp.read_steps(prof, CATALOG)["niches"], "done")

    def test_unreadable_status_file(self):
        prof = make_profile(self.root)
        (prof / "context" / "integration-status.md").write_bytes(b"\xff\xfe")
        with self.assertRaises(lp.StatusFileError):
            lp.read_steps(prof, CATALOG)

    def test_unknown_state_fails(self):
        prof = make_profile(self.root, status="| firms | maybe | | |\n")
        with self.assertRaises(lp.StatusFileError):
            lp.read_steps(prof, CATALOG)

    def test_no_status_file_all_pending(self):
        self.assertEqual(set(lp.read_steps(self.root, CATALOG).values()), {"pending"})


class StepSet(TmpCase):
    def test_creates_replaces_and_appends(self):
        prof = self.root / "p"
        prof.mkdir()
        (prof / "context").mkdir()
        (prof / "context" / "company.md").write_text("x\n", encoding="utf-8")
        lp.step_set(prof, "firms", "DONE", CATALOG, "two firms", "2026-11-04")
        lp.step_set(prof, "language", "skipped", CATALOG, date="2026-11-04")
        lp.step_set(prof, "firms", "pending", CATALOG, "redo | later", "2026-11-05")
        text = (prof / "context" / "integration-status.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("| firms |"), 1)
        self.assertIn("| firms | pending | 2026-11-05 | redo \\| later |", text)
        self.assertEqual(lp.read_steps(prof, CATALOG)["language"], "skipped")

    def test_duplicate_rows_of_the_step_become_one(self):
        on = "| reading | done | 2026-11-04 | conversation: on; monitoring: on |"
        off = "| reading | skipped | 2026-11-04 | not connected |"
        for rows in ((on, on), (on, off), (off, on)):
            with self.subTest(rows=rows):
                table = STATUS_TABLE + "\n".join(rows) + "\n| tools | done | 2026-11-04 | |\n"
                prof = make_profile(Path(tempfile.mkdtemp(dir=self.root)), status=table)
                lp.step_set(prof, "reading", "done", CATALOG, "conversation: on; monitoring: off", "2026-11-05")
                lines = (prof / "context" / "integration-status.md").read_text(encoding="utf-8").splitlines()
                mine = [x for x in lines if x.startswith("| reading |")]
                self.assertEqual(mine, ["| reading | done | 2026-11-05 | conversation: on; monitoring: off |"])
                self.assertLess(lines.index(mine[0]), lines.index("| tools | done | 2026-11-04 | |"))
                self.assertEqual(lp.read_steps(prof, CATALOG)["firms"], "done")

    def test_appends_table_to_a_file_without_one(self):
        prof = make_profile(self.root, status="# Integration status\n\nfree text\n")
        lp.step_set(prof, "tools", "done", CATALOG)
        self.assertEqual(lp.read_steps(prof, CATALOG)["tools"], "done")

    def test_errors(self):
        prof = make_profile(self.root)
        for args in (("nope", "done", None), ("firms", "maybe", None), ("firms", "done", "5 Nov")):
            with self.subTest(args=args), self.assertRaises(lp.StatusFileError):
                lp.step_set(prof, args[0], args[1], CATALOG, date=args[2])
        with self.assertRaises(lp.StatusFileError):
            lp.step_set(self.root / "nope", "firms", "done", CATALOG)
        with self.assertRaises(lp.StatusFileError):
            lp.step_set(prof, "laws", "done", CATALOG)  # no laws/watchlist.yaml yet


class Status(TmpCase):
    def test_ready_profile(self):
        prof = make_profile(self.root)
        sib = make_siblings(self.root, "legal-contracts", "legal-privacy", "legal-consumer")
        out = lp.status(prof, "test", CATALOG, siblings=sib)
        self.assertTrue(out["ready"])
        self.assertEqual(out["missing_steps"], [])
        self.assertEqual(out["modules"]["contracts"], "core")
        self.assertEqual(out["modules"]["privacy"], "on")
        self.assertEqual(out["modules"]["consumer"], "off")
        self.assertEqual(out["modules"]["employment"], "not-installed")

    def test_module_with_extra_needs(self):
        prof = make_profile(self.root)
        sib = make_siblings(self.root, "legal-watch")
        out = lp.status(prof, "test", CATALOG, module="watch", siblings=sib)
        self.assertFalse(out["ready"])
        self.assertEqual(out["missing_steps"], ["niches", "laws"])
        self.assertEqual(out["module_state"], "core")

    def test_missing_profile(self):
        out = lp.status(self.root / "nope", "test", CATALOG, siblings=make_siblings(self.root))
        self.assertFalse(out["exists"])
        self.assertFalse(out["ready"])
        self.assertEqual(out["missing_steps"], CATALOG["base_needs"])

    def test_unknown_module(self):
        with self.assertRaises(lp.LegalProfileError):
            lp.status(make_profile(self.root), "test", CATALOG, module="tax")

    def test_no_modules_file_means_unset_not_off(self):
        sib = make_siblings(self.root, "legal-privacy")
        self.assertEqual(lp.module_state("privacy", CATALOG, None, sib), "unset")
        prof = make_profile(self.root)
        (prof / "modules.json").unlink()
        out = lp.status(prof, "test", CATALOG, module="privacy", siblings=sib)
        self.assertEqual(out["module_state"], "unset")
        self.assertIn("modules", out["missing_steps"])


class Matters(TmpCase):
    def setUp(self):
        super().setUp()
        self.prof = make_profile(self.root)

    def test_new_creates_folder_intake_and_log(self):
        out = lp.matter_new(self.prof, "nda-acme", "NDA | with Acme\nSRL", "contracts", CATALOG, "2026-11-04")
        self.assertEqual(out["id"], "2026-11-04-nda-acme")
        intake = json.loads((self.prof / "matters" / out["id"] / "intake.json").read_text(encoding="utf-8"))
        self.assertEqual(intake["task_id"], out["id"])
        self.assertEqual(intake["module"], "contracts")
        self.assertEqual(intake["title"], "NDA | with Acme SRL")
        self.assertTrue((self.prof / "matters" / out["id"] / "input").is_dir())
        self.assertTrue((self.prof / "matters" / out["id"] / "output").is_dir())
        self.assertEqual(lp.matter_list(self.prof)[0]["title"], "NDA | with Acme SRL")
        log = (self.prof / "matters" / "log.md").read_text(encoding="utf-8")
        self.assertTrue(log.startswith("# Matters log"))
        self.assertIn("| 2026-11-04 | 2026-11-04-nda-acme | contracts | opened | NDA \\| with Acme SRL |", log)

    def test_same_name_gets_suffix(self):
        ids = [lp.matter_new(self.prof, "nda", "t", "contracts", CATALOG, "2026-11-04")["id"] for _ in range(3)]
        self.assertEqual(ids, ["2026-11-04-nda", "2026-11-04-nda-02", "2026-11-04-nda-03"])

    def test_bad_inputs(self):
        cases = [("NDA", "t", "contracts", None), ("a" * 61, "t", "contracts", None),
                 ("nda", "t", "tax", None), ("nda", "  ", "contracts", None),
                 ("nda", "t", "contracts", "04.11.2026")]
        for slug, title, module, date in cases:
            with self.subTest(slug=slug, module=module, date=date), self.assertRaises(lp.MatterError):
                lp.matter_new(self.prof, slug, title, module, CATALOG, date)

    def test_no_profile(self):
        with self.assertRaises(lp.MatterError):
            lp.matter_new(self.root / "nope", "nda", "t", "contracts", CATALOG)

    def test_log_and_list(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")["id"]
        b = lp.matter_new(self.prof, "policy", "Privacy policy", "privacy", CATALOG, "2026-11-02")["id"]
        lp.matter_log(self.prof, a, "waiting", "asked for the counterparty name", "2026-11-03")
        lp.matter_log(self.prof, a, "note", "draft v1 ready", "2026-11-04")
        lp.matter_log(self.prof, b, "done", "", "2026-11-04")
        items = {i["id"]: i for i in lp.matter_list(self.prof)}
        self.assertEqual(items[a]["status"], "waiting")
        self.assertEqual(items[a]["updated"], "2026-11-04")
        self.assertEqual(items[a]["title"], "NDA")
        self.assertEqual(items[b]["status"], "done")
        self.assertEqual([i["id"] for i in lp.matter_list(self.prof, only_open=True)], [a])

    def test_show(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")["id"]
        lp.matter_log(self.prof, a, "waiting", "q", "2026-11-02")
        lp.matter_log(self.prof, a, "note", "n", "2026-11-03")
        out = lp.matter_show(self.prof, a)
        self.assertEqual(out["status"], "waiting")
        self.assertEqual([e["event"] for e in out["events"]], ["opened", "waiting", "note"])
        self.assertEqual(out["intake"]["module_data"], {})
        (self.prof / "matters" / a / "intake.json").write_text("[1]", encoding="utf-8")
        with self.assertRaises(lp.MatterError):
            lp.matter_show(self.prof, a)

    def test_failed_create_leaves_no_folder(self):
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(lp.MatterError):
                lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")
        self.assertFalse((self.prof / "matters" / "2026-11-01-nda").exists())
        self.assertEqual(lp.matter_list(self.prof), [])

    def test_unreadable_log(self):
        lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG)
        (self.prof / "matters" / "log.md").write_bytes(b"\xff")
        with self.assertRaises(lp.MatterError):
            lp.matter_list(self.prof)

    def test_log_errors(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG)["id"]
        for event in ("signed", "opened"):
            with self.subTest(event=event), self.assertRaises(lp.MatterError):
                lp.matter_log(self.prof, a, event)
        with self.assertRaises(lp.MatterError):
            lp.matter_log(self.prof, "../etc", "note")
        with self.assertRaises(lp.MatterError):
            lp.matter_log(self.prof, "2026-01-01-none", "note")
        (self.prof / "matters" / a / "intake.json").write_text("{", encoding="utf-8")
        with self.assertRaises(lp.MatterError):
            lp.matter_log(self.prof, a, "note")

    def test_list_without_log(self):
        self.assertEqual(lp.matter_list(self.prof), [])

    def test_update_merges_core_and_module_data(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")["id"]
        lp.matter_update(self.prof, a, {"represented_party": "Example SRL", "module_data": {"action": "draft"}})
        out = lp.matter_update(self.prof, a, {"module_data": {"document_type": "NDA"}, "unknowns": ["forum"]})
        self.assertEqual(out["updated"], ["module_data", "unknowns"])
        intake = lp.matter_show(self.prof, a)["intake"]
        self.assertEqual(intake["represented_party"], "Example SRL")
        self.assertEqual(intake["module_data"], {"action": "draft", "document_type": "NDA"})
        self.assertEqual(intake["unknowns"], ["forum"])
        self.assertEqual(intake["task_id"], a)
        self.assertEqual(list((self.prof / "matters" / a).glob("*.tmp")), [])

    def test_update_refusals(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")["id"]
        for data in ({}, [], {"task_id": "x"}, {"module": "privacy"}, {"parties": []}, {"module_data": []},
                     {"module_data": {}}, {"input_files": "x"}, {"unknowns": None}, {"represented_party": 5}):
            with self.subTest(data=data), self.assertRaises(lp.MatterError):
                lp.matter_update(self.prof, a, data)
        with self.assertRaises(lp.MatterError):
            lp.matter_update(self.prof, "2026-01-01-none", {"unknowns": []})
        intake = self.prof / "matters" / a / "intake.json"
        intake.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        with self.assertRaisesRegex(lp.MatterError, "legal-workflow-update"):
            lp.matter_update(self.prof, a, {"unknowns": []})

    def test_update_write_failure_keeps_old_intake(self):
        a = lp.matter_new(self.prof, "nda", "NDA", "contracts", CATALOG, "2026-11-01")["id"]
        before = (self.prof / "matters" / a / "intake.json").read_text(encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=OSError("disk full")), self.assertRaises(lp.MatterError):
            lp.matter_update(self.prof, a, {"unknowns": ["x"]})
        self.assertEqual((self.prof / "matters" / a / "intake.json").read_text(encoding="utf-8"), before)
        self.assertEqual(list((self.prof / "matters" / a).glob("*.tmp")), [])


class ProfileInit(TmpCase):
    def test_creates_folders_status_and_config_then_is_idempotent(self):
        cfg = self.root / "cfg" / "config.json"
        target = self.root / "prof"
        out = lp.profile_init(str(target), cfg)
        self.assertEqual(out["profile"], str(target))
        self.assertTrue(out["config_written"])
        self.assertFalse(out["existed"])
        for sub in lp.PROFILE_DIRS:
            self.assertTrue((target / sub).is_dir())
        self.assertIn("| Step | Status |", (target / lp.STATUS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), {"profile_dir": str(target)})
        (target / "context" / "company.md").write_text("mine\n", encoding="utf-8")
        again = lp.profile_init(None, cfg)
        self.assertEqual((again["created"], again["config_written"], again["existed"]), ([], False, True))
        self.assertEqual((target / "context" / "company.md").read_text(encoding="utf-8"), "mine\n")

    def test_default_folder_without_config(self):
        cfg = self.root / "config.json"
        with mock.patch.object(lp, "DEFAULT_PROFILE", self.root / "legal-profile"):
            out = lp.profile_init(None, cfg)
        self.assertEqual(out["profile"], str(self.root / "legal-profile"))
        self.assertTrue(cfg.is_file())

    def test_switch_is_required_to_repoint(self):
        cfg = self.root / "config.json"
        lp.profile_init(str(self.root / "a"), cfg)
        with self.assertRaises(lp.SetupError) as ctx:
            lp.profile_init(str(self.root / "b"), cfg)
        self.assertIn("--switch", str(ctx.exception))
        out = lp.profile_init(str(self.root / "b"), cfg, switch=True)
        self.assertTrue(out["config_written"])
        self.assertTrue((self.root / "a" / "context").is_dir())  # the old profile is left alone

    def test_refusals(self):
        cfg = self.root / "config.json"
        for raw in ("relative/path", "  "):
            with self.assertRaises(lp.SetupError):
                lp.profile_init(raw, cfg)
        with self.assertRaises(lp.SetupError):
            lp.profile_init(str(Path.home()), cfg)
        with self.assertRaises(lp.SetupError):
            lp.profile_init("/", cfg)
        with self.assertRaises(lp.ProfileLocationError):
            lp.profile_init(str(lp.ENGINE_ROOT / "profile"), cfg)
        (self.root / "file").write_text("x", encoding="utf-8")
        with self.assertRaises(lp.SetupError):
            lp.profile_init(str(self.root / "file"), cfg)
        cfg.write_text("{broken", encoding="utf-8")
        with self.assertRaises(lp.ConfigError):
            lp.profile_init(str(self.root / "p"), cfg)

    def test_os_errors_are_typed(self):
        cfg = self.root / "config.json"
        with mock.patch.object(Path, "mkdir", side_effect=OSError("read-only")), self.assertRaises(lp.SetupError):
            lp.profile_init(str(self.root / "p"), cfg)
        with mock.patch.object(Path, "replace", side_effect=OSError("disk full")), \
                self.assertRaises(lp.SetupError):
            lp.profile_init(str(self.root / "q"), cfg)
        self.assertFalse(cfg.exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])


    def test_refuses_a_folder_that_contains_the_engine(self):
        with self.assertRaises(lp.ProfileLocationError):
            lp.profile_init(str(lp.ENGINE_ROOT.parent), self.root / "config.json")
        with self.assertRaises(lp.SetupError):  # home reached through "..": compared after resolving
            lp.profile_init(str(Path.home() / "x" / ".."), self.root / "config.json")

    def test_missing_configured_folder_is_not_recreated_silently(self):
        cfg = self.root / "config.json"
        gone = self.root / "volume" / "legal-profile"
        cfg.write_text(json.dumps({"profile_dir": str(gone)}), encoding="utf-8")
        with self.assertRaises(lp.SetupError) as ctx:
            lp.profile_init(None, cfg)
        self.assertIn("disk not connected", str(ctx.exception))
        self.assertFalse(gone.exists())
        self.assertEqual(lp.profile_init(None, cfg, create=True)["profile"], str(gone))

    def test_symlinked_config_is_written_through(self):
        real = self.root / "dotfiles" / "config.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"profile_dir": str(self.root / "a")}), encoding="utf-8")
        link = self.root / "config.json"
        link.symlink_to(real)
        lp.profile_init(str(self.root / "b"), link, switch=True)
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(real.read_text(encoding="utf-8"))["profile_dir"], str(self.root / "b"))


class ModulesSet(TmpCase):
    def test_new_file_lists_every_optional_module(self):
        prof = self.root / "p"
        prof.mkdir()
        out = lp.modules_set(prof, CATALOG, ["privacy=on", "consumer=OFF"])
        self.assertEqual(out["changed"], ["privacy"])
        data = json.loads((prof / "modules.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(set(data) - {"schema_version"}, set(lp.optional_ids(CATALOG)))
        self.assertEqual(lp.read_modules(prof, CATALOG)["privacy"], True)

    def test_keeps_untouched_values(self):
        prof = make_profile(self.root)
        out = lp.modules_set(prof, CATALOG, ["employment=on"])
        self.assertEqual((out["modules"]["privacy"], out["modules"]["employment"]), (True, True))
        self.assertEqual(lp.modules_set(prof, CATALOG, ["employment=on"])["changed"], [])

    def test_refusals(self):
        prof = make_profile(self.root)
        cases = ([], ["contracts=on"], ["tax=on"], ["privacy"], ["privacy=yes"], ["privacy=on", "privacy=off"])
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(lp.SetupError):
                lp.modules_set(prof, CATALOG, changes)
        with self.assertRaises(lp.SetupError):
            lp.modules_set(self.root / "none", CATALOG, ["privacy=on"])
        (prof / "modules.json").write_text('{"schema_version": 0}', encoding="utf-8")
        with self.assertRaises(lp.ModulesFileError):
            lp.modules_set(prof, CATALOG, ["privacy=on"])
        self.assertEqual(json.loads((prof / "modules.json").read_text(encoding="utf-8")), {"schema_version": 0})


    def test_read_only_profile_gives_typed_errors(self):
        prof = make_profile(self.root)
        with mock.patch.object(lp.tempfile, "mkstemp", side_effect=PermissionError("read-only")):
            with self.assertRaises(lp.SetupError):
                lp.modules_set(prof, CATALOG, ["privacy=off"])
            with self.assertRaises(lp.StatusFileError):
                lp.step_set(prof, "tools", "done", CATALOG)
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("read-only")), \
                self.assertRaises(lp.StatusFileError) as ctx:
            lp.step_set(prof, "tools", "done", CATALOG)
        self.assertIn("cannot create", str(ctx.exception))


class SkippedModules(TmpCase):
    def test_skipped_modules_step_means_off_not_unset(self):
        prof = make_profile(self.root)
        (prof / "modules.json").unlink()
        sib = make_siblings(self.root, "legal-privacy")
        self.assertEqual(lp.status(prof, "test", CATALOG, "privacy", sib)["module_state"], "unset")
        lp.step_set(prof, "modules", "skipped", CATALOG)
        out = lp.status(prof, "test", CATALOG, "privacy", sib)
        self.assertEqual((out["module_state"], out["missing_steps"]), ("off", []))


class Cli(TmpCase):
    def run_cli(self, *args: str, config: dict | None = None, siblings: Path | None = None) -> tuple[int, str, str]:
        cfg = self.root / "config.json"
        if config is not None:
            cfg.write_text(json.dumps(config), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(lp, "CONFIG", cfg), mock.patch.object(lp, "SIBLINGS", siblings or self.root / "none"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lp.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_where_status_module_and_matters(self):
        prof = make_profile(self.root)
        cfg = {"profile_dir": str(prof)}
        sib = make_siblings(self.root, "legal-contracts")
        code, out, _ = self.run_cli("where", config=cfg)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["profile"], str(prof))
        self.assertTrue((Path(json.loads(out)["engine"]) / "install.sh").is_file())
        code, out, _ = self.run_cli("status", "--module", "contracts", config=cfg, siblings=sib)
        self.assertTrue(json.loads(out)["ready"])
        code, out, _ = self.run_cli("module", "privacy", config=cfg, siblings=sib)
        self.assertEqual(json.loads(out)["state"], "not-installed")
        code, out, _ = self.run_cli("matter", "new", "--slug", "nda", "--title", "NDA", "--module", "contracts",
                                    "--date", "2026-11-04", config=cfg)
        self.assertEqual(json.loads(out)["id"], "2026-11-04-nda")
        code, out, _ = self.run_cli("matter", "log", "2026-11-04-nda", "--event", "done", config=cfg)
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("matter", "list", "--open", config=cfg)
        self.assertEqual(json.loads(out), [])
        code, out, _ = self.run_cli("matter", "show", "2026-11-04-nda", config=cfg)
        self.assertEqual(json.loads(out)["status"], "done")
        code, out, _ = self.run_cli("matter", "update", "2026-11-04-nda", "--data",
                                    '{"module_data": {"action": "audit"}}', config=cfg)
        self.assertEqual(code, 0)
        data = self.root / "data.json"
        data.write_text(json.dumps({"document_language": "ro"}), encoding="utf-8")
        code, out, _ = self.run_cli("matter", "update", "2026-11-04-nda", "--data", f"@{data}", config=cfg)
        intake = json.loads(self.run_cli("matter", "show", "2026-11-04-nda", config=cfg)[1])["intake"]
        self.assertEqual((intake["module_data"], intake["document_language"]), ({"action": "audit"}, "ro"))
        code, _, err = self.run_cli("matter", "update", "2026-11-04-nda", "--data", "{bad", config=cfg)
        self.assertEqual(code, 2)
        self.assertIn("not readable JSON", err)
        code, out, _ = self.run_cli("step", "set", "tools", "--status", "done", config=cfg)
        self.assertEqual(json.loads(out)["step"], "tools")
        code, out, _ = self.run_cli("modules", "set", "trademark=on", config=cfg)
        self.assertEqual((code, json.loads(out)["changed"]), (0, ["trademark"]))

    def test_profile_init_cli(self):
        target = self.root / "fresh"
        code, out, _ = self.run_cli("profile", "init", "--dir", str(target))
        self.assertEqual((code, json.loads(out)["profile"]), (0, str(target)))
        code, out, _ = self.run_cli("where")
        self.assertEqual(json.loads(out)["profile"], str(target))
        code, _, err = self.run_cli("profile", "init", "--dir", str(self.root / "other"))
        self.assertEqual(code, 2)
        self.assertIn("SetupError", err)
        code, out, _ = self.run_cli("profile", "init", "--dir", str(self.root / "other"), "--switch")
        self.assertEqual(code, 0)

    def test_errors_exit_2_with_message(self):
        code, out, err = self.run_cli("where", config={"profile_dir": ""})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("ConfigError", err)
        code, _, err = self.run_cli("module", "tax", config={"profile_dir": str(self.root / "p")})
        self.assertEqual(code, 2)
        self.assertIn("unknown module", err)



class ReadingStep(TmpCase):
    """Step `reading` (Firecrawl, optional) is first in the wizard and never a need of any module."""

    def test_reading_is_first_and_not_needed(self):
        self.assertEqual(list(CATALOG["steps"])[0], "reading")
        self.assertIsNone(CATALOG["steps"]["reading"])
        self.assertNotIn("reading", CATALOG["base_needs"])
        for mid, mod in CATALOG["modules"].items():
            with self.subTest(module=mid):
                self.assertNotIn("reading", mod["needs"])

    def test_reading_done_without_file(self):
        prof = make_profile(self.root)
        lp.step_set(prof, "reading", "done", CATALOG, note="conversation: on; monitoring: off", date="2026-11-05")
        self.assertEqual(lp.read_steps(prof, CATALOG)["reading"], "done")

    def test_pending_reading_does_not_block_ready(self):
        prof = make_profile(self.root)
        sib = make_siblings(self.root, "legal-contracts")
        self.assertEqual(lp.read_steps(prof, CATALOG)["reading"], "pending")
        out = lp.status(prof, "test", CATALOG, siblings=sib)
        self.assertTrue(out["ready"])
        self.assertNotIn("reading", out["missing_steps"])

if __name__ == "__main__":
    unittest.main()
