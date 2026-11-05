"""The `firecrawl` engine: argv, format per site, JSON parsing, error mapping, and that no key or stderr leaks.

No real CLI and no network: `run` and `which` are fakes; the JSON is synthetic.
"""

from __future__ import annotations

import json
import plistlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
from watch import library as lib, schedule  # noqa: E402
from watch import fetchers as F  # noqa: E402

REPO = SKILL.parents[1]
FAKE_BIN = "/opt/fake/bin/firecrawl"
LEGIS = "https://www.legis.md/cautare/getResults?doc_id=1&lang=ro"
EURLEX = "https://eur-lex.europa.eu/eli/dir/2011/83/oj"
# The Gazette is the allowlisted HTML site: the tests that need Firecrawl to run on HTML use it.
GAZETTE = "https://monitorul.gov.md/ro/monitor/view/1"
HTML = "<html><head><title>Act</title></head><body><p>Articolul 1</p></body></html>"
MD = "# Lege\n\nArticolul 1. Text of the act.\n"
MARKER = "SECRET-MARKER-123"


def proc(stdout: str = "", stderr: str = "", rc: int = 0):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class FakeRun:
    """Records each call; returns `out` or raises it."""

    def __init__(self, out):
        self.out, self.calls = out, []

    def __call__(self, argv, **kw):
        cwd = kw.get("cwd")
        self.calls.append({"argv": argv, "kw": kw, "cwd_existed": bool(cwd) and Path(cwd).is_dir()})
        if isinstance(self.out, BaseException):
            raise self.out
        return self.out


def fetcher(out, *, which=lambda name: FAKE_BIN, **kw) -> tuple[F.FirecrawlFetcher, FakeRun]:
    run = FakeRun(out)
    return F.FirecrawlFetcher(run=run, which=which, pause_range=(0, 0), **kw), run


def payload(fmt: str, content: str, **meta) -> str:
    return json.dumps({fmt: content, "metadata": meta})


class Lists(unittest.TestCase):
    def test_engine_lists_include_firecrawl(self):
        self.assertEqual(F.ENGINES, ("urllib", "playwright", "command", "firecrawl"))
        self.assertEqual(lib.ENGINES, ("urllib", "playwright", "command", "firecrawl", "host"))
        self.assertEqual(lib.default_settings()["engines"], ["urllib"])
        out = lib.validate_watchlist({"settings": {"engines": ["urllib", "firecrawl", "host"]}, "acts": []})
        self.assertEqual(out["settings"]["engines"], ["urllib", "firecrawl", "host"])

    def test_format_by_host(self):
        for url in (LEGIS, "https://legis.md/x", "http://WWW.LEGIS.MD/y"):
            self.assertEqual(F.firecrawl_format(url), "markdown", url)
        for url in (GAZETTE, "https://www.monitorul.gov.md/ro"):
            self.assertEqual(F.firecrawl_format(url), "rawHtml", url)
        # an allowlist: any other site gets no format, so Firecrawl is not used there
        for url in (EURLEX, "https://legislatie.just.ro/Public/DetaliiDocument/1", "https://web.archive.org/web/2026/x",
                    "https://publications.europa.eu/resource/celex/32011L0083", "not a url", ""):
            self.assertIsNone(F.firecrawl_format(url), url)
        self.assertIsNone(F.firecrawl_format(LEGIS, {}))
        self.assertEqual(F.firecrawl_format(EURLEX, {"eur-lex.europa.eu": "markdown"}), "markdown")

    def test_argv_exact_and_safe(self):
        argv = F.firecrawl_argv(FAKE_BIN, LEGIS, "markdown")
        self.assertEqual(argv, [FAKE_BIN, "scrape", LEGIS, "--format", "markdown", "--max-age", "0", "--json"])
        for bad in ("--api-key", "login", "view-config", "env"):
            self.assertNotIn(bad, argv)
        for url in ("--api-key=x", "file:///etc/passwd", "ftp://example.com/a", "", "https://"):
            with self.assertRaises(F.FetchConfigError, msg=url):
                F.firecrawl_argv(FAKE_BIN, url, "rawHtml")


