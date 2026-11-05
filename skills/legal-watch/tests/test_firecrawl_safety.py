"""Firecrawl safety after the second review (no real CLI, no network).

- the CLI's metadata (final URL, title) is checked inside the fixed-error boundary: a malformed URL never leaks;
- only a 2xx answer is a page: 1xx, unfollowed redirects and 304 are "not verified", the baseline stays;
- the consent of the setup step `reading` is checked by the scripts (`fetch`, adding the engine, a run);
- `engines add|remove` change one engine and keep the rest;
- the digest gives the run's Firecrawl calls as an estimate, never as the bill.
"""

from __future__ import annotations

import contextlib
import datetime as dt
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
from test_adapters_legis_md import T_MD, live_act, read  # noqa: E402
from test_firecrawl import GAZETTE, HTML, LEGIS, MARKER, MD, allow, fetcher, payload, proc  # noqa: E402
from watch import consent, digest, fetchers as F, library as lib, runner  # noqa: E402
from watch.adapters import legis_md  # noqa: E402

UNREADABLE = "firecrawl: unreadable output"
# Metadata URLs that make urlparse raise with the value in its message (NFKC netloc, bracket, bad port).
BAD_URLS = (f"https://{MARKER}／example.com/x", f"https://[{MARKER}/x", f"https://legis.md:{MARKER}/x")
DOC = "150997"
PAGE = legis_md.PAGE_URL.format(doc_id=DOC)
DOC_MD = read(f"legis_md/markdown-{DOC}-2026-10-02.md")


class Engine:
    def __init__(self, res: F.FetchResult):
        self.res, self.calls = res, []

    def get(self, url):
        self.calls.append(url)
        return self.res


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profile = self.dir / "profile"

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--profile", str(self.profile), *argv])
        return code, out.getvalue(), err.getvalue()


class MalformedMetadata(Tmp):
    """A URL in Firecrawl's metadata that does not parse is unreadable output; its text goes nowhere."""

    def test_fetcher_returns_the_fixed_error(self):
        for bad in BAD_URLS:
            with self.subTest(url=bad):
                f, run = fetcher(proc(payload("markdown", MD, statusCode=200, url=bad)))
                res = f.get(LEGIS)
                self.assertEqual((res.error, res.markdown, res.status), (UNREADABLE, "", None))
                self.assertEqual(len(run.calls), 1)

    def test_odd_but_parseable_metadata_falls_back_to_the_request(self):
        for meta in ({"url": 7, "title": 5}, {"url": "ftp://x/y"}, {"url": "https:///nohost"}):
            with self.subTest(meta=meta):
                f, _ = fetcher(proc(payload("markdown", MD, statusCode=200, **meta)))
                res = f.get(LEGIS)
                self.assertIsNone(res.error)
                self.assertEqual(res.final_url, LEGIS)
        f, _ = fetcher(proc(payload("markdown", MD, statusCode=200, url="https://www.legis.md/y", title="T")))
        res = f.get(LEGIS)
        self.assertEqual((res.final_url, res.title), ("https://www.legis.md/y", "T"))

    def test_chain_goes_on_to_the_next_engine(self):
        good = F.page_result(LEGIS, "", via="command", markdown=MD)
        fc, _ = fetcher(proc(payload("markdown", MD, statusCode=200, url=BAD_URLS[0])))
        chain = F.ChainFetcher([fc, Engine(good)], names=["firecrawl", "command"])
        self.assertIs(chain.get(LEGIS), good)
        self.assertEqual(chain.attempts[0]["error"], UNREADABLE)
        self.assertNotIn(MARKER, json.dumps(chain.attempts))

    def test_fetch_command_prints_only_the_fixed_error(self):
        allow(self.profile)
        target = self.dir / "page.md"
        for bad in BAD_URLS:
            with self.subTest(url=bad):
                fake, _ = fetcher(proc(payload("markdown", MD, statusCode=200, url=bad)))
                with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
                    code, out, err = self.call("fetch", "--url", LEGIS, "--out", str(target))
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"], UNREADABLE)
                self.assertNotIn(MARKER, out + err)
                self.assertFalse(target.exists())

    def test_fetch_command_never_shows_an_exception_text(self):
        allow(self.profile)
        with mock.patch.object(cli, "FirecrawlFetcher") as cls:
            cls.return_value.get.side_effect = ValueError(f"netloc {MARKER} contains invalid characters")
            code, out, err = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
        self.assertEqual((code, json.loads(out)["error"]), (2, UNREADABLE))
        self.assertNotIn(MARKER, out + err)
        self.assertFalse((self.dir / "a.md").exists())

    def test_monitoring_keeps_the_baseline_and_writes_no_marker(self):
        act = live_act(DOC)
        good, _ = fetcher(proc(payload("markdown", DOC_MD, statusCode=200)))
        runner.run(self.profile, [act], good, T_MD, scan_gazette=False, engines=["firecrawl"])
        before = lib.load_state(self.profile)["acts"][act["id"]]
        texts = sorted((lib.laws_dir(self.profile) / "texts").rglob("*"))
        day = T_MD + dt.timedelta(days=7)
        bad, _ = fetcher(proc(payload("markdown", DOC_MD, statusCode=200, url=BAD_URLS[0])))
        out = runner.run(self.profile, [act], bad, day, scan_gazette=False, engines=["firecrawl"])
        self.assertFalse(out["acts"][0]["checked"])
        self.assertEqual(lib.load_state(self.profile)["acts"][act["id"]], before)
        self.assertEqual(sorted((lib.laws_dir(self.profile) / "texts").rglob("*")), texts)
        run_dir = lib.laws_dir(self.profile) / "runs" / day.isoformat()
        for f in list(run_dir.iterdir()) + [lib.laws_dir(self.profile) / "issues.json"]:
            if f.is_file():
                self.assertNotIn(MARKER, f.read_text(encoding="utf-8"), f.name)

    def test_a_crashed_reader_keeps_only_the_exception_type(self):
        def boom(act, fetcher, today):
            raise ValueError(f"netloc {MARKER} contains invalid characters")
        with mock.patch.object(runner, "adapter_for", lambda a: ("legis_md", boom)):
            r = runner.check_one(live_act(DOC), None, T_MD)
        self.assertEqual((r["error"], r["reasons"]), ("adapter crashed: ValueError", ["adapter_crashed"]))

    def test_a_crashed_gazette_scan_keeps_only_the_exception_type(self):
        act = {**live_act(DOC), "jurisdiction": "MD"}
        with mock.patch.object(runner.monitorul_md, "scan", side_effect=ValueError(MARKER)), \
                mock.patch.object(runner, "adapter_for", lambda a: ("none", None)):
            out = runner.run(self.profile, [act], Engine(F.FetchResult(url="x", status=None, error="e")), T_MD,
                             dry_run=True)
        self.assertEqual(out["monitorul"]["error"], "scan crashed: ValueError")


