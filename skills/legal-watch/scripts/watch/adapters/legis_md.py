"""legis_md: the State Register of Legal Acts of Moldova (www.legis.md).

Input: an act record with a source `{"kind": "legis_md", "doc_id": …}`. On legis.md a doc_id is one specific
version of the act, not the act as such: a newer version gets a new doc_id, so a page that still shows the
held version is not proof that nothing changed elsewhere (the core `classify` also compares `current.doc_id`).
Output: `contract.AdapterResult`.

The version rule: the version in force is the latest one with a start date on or before the run date; a later
one is `next`, never in force (the trap of future versions).

Two parsers, chosen by what the fetch engine returned:

HTML text (`legis_md/text-v1`, NOT calibrated: legis.md answers automated browsers with an anti-bot page, so a
live body was never read this way):
- the amendment list in the register's label format «LP114 din 18.06.26, MO288-290/30.06.26 art.290» followed by
  «în vigoare DD.MM.YY»; a label without a start date is not used;
- an act without amendments: «Data intrării în vigoare: DD.MM.YYYY» → «forma de bază»;
- repeal: «ABROGAT(Ă)» / «Abrogat(ă) prin …» only in the header (before «Articolul 1»); inline notes such as
  «[Art.5 abrogat prin …]» would otherwise look like a repeal of the whole act.

Markdown (`legis_md/markdown-v1`, calibrated on live markdown pages of three acts, see the fixtures
`markdown-*.md`), used when the engine returned markdown and no HTML (the `firecrawl` or a user `command` engine):
- the act card «Fişa actului juridic»: amendment labels «LP189 din 10.07.25, MO502-505/25.09.25 art.652; în vigoare
  25.10.25» and «Data abrogării | <date>»;
- the version bar at the end of the page («- 25-10-2025»): every date is a version; its label comes from the
  amendment list with the same start date, else «redacția din DD.MM.YYYY (bara legis.md)»;
- the same version as the baseline: when the start date equals `current.in_force_from` and the baseline label
  names the amending act, its Official Gazette number or that date, the page's doc_id is attached so the core
  treats it as the same version (`align_with_baseline`).

Every page must identify the act by number and year, else parse_failed. Any doubt gives parse_failed,
fetch_failed or blocked_403, never unchanged. An anti-bot page is reported as blocked and never bypassed.
"""
from __future__ import annotations

import datetime as _dt
import re

from ..contract import (BLOCKED_403, FETCH_FAILED, PARSE_FAILED, AdapterResult, Evidence, Redaction,
                        act_number_year, classify, parse_date, text_sha256)
from ..fetchers import Fetcher, FetchResult
from .common import is_markdown, page_text, source_doc_id

ADAPTER = "legis_md"
PARSER_ID = "legis_md/text-v1"
PARSER_CALIBRATED = False        # HTML path: legis.md served an anti-bot page, no live body was ever parsed
PARSER_ID_MD = "legis_md/markdown-v1"
PARSER_CALIBRATED_MD = True      # markdown path: checked against live markdown pages of three acts
PAGE_URL = "https://www.legis.md/cautare/getResults?doc_id={doc_id}&lang=ro"
MIN_TEXT_CHARS = 2000

_D = r"\d{2}\.\d{2}\.(?:\d{4}|\d{2})"
AMENDMENT_RE = re.compile(
    r"(?P<label>\b[A-Z]{1,4}\d+(?:-[IVXL]+)?\s+din\s+" + _D + r"\s*,\s*MO\s*[\d\-]+\s*/\s*" + _D
    + r"\s+art\.?\s*\d+)"
    r"(?:\s*[;,]?\s*în\s+vigoare\s*(?:din\s*)?(?P<date>" + _D + r"))?")
BASE_IN_FORCE_RE = re.compile(r"Data\s+intr[ăa]rii\s+[îi]n\s+vigoare\s*:?\s*(?P<date>\d{2}[.\-]\d{2}[.\-]\d{4})",
                              re.I)
REPEAL_RE = re.compile(r"(?:^|\n)\s*(?:ABROGAT[ĂA]?\b|Abrogat[ăa]?\s+prin\b)(?P<by>[^\n]{0,120})")
BAR_RE = re.compile(r"(?m)^\s*-\s*(?P<d>\d{2})-(?P<m>\d{2})-(?P<y>\d{4})\s*$")
CARD_REPEAL_RE = re.compile(r"Data\s+abrog[ăa]rii\s*\|\s*(?P<v>[^|\n]{0,40})")
CARD_BASE_RE = re.compile(r"Data\s+intr[ăa]rii\s+[îi]n\s+vigoare\s*\|?\s*:?\s*(?P<date>\d{2}[.\-]\d{2}[.\-]\d{4})",
                          re.I)
