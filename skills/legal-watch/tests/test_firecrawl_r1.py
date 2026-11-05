"""Review round 1 of the Firecrawl feature: one test per finding (no real CLI, no network).

D1 allowlist (K1, K2, X4) · D3 fatal errors remembered (K7) · D4 argv error caught (K8) · D5 snapshot = hashed text
(K3) · D7 `legal_watch.py fetch` (X2) · D9 `legal_watch.py engines set` (X7).
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
    """D1: Firecrawl only on sites whose reader can use it; elsewhere no CLI call, no credit, no failed attempt."""

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

    def test_chain_skips_firecrawl_on_eurlex_so_cellar_stays_free(self):
        """K1/X4: EUR-Lex's empty 202 from urllib ends the chain; Firecrawl is never asked (Cellar reads EU acts)."""
        empty = F.page_result(EURLEX, "", status=202, via="urllib")
        url_e = Engine(empty)
        fc, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200)))
        chain = F.ChainFetcher([url_e, fc], names=["urllib", "firecrawl"])
        self.assertIs(chain.get(EURLEX), empty)
        self.assertEqual(run.calls, [])

    def test_chain_keeps_the_previous_failure_and_records_no_firecrawl_attempt(self):
        """K2: just.ro refused urllib: Firecrawl is not tried (its reader is uncalibrated), no credit, no demotion."""
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
    """D3/K7: not logged in, out of credits or no CLI: later pages get the same error at once, no call, no pause."""

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
    """D4/K8: a URL the argv builder refuses is a failed fetch, never an exception that stops the run."""

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
    """D5/K3: the snapshot of a markdown page is the text the reader hashed, so its name matches evidence.sha256."""

    def test_markdown_page_snapshot_is_md_to_text(self):
        md = "# Lege\n\n**Articolul 1.** [Text](https://www.legis.md/x) of the act.\n"
        rec = runner.RecordingFetcher(None)
        rec.pages[LEGIS] = F.page_result(LEGIS, "", via="firecrawl", markdown=md)
        text = runner.official_text(LEGIS, rec, None)
        self.assertEqual(text, md_to_text(md))
        self.assertEqual(text_sha256(text), text_sha256(md_to_text(md)))
        rec.pages[GAZETTE] = F.page_result(GAZETTE, HTML, via="urllib")
        self.assertIn("Articolul 1", runner.official_text(GAZETTE, rec, None))


if __name__ == "__main__":
    unittest.main()
