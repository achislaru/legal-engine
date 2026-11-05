"""Tests for check_version.py on synthetic cards (no real act, no network)."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import check_version as cv  # noqa: E402

NOW = datetime.now().astimezone()
TODAY = NOW.date()
STAMP = (NOW - timedelta(minutes=5)).isoformat()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def evidence(**extra) -> dict:
    ev = {"url": "https://official.example.org/act/1", "opened_at": STAMP, "official": True,
          "quote": "Prezenta lege intră în vigoare la data publicării."}
    ev.update(extra)
    return ev


def good_card() -> dict:
    points = {name: {"status": "done", "note": "checked", "evidence": [evidence()]} for name in cv.POINTS}
    return {
        "schema_version": 1,
        "act": {"id": "xx.lege.1-2020", "title": "Synthetic act", "jurisdiction": "RO"},
        "checked_at": STAMP,
        "analysis_date": TODAY.isoformat(),
        "scope": "full",
        "held_version": {"label": "v3", "version_from": day(-100)},
        "cited_provisions": ["art. 5"],
        "points": points,
        "latest_in_force": {"label": "v3", "version_from": day(-100)},
        "next_versions": [{"label": "v4", "applies_from": day(30)}],
        "changes": [
            {"act": "Lege 2/2021", "published": "MO 1", "status": "in_force", "applies_from": day(-100)},
            {"act": "Lege 9/2026", "published": "MO 9", "status": "published_not_in_force", "applies_from": day(30)},
            {"act": "Proiect 7", "published": "site of parliament", "status": "draft"},
        ],
        "related": [{"id": "r1", "kind": "guidance", "effect": "interprets", "binding": False,
                     "url": "https://authority.example.org/guide"}],
        "result": "current",
    }


def check(card: dict, root: Path | None = None) -> dict:
    return cv.validate(card, NOW, root)


class ValidCard(unittest.TestCase):
    def test_good_card_passes(self):
        res = check(good_card())
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["structural_status"], "passed")
        self.assertFalse(res["legal_truth_checked"])
        self.assertEqual(res["quotes"], {"checked": 0, "unchecked": 7})

    def test_text_scope_allows_open_related_points(self):
        card = good_card()
        card["scope"] = "text"
        card["points"]["case_law"] = {"status": "not_verified", "reason": "court site blocked",
                                      "depends": "reading of art. 5"}
        res = check(card)
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(res["gaps"]), 1)


class Points(unittest.TestCase):
    def test_missing_point(self):
        card = good_card()
        del card["points"]["repeal"]
        self.assertTrue(any(e.startswith("repeal: missing") for e in check(card)["errors"]))

    def test_done_without_evidence_or_note(self):
        card = good_card()
        card["points"]["amendments"] = {"status": "done", "evidence": []}
        errs = check(card)["errors"]
        self.assertIn("amendments: done without evidence", errs)
        self.assertIn("amendments: done without a note of what was found", errs)

    def test_bad_status(self):
        card = good_card()
        card["points"]["amendments"]["status"] = "ok"
        self.assertIn("amendments: status must be done or not_verified", check(card)["errors"])

    def test_not_verified_needs_reason_and_dependency(self):
        card = good_card()
        card["points"]["repeal"] = {"status": "not_verified"}
        card["result"] = "not_verified"
        card["working_conclusion"] = "last text of v3"
        errs = check(card)["errors"]
        self.assertIn("repeal: not_verified needs a reason", errs)
        self.assertIn("repeal: not_verified needs what depends on it", errs)

    def test_current_with_open_required_point(self):
        card = good_card()
        card["points"]["repeal"] = {"status": "not_verified", "reason": "site down", "depends": "F001"}
        self.assertTrue(any(e.startswith("current needs every required point") for e in check(card)["errors"]))

    def test_evidence_rules(self):
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [
            {"url": "ftp://x", "opened_at": (NOW + timedelta(hours=1)).isoformat(), "official": False,
             "quote": "x" * 301}]
        errs = check(card)["errors"]
        for msg in ("evidence without a URL", "evidence opened after checked_at", "longer than 300",
                    "not an official text"):
            self.assertTrue(any(msg in e for e in errs), msg)

    def test_empty_quote(self):
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [evidence(quote="  ")]
        self.assertTrue(any("quote missing or shorter" in e for e in check(card)["errors"]))

    def test_one_letter_quote_proves_nothing(self):
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [evidence(quote="a")]
        self.assertTrue(any("shorter than 15" in e for e in check(card)["errors"]))

    def test_evidence_from_another_day(self):
        card = good_card()
        card["points"]["amendments"]["evidence"] = [evidence(opened_at="2020-01-01T00:00:00+00:00")]
        self.assertIn("amendments: evidence 1: evidence not opened today", check(card)["errors"])

    def test_unofficial_archived_copy(self):
        card = good_card()
        card["points"]["case_law"]["evidence"] = [evidence(official=False, archived_on=day(-1))]
        self.assertTrue(any("not an official text" in e for e in check(card)["errors"]))

    def test_hash_without_file(self):
        card = good_card()
        card["points"]["repeal"]["evidence"] = [evidence(text_sha256="ab")]
        self.assertIn("repeal: evidence 1: text_sha256 without text_file", check(card)["errors"])


class Archive(unittest.TestCase):
    def test_fresh_archive_copy_confirms_wording(self):
        card = good_card()
        card["points"]["case_law"]["evidence"] = [evidence(archived_on=day(-3))]
        self.assertEqual(check(card)["errors"], [])

    def test_archive_never_shows_the_latest_version(self):
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [evidence(archived_on=day(-1))]
        res = check(card)
        self.assertTrue(any("archived copies only: consolidation" in e for e in res["errors"]))

    def test_old_archive_copy_cannot_prove_current(self):
        card = good_card()
        card["points"]["case_law"]["evidence"] = [evidence(archived_on=day(-40))]
        res = check(card)
        self.assertTrue(any("archived copies only" in e for e in res["errors"]))
        self.assertTrue(any("40 days old" in g for g in res["gaps"]))

    def test_old_archive_copy_with_not_verified_passes(self):
        card = good_card()
        card["points"]["case_law"]["evidence"] = [evidence(archived_on=day(-40))]
        card["result"] = "not_verified"
        card["working_conclusion"] = "archived text of v3 from 40 days ago; later changes unknown"
        self.assertEqual(check(card)["errors"], [])


class Versions(unittest.TestCase):
    def test_next_version_is_not_in_force(self):
        card = good_card()
        card["latest_in_force"]["version_from"] = day(10)
        self.assertTrue(any("it is a next version" in e for e in check(card)["errors"]))

    def test_next_version_already_applies(self):
        card = good_card()
        card["next_versions"] = [{"label": "v4", "applies_from": day(-1)}]
        self.assertTrue(any("in force, not next" in e for e in check(card)["errors"]))

    def test_held_behind_latest_is_outdated(self):
        card = good_card()
        card["latest_in_force"]["version_from"] = day(-10)
        errs = check(card)["errors"]
        self.assertTrue(any(e.startswith("the held version is not the latest in force") for e in errs))
        self.assertIn("the held version is behind the law in force: result must be outdated", errs)

    def test_change_in_journal_not_in_consolidation(self):
        card = good_card()
        card["changes"].append({"act": "Lege 3/2026", "published": "MO 3", "status": "in_force",
                                "applies_from": day(-2)})
        self.assertIn("a change in force after the held version: result is outdated", check(card)["errors"])

    def test_future_held_version_is_not_current(self):
        card = good_card()
        card["held_version"]["version_from"] = day(20)
        self.assertIn("the held version is behind the law in force: result must be outdated", check(card)["errors"])

    def test_repealed_act_is_not_current(self):
        card = good_card()
        card["repealed"] = {"by": "Lege 5/2026", "from": day(-5)}
        self.assertIn("the held version is behind the law in force: result must be outdated", check(card)["errors"])
        card["repealed"] = {"by": "Lege 5/2026"}
        self.assertIn("repealed needs by and from", check(card)["errors"])

    def test_in_force_change_in_the_future(self):
        card = good_card()
        card["changes"][0]["applies_from"] = day(40)
        self.assertIn("change 1: 'in_force' but applies only after the analysis date", check(card)["errors"])

    def test_change_without_dates_and_fallback(self):
        card = good_card()
        card["changes"].append({"act": "Lege 4/2026", "published": "MO 4", "status": "published_not_in_force"})
        self.assertIn("change 4: needs applies_from (or in_force_from)", check(card)["errors"])
        card["changes"][3] = {"act": "Lege 4/2026", "published": "MO 4", "status": "in_force",
                              "in_force_from": day(-2)}
        self.assertIn("a change in force after the held version: result is outdated", check(card)["errors"])

    def test_future_analysis_date(self):
        card = good_card()
        card["analysis_date"] = day(60)
        self.assertIn("analysis_date after the check date", check(card)["errors"])

    def test_outdated_needs_reason(self):
        card = good_card()
        card["latest_in_force"]["version_from"] = day(-10)
        card["result"] = "outdated"
        self.assertEqual(check(card)["errors"], ["outdated needs outdated_reason"])
        card["outdated_reason"] = "v4 from " + day(-10)
        self.assertEqual(check(card)["errors"], [])

    def test_current_needs_latest(self):
        card = good_card()
        card["latest_in_force"] = {}
        self.assertIn("current needs latest_in_force.version_from", check(card)["errors"])

    def test_not_verified_with_everything_closed(self):
        card = good_card()
        card["result"] = "not_verified"
        errs = check(card)["errors"]
        self.assertIn("not_verified but every required point is closed", errs)
        self.assertTrue(any("working_conclusion" in e for e in errs))


class ChangesAndRelated(unittest.TestCase):
    def test_draft_cannot_change_conclusion(self):
        card = good_card()
        card["changes"][2]["affects_conclusion"] = True
        self.assertIn("change 3: a draft cannot change the conclusion", check(card)["errors"])

    def test_published_not_in_force_already_applies(self):
        card = good_card()
        card["changes"][1]["applies_from"] = day(-1)
        self.assertTrue(any("change 2: 'published_not_in_force'" in e for e in check(card)["errors"]))

    def test_change_fields(self):
        card = good_card()
        card["changes"].append({"status": "maybe"})
        errs = check(card)["errors"]
        self.assertIn("change 4: unknown status", errs)
        self.assertIn("change 4: needs the amending act and publication", errs)

    def test_guidance_is_not_binding(self):
        card = good_card()
        card["related"][0]["binding"] = True
        self.assertIn("related 1: guidance is not law: binding must be false", check(card)["errors"])

    def test_related_fields(self):
        card = good_card()
        card["related"] = [{"kind": "blog", "effect": "likes", "url": "x"}]
        errs = check(card)["errors"]
        for msg in ("unknown kind", "unknown effect", "say whether it binds", "needs a URL"):
            self.assertTrue(any(msg in e for e in errs), msg)


class Header(unittest.TestCase):
    def test_not_from_today(self):
        card = good_card()
        old = (NOW - timedelta(days=2)).isoformat()
        card["checked_at"] = old
        for p in card["points"].values():
            p["evidence"][0]["opened_at"] = old
        self.assertIn("card is not from today: re-check required", check(card)["errors"])

    def test_future_check_and_bad_values(self):
        card = good_card()
        card["checked_at"] = (NOW + timedelta(hours=2)).isoformat()
        card["scope"] = "half"
        card["schema_version"] = 2
        card["cited_provisions"] = []
        card["result"] = "fine"
        errs = check(card)["errors"]
        for msg in ("checked_at is in the future", "scope must be", "unsupported schema_version",
                    "no cited provisions", "result must be"):
            self.assertTrue(any(msg in e for e in errs), msg)

    def test_timestamp_without_zone(self):
        card = good_card()
        card["checked_at"] = "2026-01-01T10:00:00"
        self.assertTrue(check(card)["errors"][0].startswith("invalid schema/date"))

    def test_missing_act(self):
        card = good_card()
        del card["act"]
        self.assertTrue(check(card)["errors"][0].startswith("invalid schema/date"))


class Quotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "work" / "sources").mkdir(parents=True)
        self.text = "Art. 5. — Prezenta  lege\nintră în vigoare la data publicării.".replace("ț", "ţ")
        self.file = self.root / "work" / "sources" / "act.txt"
        self.file.write_text(self.text, encoding="utf-8")
        self.sha = hashlib.sha256(self.file.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, **extra) -> dict:
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [
            evidence(text_file="work/sources/act.txt", text_sha256=self.sha, **extra)]
        return card

    def test_quote_found_despite_layout_and_cedilla(self):
        res = check(self.card(), self.root)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["quotes"], {"checked": 1, "unchecked": 6})

    def test_html_entities_tags_and_soft_hyphens(self):
        page = self.root / "work" / "sources" / "act.html"
        page.write_text("<p>Prezenta lege <b>intr&#259; &icirc;n</b> vi\u00adgoare la data public&#259;rii.</p>"
                        "<script>var x = 1;</script>", encoding="utf-8")
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [evidence(text_file="work/sources/act.html")]
        self.assertEqual(check(card, self.root)["errors"], [])

    def test_quote_not_in_text(self):
        res = check(self.card(quote="Prezenta lege se abrogă."), self.root)
        self.assertTrue(any("quote not found" in e for e in res["errors"]))

    def test_changed_file(self):
        self.file.write_text(self.text + " x", encoding="utf-8")
        self.assertTrue(any("sha256" in e for e in check(self.card(), self.root)["errors"]))

    def test_needs_root(self):
        self.assertTrue(any("pass --root" in e for e in check(self.card())["errors"]))

    def test_outside_root_and_missing_file(self):
        card = self.card()
        card["points"]["consolidation"]["evidence"][0]["text_file"] = "../escape.txt"
        self.assertTrue(any("outside the matter" in e for e in check(card, self.root)["errors"]))
        card["points"]["consolidation"]["evidence"][0]["text_file"] = "work/sources/none.txt"
        self.assertTrue(any("cannot be read" in e for e in check(card, self.root)["errors"]))


class Cli(unittest.TestCase):
    def run_main(self, args: list[str]) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cv.main(args)
        return code, json.loads(out.getvalue())

    def test_cli_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.json"
            path.write_text(json.dumps(good_card()), encoding="utf-8")
            self.assertEqual(self.run_main([str(path)])[0], 0)
            bad = good_card()
            bad["result"] = "fine"
            path.write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(self.run_main([str(path)])[0], 1)
            path.write_text("[1]", encoding="utf-8")
            code, data = self.run_main([str(path)])
            self.assertEqual(code, 2)
            self.assertIn("must be a JSON object", data["error"])
            code, data = self.run_main([str(Path(tmp) / "none.json")])
            self.assertEqual(code, 2)

    def test_template_is_readable_and_fails_honestly(self):
        card = cv.load(HERE.parent / "assets" / "version-card.json")
        res = cv.validate(copy.deepcopy(card), NOW)
        self.assertEqual(res["structural_status"], "failed")



class MarkdownText(unittest.TestCase):
    """A page saved as markdown (e.g. read through Firecrawl) is compared as its plain text."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "work" / "sources").mkdir(parents=True)
        (self.root / "work" / "sources" / "act.md").write_text(
            "## Art. 5\n\nPrezenta **lege** intră în vigoare la data [publicării](https://official.example.org/mo).\n"
            "\n| Data | Act |\n|---|---|\n| 01.01.2026 | LP1 |\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, quote: str) -> dict:
        card = good_card()
        card["points"]["consolidation"]["evidence"] = [evidence(text_file="work/sources/act.md", quote=quote)]
        return card

    def test_quote_of_the_plain_text_passes(self):
        res = check(self.card("Prezenta lege intră în vigoare la data publicării."), self.root)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["quotes"]["checked"], 1)

    def test_quote_not_in_the_text_still_fails(self):
        res = check(self.card("Prezenta lege se abrogă la data publicării."), self.root)
        self.assertTrue(any("quote not found" in e for e in res["errors"]))

    def test_plain_drops_markup_only_for_md(self):
        md = "**a** [b](https://x.example.org) \\_c\n|---|---|\n| d | e |"
        self.assertEqual(cv.plain(md, "x.MD"), "a b c | d | e |")
        self.assertEqual(cv.plain(md, "x.txt"), md)


if __name__ == "__main__":
    unittest.main()
