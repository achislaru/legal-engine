"""Firecrawl after the first review: one test per finding (no real CLI, no network).

The allowlist of sites, fatal CLI errors remembered per run, a refused URL as an error result, the snapshot of a
markdown page, `legal_watch.py fetch` for conversations and `legal_watch.py engines set`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_watch as cli  # noqa: E402
from test_firecrawl import FAKE_BIN, GAZETTE, HTML, LEGIS, MARKER, MD, EURLEX, FakeRun, fetcher, payload, proc  # noqa: E402
from watch import fetchers as F, issues, library as lib, runner  # noqa: E402
from watch.adapters.common import md_to_text  # noqa: E402
from watch.contract import text_sha256  # noqa: E402

JUST = "https://legislatie.just.ro/Public/DetaliiDocument/1"
SKIP = "firecrawl: not used for this site (only legis.md, monitorul.gov.md)"
NOT_LOGGED = "firecrawl: not logged in (run firecrawl login --browser yourself)"


class Engine:
    """A scripted engine that answers every page the same way and counts its calls."""

    def __init__(self, res: F.FetchResult):
        self.res, self.calls = res, []

    def get(self, url):
        self.calls.append(url)
        return self.res


class Allowlist(unittest.TestCase):
    """Firecrawl only on sites whose reader can use it; elsewhere no CLI call, no credit, no failed attempt."""

    def test_other_site_is_skipped_without_cli_call_or_pause(self):
        sleeps = []
        run = FakeRun(proc(payload("rawHtml", HTML, statusCode=200)))
        f = F.FirecrawlFetcher(run=run, which=lambda n: FAKE_BIN, pause_range=(1, 2), sleep=sleeps.append)
        for url in (EURLEX, JUST, "https://web.archive.org/web/2026/x", "file:///etc/passwd"):
            res = f.get(url)
            self.assertEqual((res.error, res.status, res.via), (SKIP, None, "firecrawl"), url)
        self.assertEqual((run.calls, sleeps), ([], []))
        self.assertFalse(f.accepts(EURLEX))
        self.assertTrue(f.accepts(LEGIS) and f.accepts(GAZETTE))
        self.assertIsNone(F.firecrawl_format("https://[legis.md/x"))   # malformed: not on the list, no crash
        self.assertEqual(f.get("https://[legis.md/x").error, SKIP)

    def test_chain_skips_firecrawl_on_eurlex_so_cellar_stays_free(self):
        """EUR-Lex's empty 202 from urllib ends the chain; Firecrawl is never asked (Cellar reads EU acts)."""
        empty = F.page_result(EURLEX, "", status=202, via="urllib")
        url_e = Engine(empty)
        fc, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200)))
        chain = F.ChainFetcher([url_e, fc], names=["urllib", "firecrawl"])
        self.assertIs(chain.get(EURLEX), empty)
        self.assertEqual(run.calls, [])

    def test_chain_keeps_the_previous_failure_and_records_no_firecrawl_attempt(self):
        """just.ro refused urllib: Firecrawl is not tried (its reader is uncalibrated), no credit, no demotion."""
        refused = F.FetchResult(url=JUST, status=None, via="urllib", error="ConnectionResetError: reset")
        fc, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200)))
        chain = F.ChainFetcher([Engine(refused), fc], names=["urllib", "firecrawl"])
        res = chain.get(JUST)
        self.assertIs(res, refused)
        self.assertEqual(run.calls, [])
        self.assertEqual([a["via"] for a in chain.attempts], ["urllib"])
        log = issues.empty()
        issues.update_engines(log, chain.attempts, "2026-11-05")
        self.assertNotIn("firecrawl", log["engines"].get("legislatie.just.ro", {}))

    def test_firecrawl_first_and_skipped_still_reaches_the_next_engine(self):
        ok = F.page_result(EURLEX, HTML, status=200, via="urllib")
        fc, run = fetcher(proc())
        chain = F.ChainFetcher([fc, Engine(ok)], names=["firecrawl", "urllib"])
        self.assertIs(chain.get(EURLEX), ok)
        self.assertEqual(([a["via"] for a in chain.attempts], run.calls), (["urllib"], []))
        self.assertFalse(any("firecrawl" in n for n in ok.notes))

    def test_firecrawl_alone_on_other_site_gives_the_skip_error(self):
        fc, run = fetcher(proc())
        chain = F.ChainFetcher([fc], names=["firecrawl"])
        res = chain.get(EURLEX)
        self.assertEqual((res.error, chain.attempts, run.calls), (SKIP, [], []))

    def test_allowlisted_site_still_runs(self):
        blocked = F.page_result(LEGIS, "<title>Just a moment...</title>", status=403, via="urllib")
        fc, run = fetcher(proc(payload("markdown", MD, statusCode=200)))
        chain = F.ChainFetcher([Engine(blocked), fc], names=["urllib", "firecrawl"])
        self.assertEqual(chain.get(LEGIS).markdown, MD)
        self.assertEqual(len(run.calls), 1)


