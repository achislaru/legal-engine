"""The short digest of a run in the user's language (`laws/runs/<date>/digest.md`).

Order: what changed (confirmed first), contracts to re-review, what was not verified and why, signals from the
Official Gazette, run health. "No changes" is written only when every p1 act was checked (result OK).
"""
from __future__ import annotations

import datetime as _dt

MAX_DAYS = {"weekly": 9, "claude-schedule": 9}   # a weekly run that has not succeeded for 9 days is overdue

T = {
    "en": {
        "title": "Law monitoring", "result": {"OK": "no changes", "CHANGES": "changes found",
                                              "INCOMPLETE": "incomplete: not every key act was checked",
                                              "PARTLY": "no changes in the acts checked; some were not verified",
                                              "NONE": "nothing verified: no act could be checked"},
        "checked": "checked", "of": "of", "changes": "Changes", "kind": {"in_force": "new version in force",
                                                                         "future": "future version (not yet in force)",
                                                                         "repealed": "repealed"},
        "from": "from", "possible": "possible, not confirmed: check by hand",
        "contracts": "Contracts to re-review", "clauses": "clauses",
        "propose": "Proposed: a matter \"re-review contract {c}\" (audit and redline); nothing is changed without you.",
        "unverified": "Not verified", "why": {
            "fetch_failed": "the official site did not answer", "blocked_403": "the site blocked automatic access",
            "parse_failed": "the page could not be read reliably", "stale_fallback": "only an archived copy was read",
            "parser_uncalibrated": "the reader of this site is not yet calibrated",
            "no_source": "no official source configured", "adapter_crashed": "the reader failed",
            "gazette_scan_incomplete": "the Official Gazette scan did not finish",
            "host_only": "engine 'host' only: check by hand",
            "gazette_signal": "the Official Gazette published something about it that the page does not show yet"},
        "rest": "{n} not verified",
        "page": "Details and what to do: laws/report.html in your profile.",
        "byhand": "Ask me to check these by hand (the agent opens the official page and records a version card).",
        "baselines": "First reading recorded (baseline)", "signals": "Official Gazette (MD): issues mentioning watched acts",
        "health": "Last run with every main act checked", "overdue": "overdue: the scheduled run has not completed for {d} days",
        "never": "none yet", "nochanges": "No changes in the acts checked.",
        "firecrawl_tip": ("Sites refused automatic reading. Connecting Firecrawl (the wizard's first step `reading`, "
                          "or ask to change it later) lets the scripts read them; it is a paid service with a free "
                          "monthly allowance, and you sign in yourself.")},
    "ro": {
        "title": "Monitorizarea legislației", "result": {"OK": "fără modificări", "CHANGES": "modificări găsite",
                                                         "INCOMPLETE": "incomplet: nu toate actele principale au fost verificate",
                                                         "PARTLY": "fără modificări în actele verificate; unele nu au fost verificate",
                                                         "NONE": "nimic verificat: niciun act nu a putut fi verificat"},
        "checked": "verificate", "of": "din", "changes": "Modificări", "kind": {"in_force": "redacție nouă în vigoare",
                                                                               "future": "redacție viitoare (încă nu în vigoare)",
                                                                               "repealed": "abrogat"},
        "from": "din", "possible": "posibilă, neconfirmată: de verificat manual",
        "contracts": "Contracte de revizuit", "clauses": "clauze",
        "propose": "Propunere: un dosar „revizuirea contractului {c}” (audit și modificări urmărite); nimic nu se schimbă fără dvs.",
        "unverified": "Neverificate", "why": {
            "fetch_failed": "site-ul oficial nu a răspuns", "blocked_403": "site-ul a blocat accesul automat",
            "parse_failed": "pagina nu a putut fi citită sigur", "stale_fallback": "s-a citit doar o copie arhivată",
            "parser_uncalibrated": "cititorul acestui site nu este încă calibrat",
            "no_source": "nu există sursă oficială configurată", "adapter_crashed": "cititorul a eșuat",
            "gazette_scan_incomplete": "scanarea Monitorului Oficial nu s-a încheiat",
            "host_only": "doar verificare manuală (motorul host)",
            "gazette_signal": "Monitorul Oficial a publicat ceva despre act ce pagina nu arată încă"},
        "rest": "{n} neverificate",
        "page": "Detalii și ce e de făcut: laws/report.html din profilul dvs.",
        "byhand": "Cereți-mi să le verific manual (agentul deschide pagina oficială și înregistrează fișa redacției).",
        "baselines": "Prima citire înregistrată (punct de referință)",
        "signals": "Monitorul Oficial (MD): numere care menționează acte urmărite",
        "health": "Ultima rulare cu toate actele principale verificate", "overdue": "întârziere: rularea programată nu s-a încheiat de {d} zile",
        "never": "încă niciuna", "nochanges": "Nicio modificare în actele verificate.",
        "firecrawl_tip": ("Unele site-uri au refuzat citirea automată. Conectarea Firecrawl (primul pas al "
                          "asistentului, `reading`, sau cereți schimbarea mai târziu) le permite scripturilor să le "
                          "citească; este un serviciu plătit cu o cotă lunară gratuită, iar autentificarea o faceți "
                          "dvs.")},
    "ru": {
        "title": "Мониторинг законов", "result": {"OK": "без изменений", "CHANGES": "есть изменения",
                                                  "INCOMPLETE": "неполно: проверены не все главные акты",
                                                  "PARTLY": "в проверенных актах изменений нет; часть не проверена",
                                                  "NONE": "ничего не проверено: ни один акт проверить не удалось"},
        "checked": "проверено", "of": "из", "changes": "Изменения", "kind": {"in_force": "новая редакция действует",
                                                                            "future": "будущая редакция (ещё не действует)",
                                                                            "repealed": "отменён"},
        "from": "с", "possible": "возможно, не подтверждено: проверить вручную",
        "contracts": "Договоры на пересмотр", "clauses": "пункты",
        "propose": "Предлагаю дело «пересмотр договора {c}» (аудит и правки Word); без вас ничего не меняется.",
        "unverified": "Не проверено", "why": {
            "fetch_failed": "официальный сайт не ответил", "blocked_403": "сайт закрыл автоматический доступ",
            "parse_failed": "страницу не удалось надёжно прочитать", "stale_fallback": "прочитана только архивная копия",
            "parser_uncalibrated": "чтение этого сайта ещё не сверено",
            "no_source": "нет официального источника", "adapter_crashed": "чтение сломалось",
            "gazette_scan_incomplete": "просмотр Monitorul Oficial не закончен",
            "host_only": "только ручная проверка (движок host)",
            "gazette_signal": "в Monitorul Oficial вышло что-то об акте, чего ещё нет на странице"},
        "rest": "не проверено: {n}",
        "page": "Подробности и что делать: laws/report.html в вашем профиле.",
        "byhand": "Попросите меня проверить их вручную (агент откроет официальную страницу и запишет карточку редакции).",
        "baselines": "Первое чтение записано (исходная редакция)",
        "signals": "Monitorul Oficial (MD): номера, где упомянуты отслеживаемые акты",
        "health": "Последний прогон, где проверены все главные акты", "overdue": "просрочено: плановый прогон не завершался {d} дн.",
        "never": "ещё не было", "nochanges": "В проверенных актах изменений нет.",
        "firecrawl_tip": ("Сайты отказали в автоматическом чтении. Подключение Firecrawl (первый шаг мастера "
                          "`reading` или попросите изменить позже) позволит скриптам их читать; это платный сервис "
                          "с бесплатным месячным лимитом, вход вы делаете сами.")},
}