ACT_TOKEN_RE = re.compile(r"^(?P<t>[A-Z]{1,4}\d+(?:\s*-\s*[IVXL]+)?\s+din\s+\d{2}\.\d{2}\.\d{2,4})")
MO_NUM_RE = re.compile(r"\bMO\s*(?:nr\.?\s*)?(?P<n>\d+(?:\s*-\s*\d+)?)", re.I)


def page_source(act: dict) -> tuple[str | None, str | None]:
    doc_id = source_doc_id(act, "legis_md")
    return (doc_id, PAGE_URL.format(doc_id=doc_id)) if doc_id else (None, None)


def identifies_act(act: dict, title: str, text: str) -> bool:
    """The page names the act: «154/2003», «154-XV/03» or «Nr. 154 din 28.03.2003» in the title or the head."""
    ny = act_number_year(act)
    if ny is None:
        return False                     # nothing to check the page against: never assume it is the right one
    num, year = ny
    yy = year[2:]
    hay = (title or "") + "\n" + (text or "")[:5000]
    return bool(re.search(rf"(?<!\d){num}(?:-[IVXL]+)?\s*/\s*(?:{year}|{yy})(?!\d)", hay)
                or re.search(rf"nr\.?\s*{num}(?:-[IVXL]+)?\s+din\s+[^\n]{{0,25}}?{year}", hay, re.I))


def header_of(text: str) -> str:
    m = re.search(r"\n\s*Articolul\s+1\b", text)
    return text[: m.start()] if m else text[:3000]


def parse_page(text: str, doc_id: str | None) -> tuple[list[Redaction], bool, str | None, str]:
    """HTML text → (versions, repealed?, label of the repealing act, parse mode)."""
    head = header_of(text)
    rep = REPEAL_RE.search(head)
    if rep:
        by = rep.group("by").strip(" :.-") or None
        return [], True, by, "repeal-header"
    reds: list[Redaction] = []
    for m in AMENDMENT_RE.finditer(text):
        date = parse_date(m.group("date")) if m.group("date") else None
        if date is None:
            continue
        reds.append(Redaction(label=re.sub(r"\s+", " ", m.group("label")).strip(),
                              in_force_from=date.isoformat(), doc_id=None))
    if reds:
        return reds, False, None, "amendment-list"
    m = BASE_IN_FORCE_RE.search(head)
    if m:
        d = parse_date(m.group("date").replace("-", "."))
        if d:
            return [Redaction(label="forma de bază", in_force_from=d.isoformat(), doc_id=doc_id)], \
                False, None, "base-form"
    return [], False, None, "none"


def parse_page_markdown(text: str, doc_id: str | None,
                        today: _dt.date) -> tuple[list[Redaction], bool, str | None, str]:
    """Text of a markdown page → (versions, repealed?, repeal label, parse mode)."""
    m = CARD_REPEAL_RE.search(text)
    abrog = parse_date(m.group("v").strip(" .")) if m else None
    rep = REPEAL_RE.search(header_of(text))
    if rep or (abrog is not None and abrog <= today):
        by = (rep.group("by").strip(" :.-") if rep else None) or (f"abrogat din {abrog:%d.%m.%Y}" if abrog else None)
        return [], True, by, "md-repeal"
    amend: dict[str, str] = {}
    for am in AMENDMENT_RE.finditer(text):
        d = parse_date(am.group("date")) if am.group("date") else None
        if d is not None:
            amend.setdefault(d.isoformat(), re.sub(r"\s+", " ", am.group("label")).strip())
    bar = []
    for bm in BAR_RE.finditer(text):
        try:
            bar.append(_dt.date(int(bm.group("y")), int(bm.group("m")), int(bm.group("d"))).isoformat())
        except ValueError:
            continue
    dates = sorted(set(bar) | set(amend))
    reds = [Redaction(label=amend.get(d) or f"redacția din {_dt.date.fromisoformat(d):%d.%m.%Y} (bara legis.md)",
                      in_force_from=d, doc_id=None) for d in dates]
    if abrog is not None and abrog > today:
        # A repeal dated in the future is a future version, not a repeal today.
        reds.append(Redaction(label=f"abrogare din {abrog:%d.%m.%Y}", in_force_from=abrog.isoformat()))
    if reds:
        return reds, False, None, "md-bar+amendments" if bar else "md-amendments"
    bm = CARD_BASE_RE.search(text)
    if bm:
        d = parse_date(bm.group("date").replace("-", "."))
        if d:
            return [Redaction(label="forma de bază", in_force_from=d.isoformat(), doc_id=doc_id)], \
                False, None, "md-base-form"
    return [], False, None, "md-none"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _mo_numbers(s: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group("n")) for m in MO_NUM_RE.finditer(s or "")}