class Parse(unittest.TestCase):
    def test_parse_json_bare_and_wrapped(self):
        bare = payload("rawHtml", HTML, statusCode=200, url=EURLEX)
        self.assertEqual(F.parse_firecrawl_json(bare, "rawHtml"), (HTML, {"statusCode": 200, "url": EURLEX}))
        wrapped = json.dumps({"success": True, "data": {"markdown": MD, "metadata": {"title": "T"}}})
        self.assertEqual(F.parse_firecrawl_json(wrapped, "markdown"), (MD, {"title": "T"}))
        self.assertEqual(F.parse_firecrawl_json(json.dumps({"rawHtml": HTML, "metadata": []}), "rawHtml")[1], {})
        # no html <-> rawHtml fallback: trimmed html may lack the metadata the parsers need
        cases = {
            payload("html", HTML): "firecrawl: format rawHtml not returned",
            "not json": "firecrawl: unreadable output",
            "[1, 2]": "firecrawl: unreadable output",
            "": "firecrawl: no page content",
            payload("rawHtml", "  "): "firecrawl: no page content",
            json.dumps({"success": False, "error": MARKER}): "firecrawl: the service reported a failure",
        }
        for bad, msg in cases.items():
            with self.subTest(bad=bad), self.assertRaises(F.FirecrawlOutputError) as cm:
                F.parse_firecrawl_json(bad, "rawHtml")
            self.assertEqual(str(cm.exception), msg)
            self.assertNotIn(MARKER, str(cm.exception))
        with self.assertRaises(F.FirecrawlOutputError) as cm:
            F.parse_firecrawl_json(payload("rawHtml", HTML), "html")
        self.assertEqual(str(cm.exception), "firecrawl: format html not returned")


