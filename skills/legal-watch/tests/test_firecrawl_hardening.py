"""Firecrawl hardening (no real CLI, no network).

- the page title Firecrawl reports is CLI data: it never reaches an error, run.json, issues.json, the digest or
  the report (other engines keep showing the title, it helps the user see which page answered);
- duplicate `reading` rows in the setup table are no consent, and the writer leaves one row for a step it writes,
  so a withdrawal always takes effect;
- the credit estimate counts only calls that started: a CLI that could not even start billed nothing.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
WORKFLOW = SKILL.parent / "legal-workflow" / "scripts"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(WORKFLOW))
import legal_profile as lp  # noqa: E402
import legal_watch as cli  # noqa: E402
from test_adapters_legis_md import T_MD, live_act, read  # noqa: E402
from test_firecrawl import LEGIS, MD, fetcher, payload, proc  # noqa: E402
from watch import consent, fetchers as F, library as lib, runner  # noqa: E402
from watch.adapters import eurlex, just_ro, legis_md  # noqa: E402

TITLE_MARKER = "SYNTHETIC-PRIVATE-MARKER"
DOC = "150997"
PAGE = legis_md.PAGE_URL.format(doc_id=DOC)
DOC_MD = read(f"legis_md/markdown-{DOC}-2026-10-02.md")
BLOCKED_MD = "# Just a moment...\n\nChecking the connection."
# long enough to be read, but names no act: the identity check fails
STRANGER_MD = "Pagina altui document. " * 200
TABLE = "# Integration status\n\n| Step | Status | Updated | Note |\n|---|---|---|---|\n"
ON = "| reading | done | 2026-11-04 | conversation: on; monitoring: on |"
OFF = "| reading | skipped | 2026-11-04 | not connected |"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profile = self.dir / "profile"
        (self.profile / "context").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, *rows: str) -> None:
        (self.profile / "context" / "integration-status.md").write_text(TABLE + "\n".join(rows) + "\n",
                                                                         encoding="utf-8")

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--profile", str(self.profile), *argv])
        return code, out.getvalue(), err.getvalue()


class FirecrawlTitleStaysOut(Tmp):
    def written(self, day: dt.date) -> str:
        laws = lib.laws_dir(self.profile)
        files = [f for f in (laws / "runs" / day.isoformat()).iterdir() if f.is_file()]
        files += [laws / "issues.json", laws / "report.html"]
        return "\n".join(f.read_text(encoding="utf-8") for f in files if f.is_file())

    def test_blocked_and_stranger_pages_leave_no_title_anywhere(self):
        act = live_act(DOC)
        good, _ = fetcher(proc(payload("markdown", DOC_MD, statusCode=200, title=TITLE_MARKER)))
        first = runner.run(self.profile, [act], good, T_MD, scan_gazette=False, engines=["firecrawl"])
        self.assertTrue(first["acts"][0]["checked"])
        before = lib.load_state(self.profile)["acts"][act["id"]]
        for n, (md, status, reason) in enumerate(((BLOCKED_MD, 403, "blocked"), (STRANGER_MD, 200, "parse")), 1):
            with self.subTest(reason=reason):
                day = T_MD + dt.timedelta(days=n)
                bad, _ = fetcher(proc(payload("markdown", md, statusCode=status, title=TITLE_MARKER)))
                out = runner.run(self.profile, [act], bad, day, scan_gazette=False, engines=["firecrawl"])
                self.assertFalse(out["acts"][0]["checked"])
                self.assertTrue(out["acts"][0]["error"])
                self.assertNotIn(TITLE_MARKER, json.dumps(out, ensure_ascii=False))
                self.assertNotIn(TITLE_MARKER, self.written(day))
                self.assertEqual(lib.load_state(self.profile)["acts"][act["id"]], before)

    def test_adapter_errors_hide_a_firecrawl_title_and_keep_others(self):
        md_act = live_act(DOC)
        cases = []
        for via, shown in (("firecrawl", False), ("urllib", True)):
            blocked = F.page_result(PAGE, "", status=403, via=via, markdown=BLOCKED_MD, title=TITLE_MARKER)
            stranger = F.page_result(PAGE, "", status=200, via=via, markdown=STRANGER_MD, title=TITLE_MARKER)
            cases += [(via, shown, blocked), (via, shown, stranger)]
        for via, shown, page in cases:
            with self.subTest(via=via, blocked=page.blocked):
                res = legis_md.check_act(md_act, _One(page), T_MD)
                self.assertEqual(TITLE_MARKER in (res.error or ""), shown, res.error)

    def test_other_adapters_hide_it_too(self):
        page = F.page_result("https://example.com/x", f"<html><title>{TITLE_MARKER}</title>Just a moment</html>",
                             status=403, via="firecrawl")
        self.assertEqual(F.shown_title(page), F.HIDDEN_TITLE)
        plain = F.page_result("https://example.com/x", f"<html><title>{TITLE_MARKER}</title></html>", via="urllib")
        self.assertEqual(F.shown_title(plain), repr(TITLE_MARKER))
        act = {"id": "eu.reg.2016-679", "sources": [{"kind": "eurlex", "celex": "32016R0679"}]}
        res = eurlex.check_page(act, _One(page), T_MD)
        self.assertTrue(res.error)
        self.assertNotIn(TITLE_MARKER, res.error)
        self.assertIn(F.HIDDEN_TITLE, res.error)
        self.assertIn(TITLE_MARKER, eurlex.check_page(act, _One(plain_blocked()), T_MD).error)
        for mod in (eurlex, just_ro):
            with self.subTest(adapter=mod.__name__):
                self.assertNotIn("{r.title!r}", Path(mod.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("{page.heading!r}", Path(just_ro.__file__).read_text(encoding="utf-8"))


def plain_blocked() -> F.FetchResult:
    return F.page_result("https://example.com/x", f"<html><title>{TITLE_MARKER}</title>Just a moment</html>",
                         status=403, via="urllib")


class _One:
    def __init__(self, res):
        self.res = res

    def get(self, url):
        return self.res


class DuplicateReadingRows(Tmp):
    def test_reader_fails_closed_on_duplicates(self):
        none = {"conversation": False, "monitoring": False}
        for rows in ((ON, ON), (ON, OFF), (OFF, ON)):
            with self.subTest(rows=rows):
                self.status(*rows)
                self.assertEqual(consent.reading(self.profile), none)
        self.status(ON)
        self.assertEqual(consent.reading(self.profile), {"conversation": True, "monitoring": True})

    def test_writer_leaves_one_row_and_withdrawal_takes_effect(self):
        catalog = lp.load_catalog()
        for rows in ((ON, ON), (ON, OFF), (OFF, ON)):
            with self.subTest(rows=rows):
                self.status("| firms | done | 2026-11-04 | |", *rows, "| language | done | 2026-11-04 | |")
                lp.step_set(self.profile, "reading", "skipped", catalog, note="not connected", date="2026-11-05")
                text = (self.profile / "context" / "integration-status.md").read_text(encoding="utf-8")
                self.assertEqual(text.count("| reading |"), 1)
                self.assertIn("| reading | skipped | 2026-11-05 | not connected |", text)
                self.assertIn("| firms |", text)
                self.assertIn("| language |", text)
                self.assertEqual(consent.reading(self.profile), {"conversation": False, "monitoring": False})
                # fetch is refused before anything is sent
                with mock.patch.object(cli, "FirecrawlFetcher") as cls:
                    code, out, err = self.call("fetch", "--url", LEGIS, "--out", str(self.dir / "a.md"))
                self.assertEqual(code, 2)
                self.assertIn("not allowed for conversations", err)
                cls.assert_not_called()

    def test_run_skips_firecrawl_after_withdrawal(self):
        catalog = lp.load_catalog()
        self.status(ON)
        _, niches = lib.load_catalog()
        code, _, err = self.call("init", "--niches", next(iter(niches["niches"])), "--acts", "none", "--add",
                                 "eu.reg.2016-679", "--engines", "urllib,firecrawl,host", "--force")
        self.assertEqual(code, 0, err)
        self.status(ON, ON)
        lp.step_set(self.profile, "reading", "skipped", catalog, note="not connected", date="2026-11-05")
        captured = {}

        def fake_run(*a, **kw):
            captured.update(kw)
            return {"summary": {"checked": 0, "acts": 0, "unverified_p1": 0, "changes": 0}, "result": "OK",
                    "date": "2026-11-05", "exit_code": 0}
        with mock.patch.object(cli.runner, "run", fake_run), \
                mock.patch.object(cli, "build_chain", return_value=_One(None)) as chain:
            self.call("run", "--today", "2026-11-05", "--dry-run")
        self.assertEqual(chain.call_args.args[0], ["urllib"])
        self.assertEqual(captured["notes"], [runner.NOTE_FIRECRAWL_NOT_ALLOWED])


if __name__ == "__main__":
    unittest.main()
