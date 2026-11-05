"""A check by hand through Firecrawl and saved markdown texts (no network)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_watch as cli  # noqa: E402
from test_adapters_legis_md import T_MD, live_act, md_page  # noqa: E402
from test_review_fixes import TODAY, Base, live_card  # noqa: E402
from test_runner import URL, V2, act, adapter  # noqa: E402
from watch import issues, library as lib, manual, runner  # noqa: E402
from watch.adapters import legis_md  # noqa: E402
from watch.adapters.common import md_to_text  # noqa: E402
from watch.contract import UNCHANGED, AdapterResult, Evidence, classify, text_sha256  # noqa: E402
from watch.fetchers import FixtureFetcher  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "legis_md"
MARKDOWN = sorted(FIX.glob("markdown-*.md"))
SIG = {"act_id": "ro.lege.1-2020", "edition_id": 9, "edition_number": "450", "edition_date": "2026-11-01",
       "item": "Lege pentru modificarea Legii nr. 1/2020", "matched": "1/2020", "url": "https://mo.example/9"}


def listing_adapter(related):
    """A calibrated reader that also lists the amending acts it saw (like Cellar), so a hand check can review them."""
    def fn(a, fetcher, today):
        page = fetcher.get(URL)
        ev = Evidence(url=URL, fetched_at=page.fetched_at, sha256="a" * 64, parser="fake", parser_calibrated=True,
                      via=page.via)
        st, cur, nxt, err, notes = classify(act=a, parsed=[V2], today=today, repealed=False)
        return AdapterResult(act_id=a["id"], adapter="fake", status=st, current=cur, next=nxt, evidence=ev,
                             error=err, notes=notes, related=list(related))
    return lambda a: ("fake", fn)


class HandCheckViaFirecrawl(Base):
    def test_record_via_firecrawl_keeps_hand_check_semantics(self):
        held = act(current={"label": "v2", "in_force_from": "2026-10-01"})
        # The site refused the scripts once (an open problem in the error log) ...
        self.run_with([held], adapter([], fail="blocked_403"))
        self.assertEqual(issues.load(self.profile)["acts"]["ro.lege.1-2020"]["state"], "open")
        # ... and a Gazette signal waits for this act, so today's later reading (which listed amendments) is no check.
        state = lib.load_state(self.profile)
        state.setdefault("signals", {})["ro.lege.1-2020"] = [SIG]
        lib.save_state(self.profile, state)
        out = self.run_with([held], listing_adapter(["lp-1", "lp-2"]))
        self.assertEqual(out["acts"][0]["reasons"], ["gazette_signal"])
        self.assertEqual(issues.load(self.profile)["acts"]["ro.lege.1-2020"]["state"], "open")

        out = manual.record(self.profile, [held], live_card(self.matter, "ro.lege.1-2020"), TODAY,
                            root=self.matter, via="firecrawl")
        r = next(x for x in out["acts"] if x["act_id"] == "ro.lege.1-2020")
        self.assertEqual((r["adapter"], r["evidence"]["via"], r["status"], r["checked"]),
                         ("host", "firecrawl", UNCHANGED, True))
        self.assertEqual(r["notes"][0], "checked by hand from a version card (page read through Firecrawl)")
        self.assertEqual(r["related_reviewed"], ["lp-1", "lp-2"])
        state = lib.load_state(self.profile)
        self.assertEqual(state["acts"]["ro.lege.1-2020"]["related"], ["lp-1", "lp-2"])
        self.assertEqual(state["acts"]["ro.lege.1-2020"]["via"], "firecrawl")
        self.assertNotIn("ro.lege.1-2020", state["signals"])
        entry = issues.load(self.profile)["acts"]["ro.lege.1-2020"]
        self.assertEqual((entry["state"], entry["resolved_by"]), ("resolved", "checked by hand"))

    def test_record_via_host_note_is_unchanged(self):
        out = manual.record(self.profile, [act()], live_card(self.matter, "ro.lege.1-2020"), TODAY, root=self.matter)
        self.assertEqual(out["acts"][0]["notes"][0], "checked by hand from a version card")

    def test_record_rejects_unknown_via(self):
        with self.assertRaises(lib.WatchError) as cm:
            manual.record(self.profile, [act()], live_card(self.matter, "ro.lege.1-2020"), TODAY,
                          root=self.matter, via="browser")
        self.assertEqual(str(cm.exception), "--via must be one of host, firecrawl")
        self.assertFalse((self.profile / "laws" / "state.json").exists())

    def test_script_reading_via_host_without_adapter_host_is_not_by_hand(self):
        """`adapter`, not the tool, decides: a scripted Firecrawl reading never resolves listed amendments."""
        state = {"acts": {"x": {"related": ["a"]}}, "signals": {"x": [SIG]}}
        base = {"act_id": "x", "checked": True, "status": UNCHANGED, "current": {}, "next": None,
                "adapter": "legis_md", "related_reviewed": ["a", "b"], "evidence": {"via": "firecrawl"}}
        runner.update_state(state, base, "2026-11-05", None)
        self.assertEqual((state["acts"]["x"]["related"], list(state["signals"])), (["a"], ["x"]))
        runner.update_state(state, {**base, "adapter": "host"}, "2026-11-05", None)
        self.assertEqual((state["acts"]["x"]["related"], state["signals"]), (["a", "b"], {}))


class SavedMarkdown(unittest.TestCase):
    def test_md_text_file_hash_matches_scripted_markdown(self):
        path = FIX / "markdown-150997-2026-10-02.md"
        raw = path.read_text(encoding="utf-8")
        text = manual.saved_text(path)
        self.assertEqual(text, md_to_text(raw))
        url, r = md_page("150997", via="firecrawl")
        scripted = legis_md.check_act(live_act("150997"), FixtureFetcher({url: r}), T_MD)
        self.assertEqual(text_sha256(text), scripted.evidence.sha256)
        self.assertEqual(text_sha256(text), text_sha256(md_to_text(raw)))

    def test_other_saved_text_is_kept_as_it_is(self):
        with mock.patch.object(Path, "read_text", return_value="**raw** text"):
            self.assertEqual(manual.saved_text(Path("page.txt")), "**raw** text")
            self.assertEqual(manual.saved_text(Path("page.MD")), "raw text")

    def test_check_version_plain_md_equals_md_to_text(self):
        checker = manual._checker()
        self.assertEqual(len(MARKDOWN), 4)
        for path in MARKDOWN:
            md = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertEqual(checker.normalise(checker.plain(md, "a.md")), checker.normalise(md_to_text(md)))


class CliVia(Base):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--profile", str(self.profile), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_cli_record_via_flag_and_init_accepts_firecrawl(self):
        _, niches = lib.load_catalog()
        code, out, err = self.call("init", "--niches", next(iter(niches["niches"])), "--acts", "none",
                                   "--add", "eu.reg.2016-679", "--engines", "urllib,firecrawl,host")
        self.assertEqual(code, 0, err)
        self.assertEqual(lib.load_watchlist(self.profile / "laws" / "watchlist.yaml")["settings"]["engines"],
                         ["urllib", "firecrawl", "host"])
        card = live_card(self.matter, "eu.reg.2016-679")
        code, out, err = self.call("record", "--card", str(card), "--root", str(self.matter), "--via", "firecrawl")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["checked"])
        state = lib.load_state(self.profile)
        self.assertEqual(state["acts"]["eu.reg.2016-679"]["via"], "firecrawl")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["--profile", str(self.profile), "record", "--card", str(card), "--via", "browser"])
        self.assertEqual(cm.exception.code, 2)

    def test_usage_names_firecrawl_and_via(self):
        self.assertIn("[--via host|firecrawl]", cli.__doc__)


if __name__ == "__main__":
    unittest.main()