class OnlyTwoHundredsArePages(Tmp):
    def test_status_classes(self):
        for status, err in ((100, "firecrawl: HTTP 100 (reported by Firecrawl, not a page)"),
                            (302, "firecrawl: HTTP 302 (reported by Firecrawl, not a page)"),
                            (304, "firecrawl: HTTP 304 (reported by Firecrawl, not a page)"),
                            (200, None), (203, None), (299, None),
                            (404, "HTTP 404 (reported by Firecrawl)"), (500, "HTTP 500 (reported by Firecrawl)")):
            with self.subTest(status=status):
                f, _ = fetcher(proc(payload("rawHtml", HTML, statusCode=status)))
                res = f.get(GAZETTE)
                self.assertEqual((res.status, res.error), (status, err))

    def test_redirect_falls_back_and_keeps_the_baseline(self):
        act = live_act(DOC)
        ok, _ = fetcher(proc(payload("markdown", DOC_MD, statusCode=200)))
        first = runner.run(self.profile, [act], ok, T_MD, scan_gazette=False, engines=["firecrawl"])
        self.assertTrue(first["acts"][0]["checked"])
        before = lib.load_state(self.profile)["acts"][act["id"]]
        for n, status in enumerate((100, 302, 304), 1):
            with self.subTest(status=status):
                fc, _ = fetcher(proc(payload("markdown", DOC_MD, statusCode=status)))
                nxt = Engine(F.FetchResult(url=PAGE, status=None, via="host", error="engine 'host' only"))
                chain = F.ChainFetcher([fc, nxt], names=["firecrawl", "command"])
                out = runner.run(self.profile, [act], chain, T_MD + dt.timedelta(days=n), scan_gazette=False,
                                 engines=["firecrawl"])
                self.assertEqual(nxt.calls, [PAGE])   # the fallback was asked
                self.assertFalse(out["acts"][0]["checked"])
                self.assertNotEqual(out["acts"][0]["status"], "unchanged")
                self.assertEqual(lib.load_state(self.profile)["acts"][act["id"]], before)

    def test_fetch_command_saves_nothing_for_a_redirect(self):
        allow(self.profile)
        fake, _ = fetcher(proc(payload("markdown", MD, statusCode=302)))
        with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
            code, out, _ = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
        self.assertEqual((code, json.loads(out)["error"]), (2, "firecrawl: HTTP 302 (reported by Firecrawl, not a page)"))
        self.assertFalse((self.dir / "a.md").exists())

    def test_fetch_command_checks_the_status_itself(self):
        allow(self.profile)
        with mock.patch.object(cli, "FirecrawlFetcher") as cls:
            cls.return_value.get.return_value = F.page_result(LEGIS, "", status=304, via="firecrawl", markdown=MD)
            code, out, _ = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
        self.assertEqual((code, json.loads(out)["error"]), (2, "HTTP 304"))