def align_with_baseline(act: dict, reds: list[Redaction], doc_id: str | None) -> list[str]:
    """Mark a page version as the held one when only the label wording differs (attach the page doc_id).

    The comparison goes by the start date of the held version, not by the label string: a baseline written as
    «text inițial, MO 382-385/20.08.2026» and a page that only shows the bar date 23-08-2026 are the same version.
    - a page version without an amending act (a bar date or the base form) with the same date is the same version;
    - a version with an amending act («LP189 din 10.07.25, MO502-505/25.09.25 art.652») is the same only when the
      baseline label names that act, its Official Gazette number or the start date; otherwise it is a different
      version and the core reports new_in_force.
    """
    cur = act.get("current") or {}
    reg_d = parse_date(cur.get("in_force_from"))
    raw_label = cur.get("label") or ""
    reg_label = _norm(raw_label)
    notes: list[str] = []
    if reg_d is None or not reg_label or not doc_id:
        return notes
    for r in reds:
        if parse_date(r.in_force_from) != reg_d or _norm(r.label) == reg_label:
            continue
        tok = ACT_TOKEN_RE.match(r.label or "")
        if tok is None:
            if AMENDMENT_RE.search(r.label or ""):
                continue  # looks like an amending act but is unreadable: do not guess
            r.doc_id = doc_id
            notes.append(f"baseline {raw_label!r} = page version {r.label!r}: same start date {reg_d}, "
                         "no amending act on the page for that date")
            continue
        same_mo = bool(_mo_numbers(r.label) & _mo_numbers(raw_label))
        if _norm(tok.group("t")) in reg_label or same_mo or _norm(f"{reg_d:%d.%m.%Y}") in reg_label:
            r.doc_id = doc_id
            notes.append(f"baseline {raw_label!r} = page version {r.label!r} ({reg_d})")
    return notes


def with_page_doc_id(act: dict, doc_id: str | None) -> dict:
    """The act with the held version's doc_id filled from the watched page when the baseline lacks it.

    On legis.md the watched doc_id IS the page of the held version, so a baseline written without a doc_id
    still refers to it; the core matches a page version to the held one by doc_id + start date.
    """
    cur = act.get("current")
    if not cur or cur.get("doc_id") or not doc_id:
        return act
    return dict(act, current=dict(cur, doc_id=doc_id))


def check_act(act: dict, fetcher: Fetcher, today: _dt.date) -> AdapterResult:
    act_id = act["id"]
    doc_id, url = page_source(act)
    if url is None:
        return AdapterResult(act_id=act_id, adapter=ADAPTER, status=FETCH_FAILED,
                             error="act has no legis_md source with a doc_id").validate()
    r: FetchResult = fetcher.get(url)
    md = is_markdown(r)
    text = page_text(r)
    ev = Evidence(url=url, fetched_at=r.fetched_at, http_status=r.status,
                  sha256=text_sha256(text) if text else None, parser=None,
                  parser_calibrated=PARSER_CALIBRATED_MD if md else PARSER_CALIBRATED, via=r.via)

    def fail(status, err):
        return AdapterResult(act_id=act_id, adapter=ADAPTER, status=status, evidence=ev, error=err,
                             notes=list(r.notes)).validate()

    if r.error:
        return fail(FETCH_FAILED, r.error)
    if r.blocked:
        return fail(BLOCKED_403, f"{r.blocked_reason}; page title {r.title!r}; "
                                 "anti-bot check not bypassed (by design)")
    if r.status is None or r.status >= 400:
        return fail(FETCH_FAILED, f"HTTP {r.status}")
    if r.subresource_403 and len(text) < MIN_TEXT_CHARS:
        return fail(BLOCKED_403, f"body not delivered: 403 on {len(r.subresource_403)} subresource(s), "
                                 f"e.g. {r.subresource_403[0]}")
    if len(text) < MIN_TEXT_CHARS:
        return fail(PARSE_FAILED, f"page text too short ({len(text)} chars): empty or truncated")
    if act_number_year(act) is None:
        return fail(PARSE_FAILED, f"{act_id} has no number/year: the page cannot be checked to be this act")
    if not identifies_act(act, r.title, text):
        return fail(PARSE_FAILED, f"page does not identify {act_id} (title {r.title!r})")

    if md:
        reds, repealed, by, mode = parse_page_markdown(text, doc_id, today)
        ev.parser = f"{PARSER_ID_MD}:{mode}"
        pre = align_with_baseline(act, reds, doc_id)
    else:
        reds, repealed, by, mode = parse_page(text, doc_id)
        ev.parser = f"{PARSER_ID}:{mode}"
        pre = []
    status, cur, nxt, err, notes = classify(act=with_page_doc_id(act, doc_id), parsed=reds, today=today,
                                            repealed=repealed, repealed_label=by)
    notes = pre + list(r.notes) + notes
    if not ev.parser_calibrated:
        notes.append("parser not calibrated against a live legis.md page")
    return AdapterResult(act_id=act_id, adapter=ADAPTER, status=status, current=cur, next=nxt,
                         evidence=ev, error=err, notes=notes).validate()