class FatalErrorsRemembered(unittest.TestCase):
    """Not logged in, out of credits or no CLI: later pages get the same error at once, no call, no pause."""

    def test_fatal_errors_stop_later_calls(self):
        for stderr, msg in ((f"Not authenticated {MARKER}", NOT_LOGGED),
                            ("Insufficient credits", "firecrawl: out of credits (plan limit reached)")):
            with self.subTest(msg=msg):
                sleeps = []
                run = FakeRun(proc(stderr=stderr, rc=1))
                f = F.FirecrawlFetcher(run=run, which=lambda n: FAKE_BIN, pause_range=(1, 2), sleep=sleeps.append)
                self.assertEqual(f.get(LEGIS).error, msg)
                self.assertEqual(f.get(GAZETTE).error, msg)
                self.assertEqual(f.get(LEGIS).error, msg)
                self.assertEqual((len(run.calls), sleeps), (1, []))

    def test_missing_cli_is_remembered(self):
        seen = []

        def which(name):
            seen.append(name)
            return None
        f, run = fetcher(proc(), which=which)
        first = f.get(LEGIS).error
        self.assertTrue(first.startswith("firecrawl: CLI not found on PATH"))
        self.assertEqual(f.get(GAZETTE).error, first)
        self.assertEqual((len(seen), run.calls), (1, []))

    def test_other_errors_are_retried(self):
        run = FakeRun(proc(stderr="Rate limit exceeded", rc=1))
        f = F.FirecrawlFetcher(run=run, which=lambda n: FAKE_BIN, pause_range=(0, 0))
        f.get(LEGIS)
        f.get(LEGIS)
        self.assertEqual(len(run.calls), 2)


class ArgvErrorCaught(unittest.TestCase):
    """A URL the argv builder refuses is a failed fetch, never an exception that stops the run."""

    def test_refused_url_is_an_error_result(self):
        f, run = fetcher(proc(), formats={"": "rawHtml"})       # a table that lets an empty host through
        res = f.get("https://")
        self.assertEqual((res.error, res.status), ("firecrawl: only http(s) page URLs can be read", None))
        self.assertEqual(run.calls, [])
        f, run = fetcher(proc())
        with mock.patch.object(F, "firecrawl_argv", side_effect=F.FetchConfigError("firecrawl: bad url")):
            self.assertEqual(f.get(LEGIS).error, "firecrawl: bad url")
        self.assertEqual(run.calls, [])


class SnapshotIsTheHashedText(unittest.TestCase):
    """The snapshot of a markdown page is the text the reader hashed, so its name matches evidence.sha256."""

    def test_markdown_page_snapshot_is_md_to_text(self):
        md = "# Lege\n\n**Articolul 1.** [Text](https://www.legis.md/x) of the act.\n"
        rec = runner.RecordingFetcher(None)
        rec.pages[LEGIS] = F.page_result(LEGIS, "", via="firecrawl", markdown=md)
        text = runner.official_text(LEGIS, rec, None)
        self.assertEqual(text, md_to_text(md))
        self.assertEqual(text_sha256(text), text_sha256(md_to_text(md)))
        rec.pages[GAZETTE] = F.page_result(GAZETTE, HTML, via="urllib")
        self.assertIn("Articolul 1", runner.official_text(GAZETTE, rec, None))


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class FetchCommand(CliBase):
    """The safe entry point for conversations: the CLI's output never reaches the caller, only the page."""

    def fetch(self, out, url=LEGIS, name="page.md", **kw):
        fake, run = fetcher(out, **kw)
        target = self.dir / "sources" / name
        with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
            code, stdout, stderr = self.call("fetch", "--url", url, "--out", str(target))
        return code, stdout, stderr, target, run

    def test_markdown_page_is_saved_and_summarised(self):
        code, out, err, target, run = self.fetch(proc(payload("markdown", MD, statusCode=200), stderr=MARKER))
        self.assertEqual(code, 0, err)
        self.assertEqual(target.read_text(encoding="utf-8"), MD)
        self.assertEqual(json.loads(out), {"url": LEGIS, "via": "firecrawl", "status": 200, "format": "markdown",
                                           "saved": str(target),
                                           "sha256": hashlib.sha256(MD.encode("utf-8")).hexdigest()})
        self.assertNotIn(MARKER, out + err)
        self.assertEqual(run.calls[0]["argv"], F.firecrawl_argv(FAKE_BIN, LEGIS, "markdown"))

    def test_html_page_for_the_gazette(self):
        code, out, err, target, _ = self.fetch(proc(payload("rawHtml", HTML, statusCode=200)), url=GAZETTE,
                                               name="gazette.html")
        self.assertEqual(code, 0, err)
        self.assertEqual((target.read_text(encoding="utf-8"), json.loads(out)["format"]), (HTML, "rawHtml"))

    def test_failures_save_nothing_and_print_a_fixed_error(self):
        challenge = "# Just a moment...\n\nEfectuarea verificării de securitate\n"
        cases = [
            (proc(stderr=f"Not authenticated {MARKER}", rc=1), NOT_LOGGED),
            (proc(f"<html>{MARKER}</html>"), "firecrawl: unreadable output"),
            (proc(payload("markdown", MD)), "firecrawl: page status not reported"),
            (proc(payload("markdown", challenge, statusCode=200)), "challenge marker: 'just a moment'"),
            (proc(payload("markdown", MD, statusCode=404)), "HTTP 404 (reported by Firecrawl)"),
            (proc(payload("markdown", MD, statusCode=403)), "HTTP 403"),
            (__import__("subprocess").TimeoutExpired(["firecrawl"], 120), "firecrawl: timed out after 120 s"),
        ]
        for out, msg in cases:
            with self.subTest(msg=msg):
                code, stdout, stderr, target, _ = self.fetch(out)
                self.assertEqual(code, 2)
                self.assertFalse(target.exists())
                self.assertEqual(json.loads(stdout), {"url": LEGIS, "via": "firecrawl", "status": json.loads(stdout)
                                                      ["status"], "error": msg, "saved": None})
                self.assertNotIn(MARKER, stdout + stderr)

    def test_site_not_on_the_list_is_refused_without_a_call(self):
        code, out, _, target, run = self.fetch(proc(payload("rawHtml", HTML, statusCode=200)), url=EURLEX,
                                               name="eu.html")
        self.assertEqual((code, json.loads(out)["error"], run.calls), (2, SKIP, []))
        self.assertFalse(target.exists())

    def test_out_suffix_must_match_the_format(self):
        for url, name in ((LEGIS, "page.html"), (GAZETTE, "page.md"), (LEGIS, "page.txt")):
            with self.subTest(name=name):
                code, out, err, target, run = self.fetch(proc(payload("markdown", MD, statusCode=200)), url=url,
                                                         name=name)
                self.assertEqual((code, run.calls), (2, []))
                self.assertIn("--out must end in", err)
                self.assertFalse(target.exists())

    def test_out_inside_the_engine_is_refused(self):
        fake, run = fetcher(proc(payload("markdown", MD, statusCode=200)))
        with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
            code, _, err = self.call("fetch", "--url", LEGIS, "--out", str(lib.SKILL / "x.md"))
        self.assertEqual(code, 2)
        self.assertFalse((lib.SKILL / "x.md").exists())
        self.assertEqual(run.calls, [])

    def test_real_fetcher_is_built_with_no_pause(self):
        with mock.patch.object(cli, "FirecrawlFetcher") as cls:
            cls.return_value.get.return_value = F.FetchResult(url=LEGIS, status=None, via="firecrawl", error="x")
            self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
        self.assertEqual(cls.call_args.kwargs, {"pause_range": (0, 0)})

    def test_usage_names_fetch_and_engines_set(self):
        self.assertIn("legal_watch.py fetch --url <url> --out <file> [--engine firecrawl]", cli.__doc__)
        self.assertIn("legal_watch.py engines set <engine,…>", cli.__doc__)


