"""Tests of tools/doctor.py helpers (no real install is touched)."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import doctor  # noqa: E402


class ProfileDir(unittest.TestCase):
    def test_no_config_means_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, source = doctor.profile_dir(Path(tmp) / "none.json")
            self.assertEqual(path, doctor.DEFAULT_PROFILE)
            self.assertIn("default", source)

    def test_config_path_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"profile_dir": "~/firma-legal"}), encoding="utf-8")
            path, _ = doctor.profile_dir(cfg)
            self.assertEqual(path, Path.home() / "firma-legal")

    def test_broken_config_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            for text in ("{not json", json.dumps({"profile_dir": ""}), json.dumps({})):
                cfg.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(SystemExit):
                    doctor.profile_dir(cfg)


class EngineSkills(unittest.TestCase):
    def test_lists_only_folders_with_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills/a").mkdir(parents=True)
            (root / "skills/a/SKILL.md").write_text("x", encoding="utf-8")
            (root / "skills/b").mkdir()
            self.assertEqual(doctor.engine_skills(root), ["a"])
            self.assertEqual(doctor.engine_skills(root / "none"), [])

    def test_missing_venv_is_not_ready(self):
        self.assertFalse(doctor.venv_ready(Path("/nonexistent/python")))

    def test_browser_needs_package_and_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            (cache / "chromium-1").mkdir(parents=True)
            # a Chromium in the shared cache is not enough without the package in .venv
            self.assertFalse(doctor.playwright_ready(Path("/nonexistent/python"), (cache,)))
            # python3 here has no playwright package
            self.assertFalse(doctor.playwright_ready(Path(sys.executable), (cache,)))
            self.assertFalse(doctor.playwright_ready(Path(sys.executable), (Path(tmp) / "none",)))


class WatchIssues(unittest.TestCase):
    def test_counts_open_problems_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = Path(tmp)
            self.assertEqual(doctor.open_watch_issues(prof), 0)
            (prof / "laws").mkdir()
            (prof / "laws" / "issues.json").write_text("not json")
            self.assertEqual(doctor.open_watch_issues(prof), 0)
            (prof / "laws" / "issues.json").write_text(json.dumps(
                {"acts": {"a": {"state": "open"}, "b": {"state": "resolved"}, "c": {"state": "open"}}}))
            self.assertEqual(doctor.open_watch_issues(prof), 2)


class Vendor(unittest.TestCase):
    """VENDOR.json says which release is installed and which hosts the scripts read: it must stay true."""

    ROOT = Path(__file__).resolve().parents[2]

    def setUp(self):
        self.v = json.loads((self.ROOT / "VENDOR.json").read_text(encoding="utf-8"))

    def test_skills_and_modules_match(self):
        self.assertEqual(sorted(self.v["skills"]), doctor.engine_skills(self.ROOT))
        mods = json.loads((self.ROOT / "skills/legal-workflow/assets/modules.json").read_text(encoding="utf-8"))
        for m in mods["modules"].values():
            role = "core module" if m["core"] else "optional module"
            self.assertTrue(self.v["skills"][m["skill"]].startswith(role), m["skill"])

    def test_version_is_the_latest_release_in_the_changelog(self):
        import re
        text = (self.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        m = re.search(r"^## \[?(\d+\.\d+\.\d+)\]? — (\d{4}-\d{2}-\d{2})", text, re.M)
        self.assertIsNotNone(m, "CHANGELOG has no released version heading '## X.Y.Z — YYYY-MM-DD'")
        self.assertEqual((m.group(1), m.group(2)), (self.v["version"], self.v["released"]))
        self.assertIn(self.v["version"], doctor.engine_version(self.ROOT))

    def test_every_host_the_watch_scripts_read_is_declared(self):
        import re
        hosts = set()
        for py in (self.ROOT / "skills/legal-watch/scripts").rglob("*.py"):
            hosts |= set(re.findall(r"https?://([a-z0-9-]+(?:\.[a-z0-9-]+)+)", py.read_text(encoding="utf-8")))
        hosts -= {"schemas.openxmlformats.org"}   # an XML namespace, not a request
        self.assertLessEqual(hosts, set(self.v["network"]["hosts"]))



class FakeRun:
    """Stands in for subprocess.run: records argv and kwargs, answers with fixed text or raises."""

    def __init__(self, stdout: str = "", stderr: str = "", exc: BaseException | None = None, rc: int = 0):
        self.stdout, self.stderr, self.exc, self.rc = stdout, stderr, exc, rc
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


FAKE_PATH = "/opt/fake/bin/firecrawl"


def have(_name):
    return FAKE_PATH


class FirecrawlCli(unittest.TestCase):
    def test_absent(self):
        run = FakeRun()
        self.assertEqual(doctor.firecrawl_cli(which=lambda _n: None, run=run), "absent")
        self.assertEqual(run.calls, [])

    def test_logged_in(self):
        run = FakeRun("\x1b[32m●\x1b[0m Authenticated via stored credentials\nCredits: 990 / 1,000")
        self.assertEqual(doctor.firecrawl_cli(which=have, run=run), "logged-in")

    def test_not_logged_in(self):
        for out, err in (("Not authenticated\n", ""), ("", "\x1b[31mNOT AUTHENTICATED\x1b[0m")):
            with self.subTest(out=out, err=err):
                state = doctor.firecrawl_cli(which=have, run=FakeRun(out, err))
                self.assertEqual(state, "not-logged-in")
                self.assertNotEqual(state, "logged-in")

    def test_strict_login_state(self):
        """Logged in only on exit 0 with a line that starts with "authenticated" and nothing contrary."""
        cases = [
            (FakeRun("Unauthenticated\n"), "not-logged-in"),
            (FakeRun("\x1b[33m✗\x1b[0m unauthenticated: run firecrawl login"), "not-logged-in"),
            (FakeRun("Error: authenticated request failed", rc=1), "unknown"),
            (FakeRun("Authenticated", rc=1), "unknown"),
            (FakeRun("Not authenticated", rc=1), "not-logged-in"),
            (FakeRun("", "unauthenticated", rc=2), "not-logged-in"),
            (FakeRun("Authentication failed"), "unknown"),
            (FakeRun("Authenticated\nError: credits unavailable"), "unknown"),
            (FakeRun("Authenticated", "Invalid API key"), "unknown"),
            (FakeRun("Authenticated", "not authenticated"), "not-logged-in"),
            (FakeRun("Status: authenticated"), "unknown"),          # not at the start of a line
            (FakeRun("authenticatedly odd"), "unknown"),
            (FakeRun("  ● Authenticated via FIRECRAWL login\nCredits: 10"), "logged-in"),
            (FakeRun("\x1b[1m\x1b[32m✓ AUTHENTICATED\x1b[0m\r\n"), "logged-in"),
        ]
        for run, want in cases:
            with self.subTest(out=run.stdout, err=run.stderr, rc=run.rc):
                self.assertEqual(doctor.firecrawl_cli(which=have, run=run), want)

    def test_unknown_on_odd_output_timeout_and_error(self):
        cases = (FakeRun("something else entirely"), FakeRun(""), FakeRun(None, None),
                 FakeRun(exc=subprocess.TimeoutExpired(["firecrawl"], 20)),
                 FakeRun(exc=OSError("cannot execute")),
                 FakeRun(exc=subprocess.CalledProcessError(1, ["firecrawl"])))
        for run in cases:
            with self.subTest(run=run.exc or run.stdout):
                self.assertEqual(doctor.firecrawl_cli(which=have, run=run), "unknown")

    def test_runs_only_status_without_key_flags(self):
        run = FakeRun("Authenticated")
        doctor.firecrawl_cli(which=have, run=run, timeout=5)
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, [FAKE_PATH, "--status"])
        for bad in ("--api-key", "view-config", "env", "login"):
            self.assertNotIn(bad, argv)
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 5)
        self.assertTrue(kwargs["capture_output"])

    def test_every_state_has_one_doctor_line(self):
        self.assertEqual(set(doctor.FIRECRAWL_LINES), {"absent", "logged-in", "not-logged-in", "unknown"})
        self.assertIs(doctor.FIRECRAWL_LINES["logged-in"][0], True)
        for state in ("absent", "not-logged-in", "unknown"):
            self.assertIsNone(doctor.FIRECRAWL_LINES[state][0])   # optional: never MISS

    def _main(self, run: FakeRun, which=have) -> tuple[int, str]:
        real = doctor.firecrawl_cli
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(doctor, "firecrawl_cli", lambda: real(which=which, run=run)), \
                mock.patch.object(doctor, "venv_ready", return_value=True), \
                mock.patch.object(doctor, "playwright_ready", return_value=False), \
                mock.patch.object(doctor, "engine_skills", return_value=[]), \
                mock.patch.object(doctor, "profile_dir", return_value=(Path(tmp), "test")), \
                contextlib.redirect_stdout(out):
            code = doctor.main()
        return code, out.getvalue()

    def test_main_never_prints_cli_output(self):
        for text in ("Authenticated SECRET-MARKER-123", "Not authenticated SECRET-MARKER-123",
                     "SECRET-MARKER-123"):
            with self.subTest(text=text):
                code, printed = self._main(FakeRun(text, "SECRET-MARKER-123"))
                self.assertNotIn("SECRET-MARKER-123", printed)
                self.assertEqual(sum("Firecrawl CLI" in ln for ln in printed.splitlines()), 1)
                self.assertEqual(code, 0)   # never counted as missing

    def test_main_lines_match_the_contract(self):
        expected = {
            "Authenticated": "OK   Firecrawl CLI — logged in: may read official pages that refuse plain requests, "
                             "no guarantee (paid service you connected)",
            "Not authenticated": "--   Firecrawl CLI — installed, not logged in: run firecrawl login --browser yourself",
            "???": "--   Firecrawl CLI — installed, login state unknown: run firecrawl --status yourself",
        }
        for text, want in expected.items():
            with self.subTest(text=text):
                self.assertIn(want, self._main(FakeRun(text))[1].splitlines())
        _, printed = self._main(FakeRun(), which=lambda _n: None)
        self.assertIn("--   Firecrawl CLI — optional: may read official pages that refuse plain requests, no "
                      "guarantee; monitoring scripts need this CLI: npm i -g firecrawl-cli, then firecrawl login "
                      "--browser", printed.splitlines())

    def test_install_runs_no_npm(self):
        install = (Path(__file__).resolve().parents[2] / "install.sh").read_text(encoding="utf-8")
        self.assertNotRegex(install, r"(?m)^\s*npm\s")
        self.assertIn("firecrawl", install)

if __name__ == "__main__":
    unittest.main()