class Get(unittest.TestCase):
    def test_get_runs_without_shell_in_temp_cwd(self):
        f, run = fetcher(proc(payload("markdown", MD, statusCode=200)))
        f.get(LEGIS)
        call = run.calls[0]
        self.assertEqual(call["argv"], F.firecrawl_argv(FAKE_BIN, LEGIS, "markdown"))
        self.assertFalse(call["kw"].get("shell", False))
        self.assertNotIn("env", call["kw"])
        self.assertTrue(call["cwd_existed"])
        cwd = Path(call["kw"]["cwd"]).resolve()
        self.assertFalse(cwd.is_relative_to(REPO.resolve()))
        self.assertFalse(cwd.exists())                     # removed after the call
        self.assertIs(call["kw"]["stdin"], subprocess.DEVNULL)
        self.assertEqual(call["kw"]["timeout"], 120)
        self.assertTrue(call["kw"]["capture_output"] and call["kw"]["text"])

    def test_explicit_binary_skips_which(self):
        def which(name):
            raise AssertionError("which must not be called")
        f, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200)), which=which, binary="/opt/x/firecrawl")
        self.assertEqual(f.get(GAZETTE).status, 200)
        self.assertEqual(run.calls[0]["argv"][0], "/opt/x/firecrawl")

    def test_markdown_page_for_legis(self):
        f, _ = fetcher(proc(payload("markdown", MD, statusCode=200, title="Lege nr. 1", url=LEGIS)))
        res = f.get(LEGIS)
        self.assertEqual((res.via, res.html, res.markdown, res.status, res.title), ("firecrawl", "", MD, 200,
                                                                                    "Lege nr. 1"))
        self.assertFalse(res.blocked)
        self.assertIsNone(res.error)
        self.assertEqual(res.notes, [])

    def test_html_page_status_and_final_url(self):
        moved = "https://monitorul.gov.md/ro/monitor/view/2"
        f, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200, url=moved)))
        res = f.get(GAZETTE)
        self.assertEqual(run.calls[0]["argv"][4], "rawHtml")
        self.assertEqual((res.final_url, res.title, res.html, res.markdown), (moved, "Act", HTML, ""))
        self.assertIn("Articolul 1", res.text)
        # a missing or non-http metadata url keeps the requested one
        f, _ = fetcher(proc(payload("rawHtml", HTML, statusCode=200, url="about:blank")))
        self.assertEqual(f.get(GAZETTE).final_url, GAZETTE)

    def test_missing_or_invalid_status_is_a_failed_fetch(self):
        """A page without a real status is never a 200: not verified, the next engine may try."""
        for meta in ({}, {"statusCode": None}, {"statusCode": True}, {"statusCode": False}, {"statusCode": "abc"},
                     {"statusCode": 99}, {"statusCode": 600}, {"statusCode": "2000"}, {"statusCode": 200.0},
                     {"statusCode": "²⁰⁰"}, []):
            with self.subTest(meta=meta):
                f, _ = fetcher(proc(json.dumps({"rawHtml": HTML, "metadata": meta})))
                res = f.get(GAZETTE)
                self.assertEqual((res.status, res.error), (None, "firecrawl: page status not reported"))
                self.assertFalse(res.blocked)

    def test_numeric_string_status_is_normalised(self):
        f, _ = fetcher(proc(payload("rawHtml", HTML, statusCode="403")))
        res = f.get(GAZETTE)
        self.assertEqual((res.status, res.blocked), (403, True))
        f, _ = fetcher(proc(payload("rawHtml", HTML, statusCode=" 200 ")))
        res = f.get(GAZETTE)
        self.assertEqual((res.status, res.error, res.notes), (200, None, []))

    def test_target_403_is_blocked(self):
        for fmt, url, body in (("rawHtml", GAZETTE, HTML), ("markdown", LEGIS, MD)):
            f, _ = fetcher(proc(payload(fmt, body, statusCode=403)))
            res = f.get(url)
            self.assertTrue(res.blocked, fmt)
            self.assertEqual(res.status, 403)
            self.assertIsNone(res.error)

    def test_target_404_is_error_not_blocked(self):
        f, _ = fetcher(proc(payload("rawHtml", HTML, statusCode=404)))
        res = f.get(GAZETTE)
        self.assertFalse(res.blocked)
        self.assertEqual(res.error, "HTTP 404 (reported by Firecrawl)")

    def test_markdown_challenge_is_blocked(self):
        challenge = "# Just a moment...\n\nEfectuarea verificării de securitate\n"
        f, _ = fetcher(proc(payload("markdown", challenge, statusCode=200)))
        res = f.get(LEGIS)
        self.assertTrue(res.blocked)
        self.assertIn("just a moment", res.blocked_reason)
        self.assertIsNone(res.error)
        # the same page through a user `command` engine
        cmd = F.CommandFetcher("fetch {url}", run=lambda *a, **kw: proc(challenge), pause_range=(0, 0))
        self.assertTrue(cmd.get(LEGIS).blocked)
        # and in saved fixtures
        self.assertTrue(F.fixture_result(LEGIS, "", markdown=challenge).blocked)
        self.assertFalse(F.fixture_result(LEGIS, "", markdown=MD).blocked)

    def test_exit_codes_map_to_fixed_messages(self):
        cases = {
            f"Error: Insufficient credits {MARKER}": "firecrawl: out of credits (plan limit reached)",
            f"Error: Request failed with status code 402 {MARKER}": "firecrawl: out of credits (plan limit reached)",
            f"Error: Not authenticated {MARKER}": "firecrawl: not logged in (run firecrawl login --browser yourself)",
            f"Error: 401 Unauthorized {MARKER}": "firecrawl: not logged in (run firecrawl login --browser yourself)",
            f"Invalid API key {MARKER}": "firecrawl: not logged in (run firecrawl login --browser yourself)",
            f"Error: Rate limit exceeded {MARKER}": "firecrawl: rate limited",
            f"HTTP 429 {MARKER}": "firecrawl: rate limited",
        }
        for stderr, msg in cases.items():
            f, _ = fetcher(proc(stdout=MARKER, stderr=stderr, rc=1))
            res = f.get(GAZETTE)
            self.assertEqual(res.error, msg, stderr)
            self.assertNotIn(MARKER, repr(res), stderr)
        other = f"Error: something odd {MARKER}"
        f, _ = fetcher(proc(stderr=other, rc=3))
        res = f.get(GAZETTE)
        self.assertEqual(res.error, f"firecrawl: exit 3, {len(other)} bytes on stderr")
        self.assertNotIn(MARKER, repr(res))
        self.assertEqual((res.via, res.status, res.blocked), ("firecrawl", None, False))

    def test_timeout_and_missing_binary(self):
        f, run = fetcher(proc(), which=lambda name: None)
        self.assertEqual(f.get(GAZETTE).error, "firecrawl: CLI not found on PATH (npm i -g firecrawl-cli, then "
                                              "firecrawl login --browser)")
        self.assertEqual(run.calls, [])
        f, _ = fetcher(subprocess.TimeoutExpired(["firecrawl"], 120))
        self.assertEqual(f.get(GAZETTE).error, "firecrawl: timed out after 120 s")
        f, _ = fetcher(PermissionError(MARKER))
        res = f.get(GAZETTE)
        self.assertEqual(res.error, "firecrawl: could not start (PermissionError)")
        self.assertNotIn(MARKER, repr(res))

    def test_non_json_output_is_unreadable_never_a_page(self):
        """No sniffing of non-JSON stdout: an error printed with exit 0 must not pass as a page."""
        for out, url in ((HTML, GAZETTE), (MD, LEGIS), (f"Error: Not authenticated {MARKER}", LEGIS)):
            with self.subTest(out=out[:20]):
                f, _ = fetcher(proc(out))
                res = f.get(url)
                self.assertEqual((res.error, res.status, res.html, res.markdown),
                                 ("firecrawl: unreadable output", None, "", ""))
                self.assertNotIn(MARKER, repr(res))
        for empty in ("", "  \n"):
            f, _ = fetcher(proc(empty))
            self.assertEqual(f.get(GAZETTE).error, "firecrawl: no page content")
        f, _ = fetcher(proc(payload("rawHtml", "")))       # JSON without content: same honest failure
        self.assertEqual(f.get(GAZETTE).error, "firecrawl: no page content")
        f, _ = fetcher(proc("[1, 2]"))
        self.assertEqual(f.get(GAZETTE).error, "firecrawl: unreadable output")
        f, _ = fetcher(proc(json.dumps({"success": False, "error": MARKER})))
        res = f.get(GAZETTE)
        self.assertEqual(res.error, "firecrawl: the service reported a failure")
        self.assertNotIn(MARKER, repr(res))
        f, _ = fetcher(proc(payload("html", HTML, statusCode=200)))    # rawHtml asked, only trimmed html came
        self.assertEqual(f.get(GAZETTE).error, "firecrawl: format rawHtml not returned")