class EnginesSet(CliBase):
    """Connect or disconnect Firecrawl later: only settings.engines changes; acts, state and texts stay."""

    def setUp(self):
        super().setUp()
        self.profile = self.dir / "profile"
        _, niches = lib.load_catalog()
        code, _, err = self.call("--profile", str(self.profile), "init", "--niches", next(iter(niches["niches"])),
                                 "--acts", "none", "--add", "eu.reg.2016-679", "--engines", "urllib,host",
                                 "--language", "ro")
        self.assertEqual(code, 0, err)
        self.path = self.profile / "laws" / "watchlist.yaml"
        self.state = self.profile / "laws" / "state.json"
        self.state.write_text('{"keep": true}', encoding="utf-8")

    def test_connect_then_disconnect(self):
        before = lib.load_watchlist(self.path)
        code, out, err = self.call("--profile", str(self.profile), "engines", "set", "urllib,firecrawl,host")
        self.assertEqual(code, 0, err)
        after = lib.load_watchlist(self.path)
        self.assertEqual(after["settings"]["engines"], ["urllib", "firecrawl", "host"])
        self.assertEqual({**after["settings"], "engines": None}, {**before["settings"], "engines": None})
        self.assertEqual((after["acts"], after["niches"], after["categories"]),
                         (before["acts"], before["niches"], before["categories"]))
        self.assertEqual(self.state.read_text(encoding="utf-8"), '{"keep": true}')
        self.assertEqual(json.loads(out)["engines"], ["urllib", "firecrawl", "host"])
        self.assertIn("schedule install", json.loads(out)["next"])
        code, _, err = self.call("--profile", str(self.profile), "engines", "set", "urllib,host")
        self.assertEqual(code, 0, err)
        self.assertEqual(lib.load_watchlist(self.path)["settings"]["engines"], ["urllib", "host"])

    def test_bad_lists_change_nothing(self):
        raw = self.path.read_text(encoding="utf-8")
        for bad in ("", "urllib,curl", "urllib,urllib", "command", " , "):
            with self.subTest(bad=bad):
                code, _, err = self.call("--profile", str(self.profile), "engines", "set", bad)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("legal_watch: "), err)
                self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_needs_a_watchlist(self):
        code, _, err = self.call("--profile", str(self.dir / "empty"), "engines", "set", "urllib")
        self.assertEqual(code, 2)
        self.assertIn("watchlist not found", err)


if __name__ == "__main__":
    unittest.main()
