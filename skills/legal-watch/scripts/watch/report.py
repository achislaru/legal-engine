"""The page a person opens to see the state of monitoring: `<profile>/laws/report.html`.

A local file (never published): open problems with what happened and what to do, sites that refuse an engine,
recently solved problems, and the law library (version held, when checked, how many copies of the text are
kept). Plain HTML without scripts; every value from the state, the log or a site is escaped, because an error
text or a page title comes from outside.
"""
from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path

from . import digest as _digest
from . import issues as _issues
from . import library as lib

# Labels of the reasons (`why`), the title and the health line come from the digest, so both say the same thing.
P = {
    "en": {
        "title": "Law monitoring: status and problems", "generated": "Updated", "last_run": "Last run",
        "open": "Open problems", "none_open": "No open problems.", "sites": "Sites that refuse an engine",
        "resolved": "Solved recently", "library": "Law library", "act": "Act", "what": "What happened",
        "since": "Since", "times": "Times", "agent": "What the agent will do", "you": "What you can do",
        "site": "Site", "engine": "Engine", "runs": "Runs in a row", "status": "Now", "tried_last": "tried last",
        "tried": "tried as usual", "held": "Version held", "next": "Next version", "checked": "Checked",
        "copies": "Text copies", "solved_on": "Solved", "how": "How", "detail": "Detail",
        "note": "This page lives only on your computer. \"Not verified\" never means \"no changes\".",
        "fix": {
            "blocked": ("read the official page with Firecrawl if connected, else in your browser, and record a "
                        "version card",
                        "connect Firecrawl (setup step `reading`), or allow the agent your browser"),
            "fetch_failed": ("try again next run; after 3 failures check the page by hand",
                             "nothing, unless the site is down for long"),
            "parse_failed": ("check the act by hand; if it repeats, save the page as a sample for the engine",
                             "report it to the engine's authors if the agent asks (you decide)"),
            "uncalibrated": ("check the act by hand until the reader of this site is calibrated",
                             "nothing"),
            "no_source": ("find the official page of the act and add it to the watchlist",
                          "confirm the page the agent found"),
            "stale_fallback": ("look for the current official text; an archived copy is not a check",
                               "nothing"),
            "reader_crashed": ("check the act by hand and keep the error for the engine's authors",
                               "report it to the engine's authors if the agent asks (you decide)"),
            "gazette_failed": ("scan the Official Gazette again next run", "nothing"),
            "_": ("check the act by hand", "nothing")}},
    "ro": {
        "title": "Monitorizarea legislației: stare și probleme", "generated": "Actualizat",
        "last_run": "Ultima rulare", "open": "Probleme deschise", "none_open": "Nicio problemă deschisă.",
        "sites": "Site-uri care refuză un motor", "resolved": "Rezolvate recent", "library": "Biblioteca de legi",
        "act": "Act", "what": "Ce s-a întâmplat", "since": "Din", "times": "De câte ori",
        "agent": "Ce va face agentul", "you": "Ce puteți face dvs.", "site": "Site", "engine": "Motor",
        "runs": "Rulări la rând", "status": "Acum", "tried_last": "încercat ultimul", "tried": "încercat obișnuit",
        "held": "Redacția deținută", "next": "Redacția următoare", "checked": "Verificat",
        "copies": "Copii ale textului", "solved_on": "Rezolvat", "how": "Cum", "detail": "Detalii",
        "note": "Pagina există doar pe calculatorul dvs. „Neverificat” nu înseamnă niciodată „fără modificări”.",
        "fix": {
            "blocked": ("citește pagina oficială prin Firecrawl, dacă e conectat, altfel în browserul dvs., și "
                        "înregistrează fișa redacției",
                        "conectați Firecrawl (pasul de configurare `reading`) sau permiteți agentului să folosească "
                        "browserul dvs."),
            "fetch_failed": ("reîncearcă la următoarea rulare; după 3 eșecuri verifică manual",
                             "nimic, dacă site-ul nu e căzut mult timp"),
            "parse_failed": ("verifică actul manual; dacă se repetă, salvează pagina ca model pentru motor",
                             "semnalați autorilor motorului dacă agentul propune (decideți dvs.)"),
            "uncalibrated": ("verifică actul manual până la calibrarea cititorului", "nimic"),
            "no_source": ("caută pagina oficială a actului și o adaugă în lista urmărită",
                          "confirmați pagina găsită de agent"),
            "stale_fallback": ("caută textul oficial actual; o copie arhivată nu e verificare", "nimic"),
            "reader_crashed": ("verifică actul manual și păstrează eroarea pentru autorii motorului",
                               "semnalați autorilor motorului dacă agentul propune (decideți dvs.)"),
            "gazette_failed": ("scanează din nou Monitorul Oficial la următoarea rulare", "nimic"),
            "_": ("verifică actul manual", "nimic")}},
    "ru": {
        "title": "Мониторинг законов: состояние и проблемы", "generated": "Обновлено",
        "last_run": "Последний прогон", "open": "Открытые проблемы", "none_open": "Открытых проблем нет.",
        "sites": "Сайты, которые не пускают способ чтения", "resolved": "Недавно решено",
        "library": "Библиотека законов", "act": "Акт", "what": "Что случилось", "since": "С", "times": "Раз",
        "agent": "Что сделает агент", "you": "Что можете сделать вы", "site": "Сайт", "engine": "Способ",
        "runs": "Прогонов подряд", "status": "Сейчас", "tried_last": "пробуется последним",
        "tried": "пробуется как обычно", "held": "Редакция у нас", "next": "Будущая редакция",
        "checked": "Проверено", "copies": "Копий текста", "solved_on": "Решено", "how": "Как",
        "detail": "Подробности",
        "note": "Эта страница есть только на вашем компьютере. «Не проверено» никогда не значит «без изменений».",
        "fix": {
            "blocked": ("прочитает официальную страницу через Firecrawl, если он подключён, иначе в вашем браузере, "
                        "и запишет карточку редакции",
                        "подключите Firecrawl (шаг настройки `reading`) или разрешите агенту ваш браузер"),
            "fetch_failed": ("повторит в следующий прогон; после 3 неудач проверит вручную",
                             "ничего, если сайт не лежит долго"),
            "parse_failed": ("проверит акт вручную; если повторяется — сохранит страницу как образец для движка",
                             "сообщить авторам движка, если агент предложит (решаете вы)"),
            "uncalibrated": ("проверяет акт вручную, пока чтение сайта не сверено", "ничего"),
            "no_source": ("найдёт официальную страницу акта и добавит её в список наблюдения",
                          "подтвердить найденную страницу"),
            "stale_fallback": ("найдёт актуальный официальный текст; архивная копия — не проверка", "ничего"),
            "reader_crashed": ("проверит акт вручную и сохранит ошибку для авторов движка",
                               "сообщить авторам движка, если агент предложит (решаете вы)"),
            "gazette_failed": ("снова просмотрит Monitorul Oficial в следующий прогон", "ничего"),
            "_": ("проверит акт вручную", "ничего")}},
}