def health(state: dict, today: _dt.date, schedule: str | None) -> dict:
    """When the last run that checked every p1 act happened, and whether a scheduled run is overdue."""
    # Only a run of all acts counts: a run of some acts or a hand record must not hide a missed weekly run.
    runs = state.get("runs", [])
    good = [r["date"] for r in runs if r.get("result") in ("OK", "CHANGES") and r.get("full", True)]
    last = max(good) if good else None
    days = (today - _dt.date.fromisoformat(last)).days if last else None
    limit = MAX_DAYS.get(schedule or "")
    earlier = [r for r in runs if r.get("date") != today.isoformat()]   # the first run is never "overdue"
    overdue = limit is not None and (days is None or days > limit) and bool(earlier)
    return {"last_complete": last, "days_since": days, "overdue": overdue}


# Reasons a script engine could not read the page; Firecrawl reads many such sites (anti-bot pages, dropped
# connections). Other reasons (no source, uncalibrated reader, Gazette signal) are not helped by another engine.
REFUSALS = ("blocked_403", "fetch_failed")


def needs_firecrawl_tip(run: dict | None) -> bool:
    """Suggest Firecrawl only when it was not among the run's engines and a site refused the scripts."""
    if not run or "firecrawl" in (run.get("engines") or []):
        return False
    return any(set(u.get("reasons") or []) & set(REFUSALS) for u in run.get("unverified") or [])


