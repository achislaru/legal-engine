"""The result contract of the monitoring adapters: statuses, the shape of a result, the version rule.

Two kinds of result:
- `AdapterResult`, one per act: a status from STATUSES, the version in force (`current`), the next known
  version (`next`), the evidence (URL, time, SHA-256 of the page text) and an error.
- `SourceScan`, one per signal source (the Moldovan Official Gazette): new issues and the items that mention a
  watched act. A mention is a signal to check the act, not a decision that it changed, so a scan never gives an
  act a status.

The invariant "a failure is never `unchanged`" is enforced here, in `AdapterResult.validate()` and in
`classify()`: `unchanged` needs a snapshot hash, a parsed version in force and no error. A version whose start
date is after the run date is `next`, never current (the trap of future versions).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import asdict, dataclass, field

UNCHANGED = "unchanged"
NEW_IN_FORCE = "new_in_force"
NEW_FUTURE = "new_future"
REPEALED = "repealed"
FETCH_FAILED = "fetch_failed"
BLOCKED_403 = "blocked_403"
PARSE_FAILED = "parse_failed"
STALE_FALLBACK = "stale_fallback"

STATUSES = (UNCHANGED, NEW_IN_FORCE, NEW_FUTURE, REPEALED, FETCH_FAILED, BLOCKED_403, PARSE_FAILED,
            STALE_FALLBACK)
# An act with one of these statuses was NOT checked in this run.
UNVERIFIED = (FETCH_FAILED, BLOCKED_403, PARSE_FAILED, STALE_FALLBACK)
FAILURES = (FETCH_FAILED, BLOCKED_403, PARSE_FAILED)

SCAN_COMPLETE = "complete"
SCAN_STATUSES = (SCAN_COMPLETE, FETCH_FAILED, BLOCKED_403, PARSE_FAILED)


class ContractError(ValueError):
    """A result breaks the contract: a bug in an adapter, not a status of an act."""


@dataclass
class Redaction:
    label: str
    in_force_from: str | None          # ISO date
    doc_id: str | None = None


@dataclass
class Evidence:
    url: str
    fetched_at: str
    sha256: str | None = None          # SHA-256 of the normalised page text
    http_status: int | None = None
    parser: str | None = None          # which parsing path matched (for calibration)
    parser_calibrated: bool = False    # the parser was checked against a live page of the source
    # engine that fetched the page: urllib | playwright | command | firecrawl | host | fixture
    via: str | None = None


@dataclass
class AdapterResult:
    act_id: str
    adapter: str
    status: str
    current: Redaction | None = None
    next: Redaction | None = None
    evidence: Evidence | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    # Identifiers of amending acts and corrigenda the source lists (Cellar); None when the reader has none.
    related: list[str] | None = None

    def validate(self) -> "AdapterResult":
        if self.status not in STATUSES:
            raise ContractError(f"{self.act_id}: unknown status {self.status!r}")
        if self.status in FAILURES and not self.error:
            raise ContractError(f"{self.act_id}: status {self.status} without error")
        if self.status == UNCHANGED:
            if self.error:
                raise ContractError(f"{self.act_id}: unchanged with error {self.error!r}")
            if self.evidence is None or not self.evidence.sha256:
                raise ContractError(f"{self.act_id}: unchanged without snapshot sha256")
            if self.current is None or not self.current.in_force_from:
                raise ContractError(f"{self.act_id}: unchanged without parsed current version")
        if self.status == NEW_FUTURE and self.next is None:
            raise ContractError(f"{self.act_id}: new_future without next")
        return self

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)


@dataclass
class Edition:
    edition_id: int
    number: str | None
    date: str | None
    url: str
    sha256: str | None = None
    items: int = 0


@dataclass
class Signal:
    act_id: str
    edition_id: int
    edition_number: str | None
    edition_date: str | None
    item: str                           # the table-of-contents line of the issue
    matched: str                        # what matched
    url: str


@dataclass
class SourceScan:
    source: str
    status: str                         # SCAN_STATUSES
    checked_through: int | None         # last issue checked without gaps
    previous_checked_through: int | None
    latest_seen: int | None
    editions: list[Edition] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    evidence: Evidence | None = None
    error: str | None = None

    def validate(self) -> "SourceScan":
        if self.status not in SCAN_STATUSES:
            raise ContractError(f"{self.source}: unknown scan status {self.status!r}")
        if self.status != SCAN_COMPLETE and not self.error:
            raise ContractError(f"{self.source}: scan {self.status} without error")
        if self.status == SCAN_COMPLETE and self.error:
            raise ContractError(f"{self.source}: complete scan with error")
        if (self.checked_through is not None and self.previous_checked_through is not None
                and self.checked_through < self.previous_checked_through):
            raise ContractError(f"{self.source}: checked_through moved backwards")
        return self

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)


# ---------------------------------------------------------------- helpers

def text_sha256(text: str) -> str:
    """Hash of the text with whitespace collapsed: layout noise must not look like a change."""
    norm = re.sub(r"\s+", " ", text or "").strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def norm_label(label: str | None) -> str:
    return re.sub(r"\s+", "", (label or "")).lower()


def parse_date(s: str | None) -> _dt.date | None:
    """ISO `YYYY-MM-DD`, `DD.MM.YYYY`, `DD.MM.YY`, `DD-MM-YYYY`, `DD/MM/YYYY` → date; anything else → None."""
    if not s:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})", s)
        if not m:
            return None
        d, mo, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(yy) + 2000 if len(yy) == 2 else int(yy)
    try:
        return _dt.date(y, mo, d)
    except ValueError:
        return None


def act_number_year(act: dict) -> tuple[str, str] | None:
    """Number and year of an act: explicit `number`/`year` fields first, else the tail of the id (`…-53-2003`)."""
    if act.get("number") and act.get("year"):
        return str(act["number"]), str(act["year"])
    m = re.search(r"(\d+)-(\d{4})$", str(act.get("id") or ""))
    return (m.group(1), m.group(2)) if m else None


def classify(*, act: dict, parsed: list[Redaction], today: _dt.date, repealed: bool,
             repealed_label: str | None = None) -> tuple[str, Redaction | None, Redaction | None, str | None, list[str]]:
    """Compare the versions read on the page with the baseline held for the act.

    `act["current"]` / `act["next"]` are the baseline (`label`, `in_force_from`). Returns
    (status, current, next, error, notes). The version in force is the latest with a start date on or before
    `today`; the next one is the nearest after `today`, kept apart and never treated as in force.
    """
    notes: list[str] = []
    if repealed:
        return REPEALED, Redaction(label=repealed_label or "repealed", in_force_from=None), None, None, notes

    dated = [(parse_date(r.in_force_from), r) for r in parsed]
    dated = [(d, r) for d, r in dated if d is not None]
    if not dated:
        return PARSE_FAILED, None, None, "no version with a readable start date", notes

    in_force = [(d, r) for d, r in dated if d <= today]
    future = sorted([(d, r) for d, r in dated if d > today], key=lambda x: x[0])
    if not in_force:
        return PARSE_FAILED, None, (future[0][1] if future else None), \
            "no version in force on or before the run date", notes
    cur_d, cur = max(in_force, key=lambda x: x[0])
    nxt = future[0][1] if future else None

    reg_cur = act.get("current") or {}
    reg_next = act.get("next") or {}
    reg_d = parse_date(reg_cur.get("in_force_from"))

    same = False
    if reg_d is None and reg_cur.get("label") and norm_label(reg_cur.get("label")) == norm_label(cur.label):
        # A label decides only when the held version has no date: labels can stay the same across versions
        # ("forma de bază", a hand-written card), so a date always wins over a label.
        same = True
    elif reg_d is not None and reg_d == cur_d:
        # Same start date = same version. Readers label versions differently (an amending act, a consolidation
        # date, a hand-written card): a label difference alone must never confirm a change.
        same = True
        if norm_label(reg_cur.get("label")) != norm_label(cur.label):
            notes.append(f"same start date {cur_d}, label differs: held {reg_cur.get('label')!r}, "
                         f"page {cur.label!r}")

    if not same:
        if reg_d is None:
            notes.append("baseline absent: no version held for this act yet")
            return NEW_IN_FORCE, cur, nxt, None, notes
        if cur_d > reg_d:
            return NEW_IN_FORCE, cur, nxt, None, notes
        # The page shows an older version than the one held: never "unchanged".
        return PARSE_FAILED, cur, nxt, (f"page version in force {cur_d} is older than the held {reg_d}: "
                                        "wrong page, wrong document id or an incomplete page"), notes

    reg_next_d = parse_date(reg_next.get("in_force_from"))
    if reg_next_d is not None and reg_next_d <= today:
        # The held next version should have started, yet the page still shows the old one: either it was
        # postponed or the page lags. Never confirm a version the page does not show: not verified, by hand.
        return PARSE_FAILED, cur, nxt, (f"the held next version ({reg_next_d}) should be in force, but the page "
                                        f"still shows {cur_d}: postponed or not yet consolidated; check by hand"), notes

    if nxt is not None:
        if reg_next_d != parse_date(nxt.in_force_from):
            return NEW_FUTURE, cur, nxt, None, notes
        notes.append("future version already known")
    return UNCHANGED, cur, nxt, None, notes