# An issue kind → the reason key of the digest, for the "what happened" text.
WHY = {"blocked": "blocked_403", "uncalibrated": "parser_uncalibrated", "reader_crashed": "adapter_crashed",
       "gazette_failed": "gazette_scan_incomplete"}

CSS = """body{font:15px/1.45 system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;color:#222}
h1{font-size:1.5em}h2{font-size:1.15em;margin-top:2em}table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #ddd;padding:.4em .5em;text-align:left;vertical-align:top}th{background:#f4f4f4}
.p1{font-weight:600}.muted{color:#666}.bad{color:#a00}code{font-size:.9em}details{margin:.2em 0}"""


def cls(priority) -> str:
    """A class attribute from an allowlist only: a damaged state must not inject attributes."""
    return f' class="{priority}"' if priority in lib.PRIORITIES else ""


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _texts(laws: Path, act_id: str) -> list[str]:
    folder = laws / "texts" / act_id
    return sorted(p.name for p in folder.glob("*.txt")) if folder.is_dir() else []


def _last_run(laws: Path) -> dict | None:
    runs = laws / "runs"
    days = sorted(p.name for p in runs.iterdir() if (p / "run.json").is_file()) if runs.is_dir() else []
    return lib.read_json(runs / days[-1] / "run.json", "last run") if days else None