def _name(x: dict) -> str:
    return f"{x.get('title') or x['act_id']} (`{x['act_id']}`)"


def render(run: dict, language: str = "en") -> str:
    t = T.get(language, T["en"])
    s = run["summary"]
    # why: "no changes" only when nothing is left unverified, even if the run is OK (a p2 act not verified)
    head = run["result"]
    if head == "OK" and not run.get("phrase_no_changes_allowed"):
        head = "PARTLY" if s.get("checked") else "NONE"
    lines = [f"# {t['title']} — {run['date']}", "",
             f"**{t['result'][head]}** · {t['checked']} {s['checked']} {t['of']} {s['acts']}"
             + (f" · {t['rest'].format(n=s['unverified'])}" if s.get("unverified") else ""), ""]
    changes = sorted(run.get("changes") or [], key=lambda c: (not c["confirmed"], c.get("priority") or "p9"))
    if changes:
        lines += [f"## {t['changes']}", ""]
        for c in changes:
            when = f", {t['from']} {c['in_force_from']}" if c.get("in_force_from") else ""
            label = f" — {c['label']}" if c.get("label") else ""
            tail = "" if c["confirmed"] else f" — *{t['possible']}*"
            lines.append(f"- {_name(c)}: {t['kind'][c['kind']]}{label}{when}{tail}")
        lines.append("")
    if run.get("contracts_to_review"):
        lines += [f"## {t['contracts']}", ""]
        for k in run["contracts_to_review"]:
            lines.append(f"- {k['contract']}: {t['clauses']} {', '.join(k['clauses'])}")
            lines.append(f"  {t['propose'].format(c=k['contract'])}")
        lines.append("")
    if run.get("unverified"):
        lines += [f"## {t['unverified']}", ""]
        for u in run["unverified"]:
            why = "; ".join(t["why"].get(r, r) for r in u["reasons"])
            lines.append(f"- {_name(u)} [{u.get('priority')}]: {why}")
        lines += ["", t["byhand"], t["page"]]
        if needs_firecrawl_tip(run):
            lines.append(t["firecrawl_tip"])
        lines.append("")
    baselines = [r for r in run.get("acts") or [] if r["status"] == "baseline"]
    if baselines:
        lines += [f"## {t['baselines']}", ""]
        for r in baselines:
            cur = r.get("current") or {}
            lines.append(f"- {_name(r)}: {cur.get('label')} ({t['from']} {cur.get('in_force_from')})")
        lines.append("")
    mon = run.get("monitorul") or {}
    if mon.get("signals"):
        lines += [f"## {t['signals']}", ""]
        for sig in mon["signals"]:
            lines.append(f"- `{sig['act_id']}`: MO {sig.get('edition_number') or sig['edition_id']} "
                         f"({sig.get('edition_date') or '?'}) — {sig['item'][:160]} <{sig['url']}>")
        lines.append("")
    if run.get("phrase_no_changes_allowed"):
        lines += [t["nochanges"], ""]
    h = run.get("health") or {}
    lines.append(f"{t['health']}: {h.get('last_complete') or t['never']}")
    if h.get("overdue"):
        lines.append(f"**{t['overdue'].format(d=h.get('days_since') if h.get('days_since') is not None else '?')}**")
    return "\n".join(lines) + "\n"