class ConsentReader(Tmp):
    def test_states_and_notes(self):
        cases = [
            (None, None, {"conversation": False, "monitoring": False}),   # a 1.1 profile: no file
            ("done", "conversation: on; monitoring: on", {"conversation": True, "monitoring": True}),
            ("done", "conversation: on; monitoring: off; waiting: cli login", {"conversation": True,
                                                                               "monitoring": False}),
            ("DONE", "Conversation: ON;monitoring:off", {"conversation": True, "monitoring": False}),
            ("pending", "conversation: on; monitoring: on; waiting: cli login", {"conversation": False,
                                                                                 "monitoring": False}),
            ("skipped", "later", {"conversation": False, "monitoring": False}),
            ("done", "conversation: off; monitoring: off", {"conversation": False, "monitoring": False}),
            ("done", "mcp: on; cli: off", {"conversation": False, "monitoring": False}),   # an older note
        ]
        for status, note, want in cases:
            with self.subTest(status=status, note=note):
                path = self.profile / "context" / "integration-status.md"
                if status is None:
                    path.unlink(missing_ok=True)
                else:
                    allow(self.profile, note, status)
                self.assertEqual(consent.reading(self.profile), want)

    def test_no_row_short_row_and_unreadable_file(self):
        path = self.profile / "context" / "integration-status.md"
        path.parent.mkdir(parents=True)
        path.write_text("| Step | Status | Updated | Note |\n|---|---|---|---|\n| firms | done | 2026-11-05 | |\n"
                        "| reading |\n", encoding="utf-8")
        self.assertFalse(consent.allowed(self.profile, "monitoring"))
        path.write_bytes(b"\xff\xfe| reading | done |")
        self.assertFalse(consent.allowed(self.profile, "conversation"))
        with self.assertRaises(ValueError):
            consent.allowed(self.profile, "billing")


class FetchNeedsConversationConsent(Tmp):
    def test_refused_without_conversation_on(self):
        for status, note in ((None, None), ("pending", "conversation: on; monitoring: on; waiting: x"),
                             ("skipped", "not connected"), ("done", "conversation: off; monitoring: on")):
            with self.subTest(status=status, note=note):
                path = self.profile / "context" / "integration-status.md"
                path.unlink(missing_ok=True)
                if status:
                    allow(self.profile, note, status)
                fake, run = fetcher(proc(payload("markdown", MD, statusCode=200)))
                with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
                    code, out, err = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
                self.assertEqual((code, out, run.calls), (2, "", []))
                self.assertEqual(err.strip(), f"legal_watch: {cli.NO_CONVERSATION}")
                self.assertFalse((self.dir / "a.md").exists())

    def test_allowed_with_conversation_on(self):
        allow(self.profile, "conversation: on; monitoring: off")
        fake, _ = fetcher(proc(payload("markdown", MD, statusCode=200)))
        with mock.patch.object(cli, "FirecrawlFetcher", lambda **k: fake):
            code, _, err = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
        self.assertEqual(code, 0, err)


class WatchlistBase(Tmp):
    def init(self, engines="urllib,host"):
        _, niches = lib.load_catalog()
        return self.call("init", "--niches", next(iter(niches["niches"])), "--acts", "none", "--add",
                         "eu.reg.2016-679", "--engines", engines, "--force")

    @property
    def path(self):
        return self.profile / "laws" / "watchlist.yaml"

    def engines(self):
        return lib.load_watchlist(self.path)["settings"]["engines"]


