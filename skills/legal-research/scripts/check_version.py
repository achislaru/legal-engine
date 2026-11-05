#!/usr/bin/env python3
"""Check a version card (the current-version check of one act) for completeness and consistency (stdlib only).

    python3 check_version.py <matter>/work/versions/<act>.json [--root <matter>]

Prints JSON. Exit 0 = structure passed, 1 = structural errors (listed), 2 = the card cannot be read.
It never visits a site and never proves the law: it checks that every claim the card makes is recorded the way
references/version-check.md requires, and, where a saved official text is given, that each quote is really in it.
A saved text may be plain text, HTML (`.html`/`.htm`, compared as the visible text) or markdown (`.md`, e.g. a page
read through Firecrawl, compared as plain text: links keep their label, emphasis and table bars are dropped).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

# why: the seven questions of a current-version check; each needs evidence or an honest "not verified".
POINTS = ("consolidation", "amendments", "deferred_entry", "secondary_acts", "case_law", "repeal",
          "status_of_changes")
# why: with scope "text" related acts and case law may stay open without blocking "current"; they are still gaps.
REQUIRED = {"full": set(POINTS), "text": set(POINTS) - {"secondary_acts", "case_law"}}
POINT_STATUSES = {"done", "not_verified"}
RESULTS = {"current", "outdated", "not_verified"}
CHANGE_STATUSES = {"in_force", "published_not_in_force", "draft"}
RELATED_KINDS = {"government_decision", "order", "authority_decision", "constitutional_court", "supreme_court",
                 "cjeu", "guidance"}
RELATED_EFFECTS = {"amends", "details", "suspends", "declares_unconstitutional", "interprets"}
MAX_QUOTE = 300
# why: a one-word quote matches almost any text and proves nothing.
MIN_QUOTE = 15
# why: an archived copy proves the text on the copy date only; older than this it cannot confirm currency.
ARCHIVE_MAX_DAYS = 14
# why: whether a newer version or change exists can only be seen on the live official page, never in a copy.
LIVE_ONLY = {"consolidation", "amendments", "status_of_changes"}
INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


class CardError(ValueError):
    """The version card cannot be read as a JSON object."""


def moment(value: str) -> datetime:
    """An ISO timestamp with a timezone, as in the source register."""
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return stamp


def _md_text(text: str) -> str:
    """Markdown → plain text, step for step as legal-watch's `adapters/common.md_to_text`.

    why duplicated: legal-research must run without legal-watch installed; a test in legal-watch pins the two as
    equal on live markdown pages, so a quote checked here is checked against the text monitoring hashes.
    """
    t = text or ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = _MD_LINK.sub(r"\1", t)
    t = t.replace("\\_", "_")
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    t = re.sub(r"\*\*|__", "", t)
    t = re.sub(r"(?<![\w])_(?=\S)|(?<=\S)_(?![\w])", "", t)
    t = re.sub(r"(?m)^\s*\|?\s*-{3,}\s*(\|\s*-{3,}\s*)*\|?\s*$", "", t)
    t = re.sub(r"\s*\|\s*", " | ", t)
    t = re.sub(r"_{3,}", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def plain(text: str, name: str) -> str:
    """Saved HTML is compared as the text a reader sees: tags dropped, entities decoded; saved markdown (`.md`)
    as its plain text, so a quote copied from the rendered page is found despite `**`, links and table bars."""
    lower = name.lower()
    if lower.endswith((".html", ".htm")):
        text = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    elif lower.endswith(".md"):
        text = _md_text(text)
    return text


def normalise(text: str) -> str:
    """Compare quotes loosely enough for layout, strictly enough for words.

    why: official HTML and PDF differ in spaces, line breaks, typographic quotes and the old Romanian cedilla
    letters (ş ţ vs ș ț); none of that changes the rule, every other character does.
    """
    text = unicodedata.normalize("NFC", text).translate(INVISIBLE)  # soft hyphens and zero-width from PDFs
    text = text.translate(str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț", "„": '"', "”": '"', "“": '"',
                                         "«": '"', "»": '"', "’": "'", "‘": "'", " ": " ", "–": "-",
                                         "—": "-"}))
    return re.sub(r"\s+", " ", text).strip()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate(card: dict, now: datetime, root: Path | None = None) -> dict:
    errors: list[str] = []
    gaps: list[str] = []
    quotes = {"checked": 0, "unchecked": 0}

    def require(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    def evidence_ok(point: str, label: str, ev: dict, checked: datetime) -> bool:
        """Validate one piece of evidence; return True when it can confirm currency today."""
        require(str(ev.get("url", "")).startswith(("https://", "http://")), label + "evidence without a URL")
        opened = moment(ev["opened_at"])
        require(opened <= checked, label + "evidence opened after checked_at")
        # why: law is never cached as truth; evidence read on another day is a past check, not this one.
        require(opened.astimezone(now.tzinfo).date() == now.date(), label + "evidence not opened today")
        quote = ev.get("quote") or ""
        require(len(quote.strip()) >= MIN_QUOTE, label + f"verbatim quote missing or shorter than {MIN_QUOTE} characters")
        require(len(quote) <= MAX_QUOTE, label + f"quote longer than {MAX_QUOTE} characters")
        # why: an archived copy is still evidence only of an official text; an unofficial site never is.
        require(ev.get("official") is True, label + "evidence is not an official text (an archived copy of one: official true + archived_on)")
        if ev.get("text_file"):
            check_quote(label, ev, quote)
        else:
            require(not ev.get("text_sha256"), label + "text_sha256 without text_file")
            quotes["unchecked"] += 1
        archived = ev.get("archived_on")
        if archived:
            age = (checked.date() - date.fromisoformat(archived)).days
            if point in LIVE_ONLY:
                gaps.append(label + "archived copy: shows the text on its date, not whether a newer version exists")
                return False
            if age > ARCHIVE_MAX_DAYS:
                gaps.append(label + f"archived copy is {age} days old: it confirms the text, not the current version")
                return False
        return True

    def check_quote(label: str, ev: dict, quote: str) -> None:
        if root is None:
            errors.append(label + "text_file given: pass --root <matter>")
            return
        path = root / ev["text_file"]
        if not _inside(path, root):
            errors.append(label + "text_file outside the matter folder")
            return
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(label + f"saved text cannot be read: {exc.strerror or exc}")
            return
        if ev.get("text_sha256"):
            require(hashlib.sha256(data).hexdigest() == ev["text_sha256"], label + "saved text changed (sha256)")
        text = plain(data.decode("utf-8", errors="replace"), path.name)
        found = normalise(quote) in normalise(text)
        require(found, label + "quote not found in the saved text")
        quotes["checked"] += 1

    try:
        require(card.get("schema_version", 1) == 1, "unsupported schema_version")
        act = card["act"]
        require(bool(act.get("id")) and bool(act.get("title")), "act needs id and title")
        checked = moment(card["checked_at"])
        analysis = date.fromisoformat(card["analysis_date"])
        require(checked <= now, "checked_at is in the future")
        # why: future conduct is answered as of today; adopted future changes go to next_versions / changes.
        require(analysis <= checked.astimezone(now.tzinfo).date(), "analysis_date after the check date")
        require(checked.astimezone(now.tzinfo).date() == now.date(), "card is not from today: re-check required")
        scope = card.get("scope", "full")
        require(scope in REQUIRED, "scope must be 'full' or 'text'")
        required = REQUIRED.get(scope, REQUIRED["full"])
        require(bool(card.get("cited_provisions")), "no cited provisions: say which articles the answer relies on")

        open_required: list[str] = []
        stale: list[str] = []
        points = card["points"]
        for name in POINTS:
            label = name + ": "
            point = points.get(name)
            if not isinstance(point, dict):
                errors.append(label + "missing (record it, or mark it not_verified with a reason)")
                open_required.append(name)
                continue
            status = point.get("status")
            require(status in POINT_STATUSES, label + "status must be done or not_verified")
            if status == "done":
                evidence = point.get("evidence") or []
                # why: "no amendments" is a claim too; it needs the page that shows the list and its last entry.
                require(bool(evidence), label + "done without evidence")
                require(bool(point.get("note")), label + "done without a note of what was found")
                fresh = [evidence_ok(name, f"{label}evidence {i + 1}: ", ev, checked) for i, ev in enumerate(evidence)]
                if evidence and not any(fresh):
                    stale.append(name)
            else:
                require(bool(point.get("reason")), label + "not_verified needs a reason")
                require(bool(point.get("depends")), label + "not_verified needs what depends on it")
                gaps.append(label + str(point.get("reason", "")) + " → " + str(point.get("depends", "")))
                if name in required:
                    open_required.append(name)

        latest = card.get("latest_in_force") or {}
        latest_from = date.fromisoformat(latest["version_from"]) if latest.get("version_from") else None
        if latest_from:
            # why: registers list the newest version first even when it applies only later; that one is "next".
            require(latest_from <= analysis, "latest_in_force applies after the analysis date: it is a next version")
        for i, nxt in enumerate(card.get("next_versions", [])):
            require(date.fromisoformat(nxt["applies_from"]) > analysis,
                    f"next version {i + 1} already applies on the analysis date: it is in force, not next")

        held = card.get("held_version") or {}
        held_from = date.fromisoformat(held["version_from"]) if held.get("version_from") else None
        newer_change = False
        for i, ch in enumerate(card.get("changes", [])):
            label = f"change {i + 1}: "
            status = ch.get("status")
            require(status in CHANGE_STATUSES, label + "unknown status")
            require(bool(ch.get("act")) and bool(ch.get("published")), label + "needs the amending act and publication")
            if status == "draft":
                # why: a bill or a proposal is not law; it may be mentioned for information only.
                require(not ch.get("affects_conclusion"), label + "a draft cannot change the conclusion")
                continue
            when = ch.get("applies_from") or ch.get("in_force_from")
            if not when:
                errors.append(label + "needs applies_from (or in_force_from)")
                continue
            applies = date.fromisoformat(when)
            if status == "published_not_in_force":
                require(applies > analysis, label + "'published_not_in_force' but applies on the analysis date")
            if status == "in_force":
                require(applies <= analysis, label + "'in_force' but applies only after the analysis date")
                newer_change = newer_change or bool(held_from and held_from < applies <= analysis)

        for i, rel in enumerate(card.get("related", [])):
            label = f"related {i + 1}: "
            require(rel.get("kind") in RELATED_KINDS, label + "unknown kind")
            require(rel.get("effect") in RELATED_EFFECTS, label + "unknown effect")
            require(isinstance(rel.get("binding"), bool), label + "say whether it binds (true/false)")
            if rel.get("kind") == "guidance":
                require(rel.get("binding") is False, label + "guidance is not law: binding must be false")
            require(str(rel.get("url", "")).startswith(("https://", "http://")), label + "needs a URL")

        result = card.get("result")
        require(result in RESULTS, "result must be current, outdated or not_verified")
        repealed = card.get("repealed") or {}
        gone = bool(repealed.get("from") and date.fromisoformat(repealed["from"]) <= analysis)
        if any(repealed.values()):  # why: the template keeps the keys with nulls for an act not repealed
            require(bool(repealed.get("by")) and bool(repealed.get("from")), "repealed needs by and from")
        # why: the held version must be the one in force, not merely not older; a future held text is wrong too.
        behind = bool(held_from and latest_from and held_from != latest_from) or gone
        behind = behind or bool(held_from and held_from > analysis)
        if result == "current":
            require(not open_required, "current needs every required point done: " + ", ".join(open_required))
            require(not [p for p in stale if p in required],
                    "current cannot rest on archived copies only: " + ", ".join(p for p in stale if p in required))
            require(latest_from is not None, "current needs latest_in_force.version_from")
            require(not behind, "the held version is not the latest in force (or the act is repealed): result is outdated")
            require(not newer_change, "a change in force after the held version: result is outdated")
        if result == "outdated":
            require(bool(card.get("outdated_reason")), "outdated needs outdated_reason")
        if result == "not_verified":
            require(bool(open_required or stale), "not_verified but every required point is closed")
            require(bool(card.get("working_conclusion")),
                    "not_verified needs a working_conclusion (last known text, its date, what stays open)")
        if result != "outdated" and (behind or newer_change):
            errors.append("the held version is behind the law in force: result must be outdated")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        errors.append(f"invalid schema/date: {exc!r}")
    return {"structural_status": "failed" if errors else "passed", "result": card.get("result"),
            "errors": errors, "gaps": gaps, "quotes": quotes, "legal_truth_checked": False}


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CardError(f"cannot read the version card {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CardError(f"the version card {path} must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card", type=Path)
    ap.add_argument("--root", type=Path, help="matter folder; saved texts (text_file: .txt, .html or .md) are "
                                               "relative to it")
    args = ap.parse_args(argv)
    try:
        result = validate(load(args.card), datetime.now().astimezone(), args.root)
    except CardError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
