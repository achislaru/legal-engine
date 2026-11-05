"""eurlex: EU acts and their consolidations on EUR-Lex, by CELEX or ELI.

Input: an act record with a source `{"kind": "eurlex", "celex": "32016R0679"}` (also accepted: `doc_id`
«CELEX 32016R0679» or a `url` with CELEX:/ELI). Output: `contract.AdapterResult`.

Page: https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:<celex> (the "Document information" tab; the
interface language is fixed to EN so that parsing does not depend on the locale).

Checked on live pages (a directive with several consolidations, GDPR, a base-form directive, a repealed directive,
a regulation with a future date of application), so PARSER_CALIBRATED = True:
- `<p class="forceIndicator">`: «In force…» / «No longer in force, Date of end of validity: DD/MM/YYYY; Repealed by
  …» → repealed; no indicator → parse_failed;
- consolidations `data-celex="0<year><type><number>-YYYYMMDD"`: every date is a version «consolidare DD.MM.YYYY»;
  a date after the run date is a future version;
- no consolidations → «forma de bază» from the first «Date of effect»;
- «Date of effect … Application» and «Date of transposition … Application» after the run date → a future version
  «aplicare DD.MM.YYYY» → `new_future`, never `new_in_force`;
- «Date of end of validity» after the run date, not «Partial» → a future version «sfârșitul valabilității».
EUR-Lex updates its "Current consolidated version" label late: when it disagrees with the rule "latest on or before
the run date", the rule wins and the difference goes to the notes.

EUR-Lex sits behind AWS WAF: a plain client gets HTTP 202 with an empty body. A 202 with an empty or short body is
reported as blocked_403 ("AWS WAF challenge"); the challenge is never bypassed.

Fallback: on blocked_403 / fetch_failed the same act is read from Cellar, the Publications Office repository
EUR-Lex is built from (`cellar.py`: SPARQL metadata + the text). The Cellar answer is used only when it is a
checked status (unchanged / new_* / repealed); otherwise the EUR-Lex failure stays and the Cellar outcome goes to
the notes.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re

from ..contract import (BLOCKED_403, FETCH_FAILED, NEW_FUTURE, NEW_IN_FORCE, PARSE_FAILED, REPEALED, UNCHANGED,
                        AdapterResult, Evidence, Redaction, classify, parse_date, text_sha256)
from ..fetchers import Fetcher, shown_title

ADAPTER = "eurlex"
PARSER_ID = "eurlex/all-v1"
PARSER_CALIBRATED = True
PAGE_URL = "https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:{celex}"
MIN_TEXT_CHARS = 2000
ELI_TYPE = {"reg": "R", "dir": "L", "dec": "D"}

CELEX_RE = re.compile(r"\b(?P<celex>3\d{4}[A-Z]\d{4})\b")
ELI_RE = re.compile(r"/eli/(?P<t>reg|dir|dec)/(?P<y>\d{4})/(?P<n>\d+)")
FORCE_RE = re.compile(r'<p\b[^>]*class="forceIndicator"[^>]*>(?P<t>.*?)</p>', re.S)
DL_PAIR_RE = re.compile(r"<dt\b[^>]*>(?P<dt>.*?)</dt>\s*<dd\b[^>]*>(?P<dd>.*?)</dd>", re.S)
DMY = r"(?P<date>\d{2}/\d{2}/\d{4})"


def _strip(s: str) -> str:
    s = re.sub(r"(?s)<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _dmy(s: str) -> _dt.date | None:
    return parse_date(s.replace("/", ".")) if s else None


def celex_of(act: dict) -> str | None:
    """CELEX of the base act (a consolidated CELEX «0…-YYYYMMDD» is not accepted: it names one version)."""
    for s in act.get("sources") or []:
        if s.get("kind") != "eurlex":
            continue
        for cand in (str(s.get("celex") or ""), str(s.get("doc_id") or ""), str(s.get("url") or "")):
            m = CELEX_RE.search(cand)
            if m:
                return m.group("celex")
        m = ELI_RE.search(str(s.get("url") or ""))
        if m:
            return f"3{m.group('y')}{ELI_TYPE[m.group('t')]}{int(m.group('n')):04d}"
    return None


def year_number(celex: str) -> tuple[str, str]:
    return celex[1:5], str(int(celex[6:10]))


def identifies_act(celex: str, title: str, html: str) -> bool:
    year, num = year_number(celex)
    if re.search(rf"(?<![\d/]){year}/{num}(?!\d)", title or ""):
        return True
    return bool(re.search(rf"data\.europa\.eu/eli/(?:reg|dir|dec)/{year}/{num}/oj", html or ""))


def parse_eurlex(html: str, celex: str, today: _dt.date) -> dict:
    """→ {force, repealed, repealed_label, eurlex_current, effects, redactions, mode, notes}."""
    out = {"force": None, "repealed": False, "repealed_label": None, "eurlex_current": None,
           "redactions": [], "mode": "none", "notes": [], "effects": []}
    fm = FORCE_RE.search(html or "")
    if not fm:
        return out
    force = _strip(fm.group("t"))
    out["force"] = force
    if force.lower().startswith("no longer in force"):
        m = re.search(r"end of validity:\s*" + DMY, force)
        by = re.search(r"Repealed by\s+(\S+)", force)
        out["repealed"] = True
        out["repealed_label"] = (f"abrogat{' de ' + by.group(1) if by else ''}"
                                 f"{' (sfârșitul valabilității ' + m.group('date').replace('/', '.') + ')' if m else ''}")
        out["mode"] = "no-longer-in-force"
        return out
    if not force.lower().startswith("in force"):
        return out
    m = re.search(r"Current consolidated version:\s*" + DMY, force)
    out["eurlex_current"] = _dmy(m.group("date")) if m else None

    prefix = "0" + celex[1:]
    cons: dict[str, Redaction] = {}
    for cm in re.finditer(rf'data-celex="{prefix}-(?P<d>\d{{8}})"', html):
        try:
            d = _dt.datetime.strptime(cm.group("d"), "%Y%m%d").date()
        except ValueError:
            continue
        cons.setdefault(d.isoformat(), Redaction(label=f"consolidare {d:%d.%m.%Y}", in_force_from=d.isoformat(),
                                                 doc_id=f"{prefix}-{cm.group('d')}"))

    effects, future = [], []
    for pm in DL_PAIR_RE.finditer(html):
        dt_ = _strip(pm.group("dt")).rstrip(": ").lower()
        dd = _strip(pm.group("dd"))
        dm = re.match(DMY, dd)
        d = _dmy(dm.group("date")) if dm else None
        if d is None:
            continue
        note = dd[dm.end():].strip(" ;")
        if dt_ == "date of effect":
            effects.append(d)
        if dt_ in ("date of effect", "date of transposition") and "application" in note.lower() and d > today:
            future.append(Redaction(label=f"aplicare {d:%d.%m.%Y} ({dt_}; {note})"[:200],
                                    in_force_from=d.isoformat()))
        if dt_ == "date of end of validity" and d > today and "partial" not in note.lower():
            future.append(Redaction(label=f"sfârșitul valabilității {d:%d.%m.%Y} ({note})"[:200],
                                    in_force_from=d.isoformat()))

    out["effects"] = sorted(d.isoformat() for d in effects)
    if cons:
        out["redactions"] = list(cons.values()) + future
        out["mode"] = "consolidations"
        in_force = sorted(d for d in cons if _dt.date.fromisoformat(d) <= today)
        if out["eurlex_current"] and in_force and in_force[-1] != out["eurlex_current"].isoformat():
            out["notes"].append(f"EUR-Lex label 'Current consolidated version' = {out['eurlex_current']}, "
                                f"newest listed consolidation on or before today = {in_force[-1]}")
    elif effects:
        base = min(effects)
        out["redactions"] = [Redaction(label="forma de bază", in_force_from=base.isoformat(),
                                       doc_id=celex)] + future
        out["mode"] = "base-form"
    else:
        out["redactions"] = future
        out["mode"] = "future-only" if future else "none"
    return out


def fold_preeffect_consolidation(p: dict, act: dict, celex: str) -> None:
    """A "consolidation" dated BEFORE the act took effect is the original text: fold it into the base form.

    EUR-Lex keeps, for some acts, a consolidation dated on the publication day while the date of effect is weeks
    later. If the baseline holds the act as «forma de bază» from the date of effect, the rule "latest on or before
    today" would pick the pre-effect consolidation, older than the baseline, and give parse_failed on every run.
    Folded only when the baseline itself holds the act as the base form from that date; acts tracked by a
    consolidation label are left as they are.
    """
    if p.get("mode") != "consolidations" or not p.get("effects"):
        return
    cur = act.get("current") or {}
    base = _dt.date.fromisoformat(p["effects"][0])
    if "forma de bază" not in str(cur.get("label") or "").lower() or parse_date(cur.get("in_force_from")) != base:
        return
    cons = [r for r in p["redactions"] if str(r.label).startswith("consolidare ")]
    pre = [r for r in cons if _dt.date.fromisoformat(r.in_force_from) < base]
    if not pre:
        return
    rest = [r for r in p["redactions"] if r not in pre]
    p["notes"].append(f"consolidation(s) {', '.join(r.in_force_from for r in pre)} predate the date of effect "
                      f"{base} — folded into the base text (forma de bază)")
    if len(pre) == len(cons):
        rest = [Redaction(label="forma de bază", in_force_from=base.isoformat(), doc_id=celex)] + rest
        p["mode"] = "base-form(pre-effect-consolidation)"
    p["redactions"] = rest


def check_act(act: dict, fetcher: Fetcher, today: _dt.date, *, cellar_get=None,
              cellar_fallback: bool = True) -> AdapterResult:
    """EUR-Lex; on a WAF block or a failure, Cellar. `cellar_get` replaces Cellar's HTTP getter (tests)."""
    res = check_page(act, fetcher, today)
    if not cellar_fallback or res.status not in (BLOCKED_403, FETCH_FAILED) or celex_of(act) is None:
        return res
    from . import cellar   # imported here: cellar imports this module
    cres = cellar.check_act(act, today, get=cellar_get, primary_error=res.error)
    if cres.status in (UNCHANGED, NEW_IN_FORCE, NEW_FUTURE, REPEALED):
        return cres
    res.notes.append(f"cellar fallback: {cres.status}: {cres.error}")
    return res.validate()