def render(profile: Path, language: str = "en", today: _dt.date | None = None) -> str:
    t, d = P.get(language, P["en"]), _digest.T.get(language, _digest.T["en"])
    today = today or _dt.date.today()
    laws = lib.laws_dir(profile)
    state, log, run = lib.load_state(profile), _issues.load(profile), _last_run(laws)
    titles = {r["act_id"]: r.get("title") for r in (run or {}).get("acts") or []}
    prio = {r["act_id"]: r.get("priority") for r in (run or {}).get("acts") or []}
    late = _issues.demoted(log, today)
    h = _digest.health(state, today, (run or {}).get("schedule"))
    out = [f'<!doctype html><html lang="{e(language)}"><head><meta charset="utf-8">',
           f"<title>{e(t['title'])}</title><style>{CSS}</style></head><body>",
           f"<h1>{e(t['title'])}</h1>",
           f"<p class='muted'>{e(t['generated'])}: {e(today.isoformat())} · {e(t['note'])}</p>"]
    if run:
        head = run.get("result")
        if head == "OK" and not run.get("phrase_no_changes_allowed"):
            head = "PARTLY" if (run.get("summary") or {}).get("checked") else "NONE"
        s = run.get("summary") or {}
        out.append(f"<p>{e(t['last_run'])}: <b>{e(run.get('date'))}</b> — {e(d['result'].get(head, head))} · "
                   f"{e(d['checked'])} {e(s.get('checked'))} {e(d['of'])} {e(s.get('acts'))}</p>")
    out.append(f"<p>{e(d['health'])}: <b>{e(h['last_complete'] or d['never'])}</b>"
               + (f" <span class='bad'>{e(d['overdue'].format(d=h['days_since'] if h['days_since'] is not None else '?'))}</span>"
                  if h["overdue"] else "") + "</p>")

    out.append(f"<h2>{e(t['open'])}</h2>")
    opened = _issues.open_issues(log)
    if not opened:
        out.append(f"<p>{e(t['none_open'])}</p>")
    else:
        out.append(f"<table><tr><th>{e(t['act'])}</th><th>{e(t['what'])}</th><th>{e(t['since'])}</th>"
                   f"<th>{e(t['times'])}</th><th>{e(t['agent'])}</th><th>{e(t['you'])}</th></tr>")
        for i in opened:
            agent, you = t["fix"].get(i.get("kind"), t["fix"]["_"])
            last = i.get("last") or {}
            what = d["why"].get(WHY.get(i.get("kind"), i.get("kind")), i.get("kind"))
            detail = " · ".join(e(x) for x in (last.get("via"), f"HTTP {last['http_status']}"
                                               if last.get("http_status") else None, last.get("error")) if x)
            url = f'<br><code>{e(last.get("url"))}</code>' if last.get("url") else ""
            out.append(f"<tr{cls(i.get('priority'))}><td>{e(i.get('title') or i['act_id'])}<br>"
                       f"<code>{e(i['act_id'])}</code> [{e(i.get('priority'))}]</td>"
                       f"<td>{e(what)}<details><summary>{e(t['detail'])}</summary>{detail}{url}</details></td>"
                       f"<td>{e(i.get('first_seen'))}</td><td>{e(i.get('count'))}</td>"
                       f"<td>{e(agent)}</td><td>{e(you)}</td></tr>")
        out.append("</table>")
    if _digest.needs_firecrawl_tip(run):
        out.append(f"<p>{e(d['firecrawl_tip'])}</p>")

    sites = _issues.site_issues(log)
    if sites:
        out.append(f"<h2>{e(t['sites'])}</h2><table><tr><th>{e(t['site'])}</th><th>{e(t['engine'])}</th>"
                   f"<th>{e(t['runs'])}</th><th>{e(t['status'])}</th><th>{e(t['detail'])}</th></tr>")
        for s in sites:
            now = t["tried_last"] if s["via"] in late.get(s["host"], set()) else t["tried"]
            out.append(f"<tr><td>{e(s['host'])}</td><td>{e(s['via'])}</td><td>{e(s['streak'])}</td>"
                       f"<td>{e(now)}</td><td>{e(s.get('last_error'))}</td></tr>")
        out.append("</table>")

    solved = sorted((i for i in log["acts"].values() if i.get("state") == "resolved"),
                    key=lambda i: i.get("resolved_on") or "", reverse=True)[:20]
    if solved:
        out.append(f"<h2>{e(t['resolved'])}</h2><table><tr><th>{e(t['act'])}</th><th>{e(t['what'])}</th>"
                   f"<th>{e(t['solved_on'])}</th><th>{e(t['how'])}</th></tr>")
        for i in solved:
            what = d["why"].get(WHY.get(i.get("kind"), i.get("kind")), i.get("kind"))
            out.append(f"<tr><td>{e(i.get('title') or i['act_id'])}</td><td>{e(what)}</td>"
                       f"<td>{e(i.get('resolved_on'))}</td><td>{e(i.get('resolved_by'))}</td></tr>")
        out.append("</table>")

    ids = sorted(set(state["acts"]) | set(titles))
    if ids:
        out.append(f"<h2>{e(t['library'])}</h2><table><tr><th>{e(t['act'])}</th><th>{e(t['held'])}</th>"
                   f"<th>{e(t['next'])}</th><th>{e(t['checked'])}</th><th>{e(t['copies'])}</th></tr>")
        for a in ids:
            held = state["acts"].get(a) or {}
            cur, nxt = held.get("current") or {}, held.get("next") or {}
            fmt = lambda r: f"{r.get('label')} ({d['from']} {r.get('in_force_from')})" if r else "—"  # noqa: E731
            gone = held.get("repealed")
            # why: a repeal keeps the last version as history; the page must not show it as the version in force
            held_cell = (f"<b class='bad'>{e(d['kind']['repealed'])}: {e(fmt(gone))}</b><br>"
                         f"<span class='muted'>{e(fmt(cur))}</span>") if gone else e(fmt(cur))
            out.append(f"<tr{cls(prio.get(a))}><td>{e(titles.get(a) or a)}<br><code>{e(a)}</code></td>"
                       f"<td>{held_cell}</td><td>{e(fmt(nxt))}</td><td>{e(held.get('checked_on') or '—')}</td>"
                       f"<td>{len(_texts(laws, a))}</td></tr>")
        out.append("</table>")
    out.append("</body></html>\n")
    return "\n".join(out)


def path(profile: Path) -> Path:
    return lib.laws_dir(profile) / "report.html"


def write(profile: Path, language: str = "en", today: _dt.date | None = None) -> Path:
    p = path(profile)
    lib.write_atomic(p, render(profile, language, today))
    return p