class EnginesNeedMonitoringConsent(WatchlistBase):
    def test_init_with_firecrawl(self):
        allow(self.profile, "conversation: on; monitoring: off")
        code, _, err = self.init("urllib,firecrawl,host")
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), f"legal_watch: {cli.NO_MONITORING}")
        self.assertFalse(self.path.exists())
        allow(self.profile, "conversation: off; monitoring: on")
        self.assertEqual(self.init("urllib,firecrawl,host")[0], 0)

    def test_add_and_set_refused_without_consent(self):
        self.assertEqual(self.init()[0], 0)
        raw = self.path.read_text(encoding="utf-8")
        for argv in (("engines", "add", "firecrawl"), ("engines", "set", "urllib,firecrawl,host")):
            with self.subTest(argv=argv):
                code, _, err = self.call(*argv)
                self.assertEqual(code, 2)
                self.assertIn("not allowed for monitoring", err)
                self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_remove_never_needs_consent(self):
        allow(self.profile)
        self.init("urllib,firecrawl,host")
        allow(self.profile, "conversation: on; monitoring: off")
        code, out, err = self.call("engines", "remove", "firecrawl")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.engines(), json.loads(out)["changed"]), (["urllib", "host"], True))


class EnginesAddRemove(WatchlistBase):
    def setUp(self):
        super().setUp()
        allow(self.profile)
        code, _, err = self.init("urllib,playwright,host")
        self.assertEqual(code, 0, err)

    def test_add_keeps_the_others_and_goes_before_host(self):
        code, out, err = self.call("engines", "add", "firecrawl")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.engines(), ["urllib", "playwright", "firecrawl", "host"])
        self.assertTrue(json.loads(out)["changed"])
        raw = self.path.read_text(encoding="utf-8")
        code, out, _ = self.call("engines", "add", "firecrawl")   # idempotent: nothing rewritten
        self.assertEqual((code, json.loads(out)), (0, {"engines": ["urllib", "playwright", "firecrawl", "host"],
                                                       "changed": False}))
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_add_without_host_appends(self):
        self.call("engines", "remove", "host")
        self.call("engines", "add", "firecrawl")
        self.assertEqual(self.engines(), ["urllib", "playwright", "firecrawl"])

    def test_remove_keeps_order_and_is_idempotent(self):
        self.call("engines", "add", "firecrawl")
        code, out, _ = self.call("engines", "remove", "firecrawl")
        self.assertEqual((code, self.engines()), (0, ["urllib", "playwright", "host"]))
        self.assertIn("schedule install", json.loads(out)["next"])
        code, out, _ = self.call("engines", "remove", "firecrawl")
        self.assertEqual((code, json.loads(out)["changed"]), (0, False))

    def test_bad_names_and_an_empty_list_change_nothing(self):
        raw = self.path.read_text(encoding="utf-8")
        for argv in (("engines", "add", "curl"), ("engines", "remove", "urllib,host")):
            with self.subTest(argv=argv):
                code, _, err = self.call(*argv)
                self.assertEqual(code, 2)
                self.assertIn("unknown engine", err)
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)
        for e in ("urllib", "playwright"):
            self.call("engines", "remove", e)
        code, _, err = self.call("engines", "remove", "host")
        self.assertEqual(code, 2)
        self.assertIn("settings.engines must be a non-empty list", err)
        self.assertEqual(self.engines(), ["host"])

    def test_usage_names_add_and_remove(self):
        self.assertIn("legal_watch.py engines add|remove <engine>", cli.__doc__)