def check_page(act: dict, fetcher: Fetcher, today: _dt.date) -> AdapterResult:
    act_id = act["id"]
    celex = celex_of(act)
    if celex is None:
        return AdapterResult(act_id=act_id, adapter=ADAPTER, status=FETCH_FAILED,
                             error="act has no eurlex source with a CELEX or ELI").validate()
    url = PAGE_URL.format(celex=celex)
    r = fetcher.get(url)
    ev = Evidence(url=url, fetched_at=r.fetched_at, http_status=r.status,
                  sha256=text_sha256(r.text) if r.text else None, parser=None,
                  parser_calibrated=PARSER_CALIBRATED, via=r.via)

    def fail(status, err):
        return AdapterResult(act_id=act_id, adapter=ADAPTER, status=status, evidence=ev,
                             error=err, notes=list(r.notes)).validate()

    if r.error:
        return fail(FETCH_FAILED, r.error)
    if r.blocked:
        return fail(BLOCKED_403, f"{r.blocked_reason}; page title {shown_title(r)}; "
                                 "anti-bot check not bypassed (by design)")
    if r.status == 202 and len(r.text or "") < MIN_TEXT_CHARS:
        return fail(BLOCKED_403, f"AWS WAF challenge: HTTP 202 with {len(r.text or '')}-char body; "
                                 "not bypassed (by design)")
    if r.status is None or r.status >= 400:
        return fail(FETCH_FAILED, f"HTTP {r.status}")
    if r.markdown and not r.html:
        # The parser reads EUR-Lex markup (forceIndicator, data-celex), which markdown drops. Reported as a
        # fetch failure, not a parse failure: the page in the needed form was not obtained, and Cellar may still
        # answer.
        return fail(FETCH_FAILED, "the engine returned markdown, not the page HTML the EUR-Lex parser needs")
    if len(r.text or "") < MIN_TEXT_CHARS:
        return fail(PARSE_FAILED, f"page text too short ({len(r.text or '')} chars): empty or truncated")
    if not identifies_act(celex, r.title, r.html):
        return fail(PARSE_FAILED, f"page does not identify {celex} (title {shown_title(r)})")

    p = parse_eurlex(r.html, celex, today)
    fold_preeffect_consolidation(p, act, celex)
    ev.parser = f"{PARSER_ID}:{p['mode']}"
    if p["force"] is None:
        return fail(PARSE_FAILED, "no legal-status indicator (forceIndicator) on page")
    if not p["repealed"] and not p["redactions"]:
        return fail(PARSE_FAILED, f"no consolidation or date of effect found (status {p['force'][:80]!r})")
    status, cur, nxt, err, notes = classify(act=act, parsed=p["redactions"], today=today,
                                            repealed=p["repealed"], repealed_label=p["repealed_label"])
    notes = p["notes"] + list(r.notes) + notes
    if r.status == 202:
        notes.append("main document answered HTTP 202 (AWS WAF) but full page body was delivered")
    return AdapterResult(act_id=act_id, adapter=ADAPTER, status=status, current=cur, next=nxt,
                         evidence=ev, error=err, notes=notes).validate()