class Chain(unittest.TestCase):
    def test_build_chain_with_firecrawl(self):
        chain = F.build_chain(["urllib", "firecrawl"], pause_range=(0, 0))
        self.assertEqual(len(chain.fetchers), 2)
        self.assertIsInstance(chain.fetchers[1], F.FirecrawlFetcher)
        self.assertEqual(chain.names, ["urllib", "firecrawl"])

        class Blocked:
            def get(self, url):
                return F.page_result(url, "<title>Just a moment...</title>", status=403, via="urllib")

        fc, _ = fetcher(proc(payload("markdown", MD, statusCode=200)))
        chain = F.ChainFetcher([Blocked(), fc], names=["urllib", "firecrawl"])
        res = chain.get(LEGIS)
        self.assertEqual((res.via, res.markdown), ("firecrawl", MD))
        self.assertEqual([a["via"] for a in chain.attempts], ["urllib", "firecrawl"])
        self.assertTrue(res.notes[0].startswith("engine failed, next tried: urllib:"))

    def test_unknown_engine_message_lists_firecrawl(self):
        with self.assertRaises(F.FetchConfigError) as cm:
            F.build_chain(["curl"])
        self.assertIn("firecrawl", str(cm.exception))


def fake_which(found: dict[str, str]):
    return lambda name: found.get(name)


SYS = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
TOOLS = {"firecrawl": "/opt/fake/bin/firecrawl", "node": "/opt/node/bin/node"}


class SchedulePath(unittest.TestCase):
    def test_launch_path_includes_cli_and_node_dirs(self):
        self.assertEqual(schedule.launch_path(fake_which(TOOLS)), f"/opt/fake/bin:/opt/node/bin:{SYS}")
        self.assertEqual(schedule.launch_path(fake_which({})), SYS)
        # same folder twice, or a system folder: kept once, in first-seen order
        both = {"firecrawl": "/usr/local/bin/firecrawl", "node": "/usr/local/bin/node"}
        self.assertEqual(schedule.launch_path(fake_which(both)), "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin")
        self.assertEqual(schedule.launch_path(fake_which({"node": "/opt/node/bin/node"})), f"/opt/node/bin:{SYS}")

    def test_plist_has_path(self):
        prof = Path("/tmp/profile-x")
        data = plistlib.loads(schedule.plist(prof, which=fake_which(TOOLS)))
        self.assertEqual(data["EnvironmentVariables"]["PATH"], f"/opt/fake/bin:/opt/node/bin:{SYS}")
        self.assertEqual(data["Label"], schedule.LABEL)
        self.assertEqual(schedule.plan(prof, "launchd", which=fake_which(TOOLS))["path"],
                         f"/opt/fake/bin:/opt/node/bin:{SYS}")

    def test_cron_line_has_path_and_keeps_prefix(self):
        prof = Path("/tmp/profile-x")
        line = schedule.plan(prof, "cron", which=fake_which(TOOLS))["line"]
        self.assertTrue(line.startswith("0 9 * * 1 PATH="), line)
        self.assertEqual(shlex.split(line)[5], f"PATH=/opt/fake/bin:/opt/node/bin:{SYS}")
        self.assertIn("legal_watch.py", line)
        spaced = {"firecrawl": "/opt/my tools/firecrawl"}
        self.assertEqual(shlex.split(schedule.plan(prof, "cron", which=fake_which(spaced))["line"])[5],
                         f"PATH=/opt/my tools:{SYS}")

    def test_install_writes_the_path(self):
        run = lambda cmd, **kw: mock.Mock(returncode=0, stderr="")  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(schedule.sys, "platform", "darwin"):
            out = schedule.install(Path(tmp) / "profile", run=run, home=Path(tmp), which=fake_which(TOOLS))
            data = plistlib.loads(Path(out["installed"]).read_bytes())
        self.assertEqual(data["EnvironmentVariables"]["PATH"], f"/opt/fake/bin:/opt/node/bin:{SYS}")


if __name__ == "__main__":
    unittest.main()