class RunWithoutMonitoringConsent(WatchlistBase):
    def test_firecrawl_is_dropped_and_the_digest_says_so(self):
        allow(self.profile)
        self.init("urllib,firecrawl,host")
        allow(self.profile, "conversation: on; monitoring: off")
        captured = {}

        def fake_run(*a, **kw):
            captured.update(kw)
            return {"summary": {"checked": 0, "acts": 0, "unverified_p1": 0, "changes": 0}, "result": "OK",
                    "date": "2026-11-05", "exit_code": 0}
        with mock.patch.object(cli.runner, "run", fake_run), \
                mock.patch.object(cli, "build_chain", return_value=Engine(None)) as chain:
            code, out, _ = self.call("run", "--today", "2026-11-05", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(chain.call_args.args[0], ["urllib"])
        self.assertEqual((captured["engines"], captured["notes"]), (["urllib"], [runner.NOTE_FIRECRAWL_NOT_ALLOWED]))
        self.assertIn("firecrawl skipped: not allowed for monitoring", out)

    def test_with_consent_firecrawl_stays(self):
        allow(self.profile)
        self.init("urllib,firecrawl,host")
        with mock.patch.object(cli.runner, "run", return_value={
                "summary": {"checked": 0, "acts": 0, "unverified_p1": 0, "changes": 0}, "result": "OK",
                "date": "2026-11-05", "exit_code": 0}) as run, \
                mock.patch.object(cli, "build_chain", return_value=Engine(None)):
            self.call("run", "--today", "2026-11-05", "--dry-run")
        self.assertEqual((run.call_args.kwargs["engines"], run.call_args.kwargs["notes"]), (["urllib", "firecrawl"], []))

    def test_note_in_run_json_and_digest_and_no_tip(self):
        act = live_act(DOC)
        refused = Engine(F.FetchResult(url=PAGE, status=403, via="urllib", blocked=True, blocked_reason="HTTP 403"))
        out = runner.run(self.profile, [act], refused, T_MD, scan_gazette=False, engines=["urllib"],
                         notes=[runner.NOTE_FIRECRAWL_NOT_ALLOWED])
        self.assertEqual(out["notes"], ["firecrawl_not_allowed"])
        self.assertFalse(digest.needs_firecrawl_tip(out))
        for lang in ("en", "ro", "ru"):
            with self.subTest(lang=lang):
                text = digest.render(out, lang)
                self.assertIn(digest.T[lang]["notes"]["firecrawl_not_allowed"], text)
                self.assertIn("legal_watch.py engines remove firecrawl", text)
                self.assertNotIn(digest.T[lang]["firecrawl_tip"], text)
        self.assertTrue(digest.needs_firecrawl_tip({**out, "notes": []}))


class CreditEstimate(Tmp):
    def test_counting_rules(self):
        attempts = [{"via": "firecrawl", "error": None}, {"via": "firecrawl", "error": "firecrawl: timed out after 120 s"},
                    {"via": "firecrawl", "error": F.FC_NOT_LOGGED_IN}, {"via": "firecrawl", "error": F.FC_BAD_URL},
                    {"via": "firecrawl", "error": F.FC_NO_CREDITS}, {"via": "urllib", "error": None}]
        self.assertEqual(F.firecrawl_calls(attempts), 2)
        self.assertEqual(F.firecrawl_calls(None), 0)

    def test_digest_counts_gazette_pages_and_never_claims_the_bill(self):
        """One watched MD act, the Gazette refused plain requests: its pages through Firecrawl are counted too."""
        act = live_act(DOC)
        refused = Engine(F.FetchResult(url="x", status=403, via="urllib", blocked=True, blocked_reason="HTTP 403"))
        fc, run = fetcher(proc(payload("rawHtml", HTML, statusCode=200)))
        fc.formats = {**F.FIRECRAWL_FORMAT_BY_HOST}   # the Gazette and legis.md; the act page answers rawHtml here
        chain = F.ChainFetcher([refused, fc], names=["urllib", "firecrawl"])
        out = runner.run(self.profile, [act], chain, T_MD, dry_run=True, engines=["urllib", "firecrawl"])
        n = len(run.calls)
        self.assertGreaterEqual(n, 2)   # the Gazette home page and the act page at least
        self.assertEqual(F.firecrawl_calls(out["engine_attempts"]), n)
        en = digest.render(out, "en")
        self.assertIn(f"Firecrawl calls this run: {n} (estimated credits: about {n}; actual billing only in your "
                      "Firecrawl account)", en)
        self.assertIn(f"Apeluri Firecrawl în această rulare: {n}", digest.render(out, "ro"))
        self.assertIn(f"Обращений к Firecrawl за прогон: {n}", digest.render(out, "ru"))

    def test_no_line_without_firecrawl_or_without_attempts(self):
        base = {"date": "2026-11-05", "result": "OK", "summary": {"checked": 0, "acts": 0}, "acts": []}
        for run in ({**base, "engines": ["urllib"], "engine_attempts": []},
                    {**base, "engines": ["urllib", "firecrawl"]}):   # a hand record merged into the day
            with self.subTest(run=run.get("engines")):
                self.assertNotIn("Firecrawl calls", digest.render(run, "en"))


if __name__ == "__main__":
    unittest.main()
