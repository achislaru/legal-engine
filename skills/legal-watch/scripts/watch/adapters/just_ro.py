"""just_ro: the Romanian legislative portal (legislatie.just.ro).

Input: an act record with a source `{"kind": "just_ro", "doc_id": …}`. Output: `contract.AdapterResult`.
The version rule is the same as for legis_md: the version in force is the latest with a start date on or before
the run date; a later one is `next`, never in force.

The HTML parser (`parse_just_html`) was checked against the portal's real markup, but only through Wayback `id_`
copies (the portal's bytes, unchanged): consolidated acts, a republished act with consolidations, and acts in
their base form. The live portal did not answer automated requests at the time (HTTP/2 protocol errors), so
PARSER_CALIBRATED stays False until one live page passes the same parser.

What is read:
- the heading `<span class="S_DEN">ORDONANȚĂ DE URGENȚĂ nr. 34 din 4 iunie 2014</span>`: it must match the act's
  number and year, else parse_failed;
- codes: a code page names the code and its date, not the approving law («COD FISCAL 08/09/2015», «CODUL FISCAL din
  8 septembrie 2015»). For an act with `code`, the page is identified ONLY by the code name + date from
  CODE_PAGES; the law number does not count, because the page of the approving law («LEGE 227 08/09/2015») has
  no consolidations and would give a false "unchanged". A code missing from CODE_PAGES gives parse_failed;
- `<span class="S_PUB_BDY">MONITORUL OFICIAL nr. 236 din 26 martie 2026</span>`: the date of the base form;
- the consolidation history: `<a title="Consolidarea din DD.MM.YYYY" … href="…/DetaliiDocument/N">` (the one shown
  now has no href). With consolidations, versions = consolidations;
- without consolidations (base form): «forma de bază, MO nr. … din …» plus deferred application dates from the
  text («se aplică începând cu data de 27 septembrie 2026»);
- in every case future dates from «se aplică … data de …» and from notes «(la DD-MM-YYYY, …)» are future versions
  (`new_future`, never `new_in_force`);
- repeal: the note «(la DD-MM-YYYY, Actul a fost abrogat de …)»; on or before the run date → repealed, later → a
  future version «abrogare …». This note format was never seen on a live page (synthetic fixture).

Markdown pages (an engine that returned markdown and no HTML: a user `command` engine, or the `firecrawl` engine if
its site table is switched to markdown for just.ro; by default it asks for raw HTML) go through `parse_just_markdown`;
it was never checked against a live page (no live just.ro page was obtained as markdown), so it is not calibrated.

Any doubt gives parse_failed, fetch_failed or blocked_403, never unchanged. Anti-bot pages are never bypassed.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re
from dataclasses import dataclass, field

from ..contract import (BLOCKED_403, FETCH_FAILED, PARSE_FAILED, AdapterResult, Evidence, Redaction,
                        act_number_year, classify, parse_date, text_sha256)
from ..fetchers import Fetcher, FetchResult
from .common import is_markdown, page_text, source_doc_id

ADAPTER = "just_ro"
PARSER_ID = "just_ro/html-v1"
PARSER_CALIBRATED = False        # checked on Wayback id_ copies only; the live portal did not answer
PARSER_ID_MD = "just_ro/markdown-v1"
PARSER_CALIBRATED_MD = False     # no live just.ro page was ever obtained as markdown
PAGE_URL = "https://legislatie.just.ro/Public/DetaliiDocument/{doc_id}"
MIN_TEXT_CHARS = 2000

MONTHS = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
          "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11,
          "decembrie": 12}
_MON = "|".join(MONTHS)
_MONTH_NAME = {v: k for k, v in MONTHS.items()}

# Code pages: the portal names the code and its date, not «Legea nr. N/YYYY».
# act["code"] → (code name as a regex, date of the code). Checked on Wayback id_ copies:
#   fiscal — <title> «COD FISCAL 08/09/2015», S_DEN «CODUL FISCAL din 8 septembrie 2015» (Legea nr. 227/2015);
#   muncii — <title> «CODUL MUNCII 24/01/2003», S_DEN «CODUL MUNCII din 24 ianuarie 2003 (**republicat**)»
#            (Legea nr. 53/2003).
CODE_PAGES: dict[str, tuple[str, _dt.date]] = {
    "fiscal": (r"COD(?:UL)?\s+FISCAL", _dt.date(2015, 9, 8)),
    "muncii": (r"COD(?:UL)?\s+MUNCII", _dt.date(2003, 1, 24)),
}

S_DEN_RE = re.compile(r'<span class="S_DEN">(?P<t>.*?)</span>', re.S)
S_PUB_RE = re.compile(r'<span class="S_PUB_BDY">(?P<t>.*?)</span>', re.S)
# Either quote: a browser serialises attributes as "…", the portal's raw bytes (and Wayback id_ copies) use '…'.
CONS_RE = re.compile(r'<a\b(?P<attrs>[^>]*\btitle=(?P<q>["\'])Consolidarea din (?P<d>\d{2}\.\d{2}\.\d{4})(?P=q)[^>]*)>')
HREF_DOC_RE = re.compile(r'href=(?P<q>["\'])[^"\']*DetaliiDocument(?:Afis)?/(?P<id>\d+)(?P=q)')
PUB_RE = re.compile(rf"nr\.\s*(?P<nr>[\d\-]+(?:\s*bis)?)\s+din\s+(?P<d>\d{{1,2}})\s+(?P<m>{_MON})\s+(?P<y>\d{{4}})",
                    re.I)
APPLY_RE = re.compile(rf"se\s+aplic[ăa]\s+(?:[îi]ncep[âa]nd\s+)?(?:cu|de\s+la)\s+data\s+de\s+"
                      rf"(?P<d>\d{{1,2}})\s+(?P<m>{_MON})\s+(?P<y>\d{{4}})", re.I)
NOTE_RE = re.compile(r"\(la\s+(?P<d>\d{2}-\d{2}-\d{4})\s*,\s*(?P<body>[^()]{0,400})")
REPEAL_NOTE_RE = re.compile(r"\(la\s+(?P<d>\d{2}-\d{2}-\d{4})\s*,\s*Actul\s+a\s+fost\s+abrogat\s+de\s+"
                            r"(?P<by>[^()\n]{0,200})", re.I)

# Markdown page patterns (uncalibrated, see the module docstring).
_ACT_KIND = (r"(?:LEGE[A]?|ORDONAN[ȚŢT][ĂA](?:\s+DE\s+URGEN[ȚŢT][ĂA])?|HOT[ĂA]R[ÂA]RE[A]?|DECRET(?:UL)?|"
             r"DECIZI[AE]|ORDIN(?:UL)?)")
MD_HEADING_RE = re.compile(rf"(?m)^[#*_\s]*(?P<t>{_ACT_KIND}\s+nr\.\s*\d+\s+din\s+\d{{1,2}}\s+(?:{_MON})\s+\d{{4}}"
                           r"[^\n]{0,60})", re.I)
MD_CODE_HEADING_RE = re.compile(rf"(?m)^[#*_\s]*(?P<t>COD(?:UL)?\s+[A-ZĂÂÎȘȚ ]{{3,40}}?\s+din\s+\d{{1,2}}\s+(?:{_MON})"
                                r"\s+\d{4}[^\n]{0,40})", re.I)
MD_PUB_RE = re.compile(rf"(?P<t>MONITORUL\s+OFICIAL\s+(?:al\s+Rom[âa]niei[^\n]{{0,20}}?)?nr\.\s*[\d\-]+(?:\s*bis)?\s+din\s+"
                       rf"\d{{1,2}}\s+(?:{_MON})\s+\d{{4}})", re.I)
# [20.07.2022](https://legislatie.just.ro/Public/DetaliiDocument/257047 "Consolidarea din 20.07.2022")
MD_CONS_LINK_RE = re.compile(r"\[(?P<d>\d{2}\.\d{2}\.\d{4})\]\((?P<href>[^)\s]*DetaliiDocument(?:Afis)?/(?P<id>\d+)[^)\s]*)"
                             r"(?:\s+\"[^\"]*\")?\)")
MD_SHOWN_RE = re.compile(r"(?:Forma\s+consolidat[ăa]\s+valabil[ăa]\s+la|Consolidarea\s+din)\s*:?\s*"
                         r"(?P<d>\d{2}\.\d{2}\.\d{4})", re.I)
MD_DATE_RE = re.compile(r"(?<![\d.\[])(?P<d>\d{2}\.\d{2}\.\d{4})(?![\d\]])")
MODIFIER_RE = re.compile(r"\b(?:modificat|completat|abrogat|rectificat|republicat)[ăa]?\s+(?:de|prin)\s+"
                         r"(?:[^()\n]{0,80}?\bdin\s+)?"            # «Punctul 1, Articolul III din …»
                         r"(?P<act>(?:LEGEA|Legea|Lege|ORDONAN[ȚŢ]A\s+DE\s+URGEN[ȚŢ][ĂA]|Ordonan[țţ]a\s+de\s+urgen[țţ][ăa]|"
                         r"OUG|ORDONAN[ȚŢ]A|Ordonan[țţ]a|OG|HOT[ĂA]R[ÂA]REA|Hot[ăa]r[âa]rea|HG|DECIZIA|Decizia|"
                         r"RECTIFICAREA|Rectificarea|ORDINUL|Ordinul)\s+(?:nr\.\s*)?\d+[^,;()\n]{0,60})")


def _ro_date(d: str, m: str, y: str) -> _dt.date | None:
    try:
        return _dt.date(int(y), MONTHS[m.lower()], int(d))
    except (KeyError, ValueError):
        return None


def _strip(s: str) -> str:
    s = re.sub(r"(?s)<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def page_source(act: dict) -> tuple[str | None, str | None]:
    doc_id = source_doc_id(act, "just_ro")
    return (doc_id, PAGE_URL.format(doc_id=doc_id)) if doc_id else (None, None)


@dataclass
class JustPage:
    heading: str | None = None                  # S_DEN
    publication: str | None = None              # S_PUB_BDY
    redactions: list[Redaction] = field(default_factory=list)
    repealed: bool = False
    repealed_by: str | None = None
    mode: str = "none"
    displayed: str | None = None                # the consolidation the page shows (it has no href)
    notes: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)  # amending acts named on the page


def identifies_code_page(code: str, title: str, heading: str | None) -> bool:
    if code not in CODE_PAGES:
        return False
    name, d = CODE_PAGES[code]
    if heading and re.match(rf"\s*{name}\s+din\s+{d.day}\s+{_MONTH_NAME[d.month]}\s+{d.year}\b",
                            heading, re.I):
        return True
    # <title>COD FISCAL               08/09/2015 - Portal Legislativ</title>
    return bool(re.match(rf"\s*{name}\s+{d:%d/%m/%Y}\b", title or "", re.I))


def identifies_act(act: dict, title: str, heading: str | None) -> bool:
    if act.get("code"):                 # code name + date only; the law number does not count
        return identifies_code_page(str(act["code"]), title, heading)
    ny = act_number_year(act)
    if ny is None:
        return False                     # nothing to check the page against
    num, year = ny
    if heading and re.search(rf"\bnr\.\s*{num}\s+din\s+\d{{1,2}}\s+\w+\s+{year}\b", heading, re.I):
        return True
    # <title>OUG 34 04/06/2014 - Portal Legislativ</title>
    return bool(re.search(rf"(?<!\d){num}\s+\d{{2}}/\d{{2}}/{year}\b", title or ""))


def modifying_acts(body: str, limit: int = 40) -> list[str]:
    """Amending acts named in the page text («modificat de LEGEA nr. 1 din …»), without repeats."""
    out: list[str] = []
    for m in MODIFIER_RE.finditer(body or ""):
        a = re.sub(r"\s+", " ", m.group("act")).strip(" .,")
        a = re.sub(r"\s*,?\s*publicat[ăa]?\b.*$", "", a).strip(" .,")
        if a not in out:
            out.append(a)
        if len(out) >= limit:
            break
    return out


def parse_just_html(html: str, text: str, doc_id: str | None, today: _dt.date) -> JustPage:
    p = JustPage()
    m = S_DEN_RE.search(html or "")
    p.heading = _strip(m.group("t")) if m else None
    m = S_PUB_RE.search(html or "")
    p.publication = _strip(m.group("t")) if m else None
    cons_raw = []
    for cm in CONS_RE.finditer(html or ""):
        hm = HREF_DOC_RE.search(cm.group("attrs"))
        cons_raw.append((cm.group("d"), hm.group("id") if hm else None))
    return _finish(p, text or "", cons_raw, doc_id, today)


def parse_just_markdown(md: str, text: str, doc_id: str | None, today: _dt.date) -> JustPage:
    p = JustPage()
    head_zone = (text or "")[:20000]
    m = MD_HEADING_RE.search(head_zone) or MD_CODE_HEADING_RE.search(head_zone)
    p.heading = re.sub(r"[*_]+", "", m.group("t")).strip() if m else None
    m = MD_PUB_RE.search(head_zone)
    p.publication = re.sub(r"\s+", " ", m.group("t")).strip() if m else None
    cons_raw: list[tuple[str, str | None]] = []
    links = list(MD_CONS_LINK_RE.finditer(md or ""))
    for lm in links:
        cons_raw.append((lm.group("d"), lm.group("id")))
    for sm in MD_SHOWN_RE.finditer(md or ""):
        cons_raw.insert(0, (sm.group("d"), None))
    if links:
        # The shown consolidation is the date WITHOUT a link next to the list (in HTML it has no href).
        hist = (md or "").rfind("istoric consolid", 0, links[0].start())
        a = hist if 0 <= hist and links[0].start() - hist < 600 else max(0, links[0].start() - 200)
        b = links[-1].end()
        seg = MD_CONS_LINK_RE.sub(" ", (md or "")[a:b])
        for dm in MD_DATE_RE.finditer(seg):
            cons_raw.insert(0, (dm.group("d"), None))
    return _finish(p, text or "", cons_raw, doc_id, today)


def _finish(p: JustPage, body: str, cons_raw: list[tuple[str, str | None]], doc_id: str | None,
            today: _dt.date) -> JustPage:
    """The part shared by the HTML and markdown parsers: repeal, consolidations, future dates, base form.

    cons_raw — [(«DD.MM.YYYY», consolidation doc_id | None = the one shown now)].
    """
    p.modifiers = modifying_acts(body)
    future: list[Redaction] = []
    for rm in REPEAL_NOTE_RE.finditer(body):
        d = parse_date(rm.group("d"))
        if d is None:
            continue
        by = re.sub(r"\s+", " ", rm.group("by")).strip(" ,.;")
        if d <= today:
            p.repealed, p.repealed_by, p.mode = True, f"abrogat de {by} (la {d.isoformat()})", "repeal-note"
            return p
        future.append(Redaction(label=f"abrogare de la {d:%d.%m.%Y} ({by})", in_force_from=d.isoformat()))

    cons: list[Redaction] = []
    seen: set[str] = set()
    for ds, href_id in cons_raw:
        d = parse_date(ds)
        if d is None or d.isoformat() in seen:
            continue
        seen.add(d.isoformat())
        r = Redaction(label=f"consolidare {d:%d.%m.%Y}", in_force_from=d.isoformat(), doc_id=href_id or doc_id)
        if href_id is None:
            p.displayed = r.label
        cons.append(r)

    applies = []
    for am in APPLY_RE.finditer(body):
        d = _ro_date(am.group("d"), am.group("m"), am.group("y"))
        if d is not None:
            applies.append(d)
    for d in sorted(set(applies)):
        if d > today:
            future.append(Redaction(label=f"aplicare de la {d:%d.%m.%Y}", in_force_from=d.isoformat()))
    for nm in NOTE_RE.finditer(body):
        d = parse_date(nm.group("d"))
        if d is not None and d > today and not any(f.in_force_from == d.isoformat() for f in future):
            future.append(Redaction(label=f"modificare de la {d:%d.%m.%Y} (notă în text)",
                                    in_force_from=d.isoformat()))

    if cons:
        p.redactions = cons + future
        p.mode = "consolidations"
        cur_dates = [c.in_force_from for c in cons if parse_date(c.in_force_from) <= today]
        if p.displayed and cur_dates and p.displayed != f"consolidare {parse_date(max(cur_dates)):%d.%m.%Y}":
            p.notes.append(f"page displays {p.displayed}, newest listed in force is {max(cur_dates)}")
        shown = parse_date(p.displayed.split()[-1]) if p.displayed else None
        if shown and shown > today:
            p.notes.append(f"page displays a future form ({p.displayed}); in force = latest date on or before {today}")
        return p

    pm = PUB_RE.search(p.publication or "")
    base_d = _ro_date(pm.group("d"), pm.group("m"), pm.group("y")) if pm else None
    if base_d is None:
        p.redactions = future
        p.mode = "none" if not future else "future-only"
        return p
    reds = [Redaction(label=f"forma de bază, MO nr. {pm.group('nr')} din {base_d:%d.%m.%Y}",
                      in_force_from=base_d.isoformat(), doc_id=doc_id)]
    for d in sorted(set(applies)):
        if base_d < d <= today:
            reds.append(Redaction(label=f"aplicare de la {d:%d.%m.%Y}", in_force_from=d.isoformat()))
    p.redactions = reds + future
    p.mode = "base-form"
    return p


def result_from_fetch(act: dict, r: FetchResult, today: _dt.date, *, adapter: str, url: str,
                      doc_id: str | None, parser_id: str, calibrated: bool
                      ) -> tuple[AdapterResult | None, JustPage | None, Evidence]:
    """Shared by just_ro and wayback: a failure result, or the parsed page.

    → (failure result | None, parsed page | None, evidence).
    """
    act_id = act["id"]
    md = is_markdown(r)
    text = page_text(r)
    ev = Evidence(url=url, fetched_at=r.fetched_at, http_status=r.status,
                  sha256=text_sha256(text) if text else None, parser=None,
                  parser_calibrated=PARSER_CALIBRATED_MD if md else calibrated, via=r.via)

    def fail(status, err):
        return AdapterResult(act_id=act_id, adapter=adapter, status=status, evidence=ev, error=err,
                             notes=list(r.notes)).validate(), None, ev

    if r.error:
        return fail(FETCH_FAILED, r.error)
    if r.blocked:
        return fail(BLOCKED_403, f"{r.blocked_reason}; page title {r.title!r}; "
                                 "anti-bot check not bypassed (by design)")
    if r.status is None or r.status >= 400:
        return fail(FETCH_FAILED, f"HTTP {r.status}")
    if r.subresource_403 and len(text) < MIN_TEXT_CHARS:
        return fail(BLOCKED_403, f"body not delivered: 403 on {len(r.subresource_403)} subresource(s)")
    if len(text) < MIN_TEXT_CHARS:
        return fail(PARSE_FAILED, f"page text too short ({len(text)} chars): empty or truncated")
    if md:
        page, parser_id = parse_just_markdown(r.markdown, text, doc_id, today), PARSER_ID_MD
    else:
        page = parse_just_html(r.html, text, doc_id, today)
    ev.parser = f"{parser_id}:{page.mode}"
    if act.get("code") and str(act["code"]) not in CODE_PAGES:
        return fail(PARSE_FAILED, f"code {act['code']!r} has no known page name and date: the page cannot be "
                                  "identified (add it to CODE_PAGES after checking a live page)")
    if not act.get("code") and act_number_year(act) is None:
        return fail(PARSE_FAILED, f"{act_id} has no number/year: the page cannot be checked to be this act")
    if not identifies_act(act, r.title, page.heading):
        return fail(PARSE_FAILED, f"page does not identify {act_id} (title {r.title!r}, "
                                  f"heading {page.heading!r})")
    return None, page, ev


def check_act(act: dict, fetcher: Fetcher, today: _dt.date) -> AdapterResult:
    act_id = act["id"]
    doc_id, url = page_source(act)
    if url is None:
        return AdapterResult(act_id=act_id, adapter=ADAPTER, status=FETCH_FAILED,
                             error="act has no just_ro source with a doc_id").validate()
    r = fetcher.get(url)
    failed, page, ev = result_from_fetch(act, r, today, adapter=ADAPTER, url=url, doc_id=doc_id,
                                         parser_id=PARSER_ID, calibrated=PARSER_CALIBRATED)
    if failed is not None:
        return failed
    status, cur, nxt, err, notes = classify(act=act, parsed=page.redactions, today=today,
                                            repealed=page.repealed, repealed_label=page.repealed_by)
    notes = page.notes + notes + list(r.notes)
    if page.modifiers:
        notes.append("amending acts named on the page: " + "; ".join(page.modifiers[:15])
                     + (f" (+{len(page.modifiers) - 15})" if len(page.modifiers) > 15 else ""))
    if not ev.parser_calibrated:
        notes.append("just_ro markdown parser not calibrated: no live just.ro page was read as markdown"
                     if is_markdown(r) else
                     "parser calibrated on Wayback id_ copies of just.ro pages only, not on a live portal response")
    return AdapterResult(act_id=act_id, adapter=ADAPTER, status=status, current=cur, next=nxt,
                         evidence=ev, error=err, notes=notes).validate()
