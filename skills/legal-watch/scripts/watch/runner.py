"""One monitoring run: every watched act against its official source → run.json, digest.md, state, snapshots,
and the contract clauses that depend on a changed act.

Rules (the engine's law-check discipline, `<legal-workflow>/references/law-check.md`):
- an act is *checked* only when the adapter read the version list (unchanged / new_in_force / new_future /
  repealed) with a parser calibrated on a live page of that source; anything else is "not verified", never
  "no changes";
- the first reading of an act records its baseline (`baseline`), it is not a change;
- a change read by an uncalibrated parser is reported as *possible*, does not move the baseline and asks for a
  check by hand (`legal_watch.py record`);
- an act named in a new issue of the Moldovan Official Gazette stays "not verified" (the consolidated page lags
  the Gazette) until a new version is read or it is checked by hand;
- a repeal already held is not a new change;
- one p1 act not verified → the run is INCOMPLETE (exit 2) and the digest never says "no changes";
- a future version is a change of kind `future`, never "in force".
Result and exit code: OK → 0, CHANGES → 1, INCOMPLETE → 2.
"""
from __future__ import annotations

import datetime as _dt
import functools
from pathlib import Path

from . import clauses as _clauses
from . import digest as _digest
from . import issues as _issues
from . import library as lib
from . import report as _report
from .adapters import adapter_for, cellar, monitorul_md
from .contract import (FETCH_FAILED, NEW_FUTURE, NEW_IN_FORCE, PARSE_FAILED, REPEALED, SCAN_COMPLETE, UNCHANGED,
                       AdapterResult, ContractError)
from .fetchers import FetchResult, _Paced, now_iso

BASELINE = "baseline"
REPEAL_KNOWN = "repealed_known"     # the act was already held as repealed: checked, no new change
VERIFIABLE = (UNCHANGED, NEW_IN_FORCE, NEW_FUTURE, REPEALED, BASELINE, REPEAL_KNOWN)
CHANGE_KIND = {NEW_IN_FORCE: "in_force", NEW_FUTURE: "future", REPEALED: "repealed"}
EXIT = {"OK": 0, "CHANGES": 1, "INCOMPLETE": 2}
HOST_ONLY_ERROR = "engine 'host' only"


class RecordingFetcher:
    """Keeps every page fetched in the run, so the official text can be saved as a snapshot."""

    def __init__(self, inner):
        self.inner = inner
        self.pages: dict[str, FetchResult] = {}
        self._own: list[dict] = []

    def get(self, url: str) -> FetchResult:
        r = self.inner.get(url)
        self.pages[url] = r
        self._own.append(attempt_of(url, r))
        return r

    @property
    def attempts(self) -> list[dict]:
        """Every engine tried, for the error log: the chain's own list when there is one (it sees each engine)."""
        inner = getattr(self.inner, "attempts", None)
        return list(inner) if isinstance(inner, list) else list(self._own)


def attempt_of(url: str, r: FetchResult) -> dict:
    ok = not r.error and not r.blocked and r.status is not None and r.status < 400
    return {"host": _issues.host_of(url), "via": r.via, "ok": ok, "http_status": r.status,
            "error": None if ok else (r.error or r.blocked_reason or f"HTTP {r.status}")}


class PacedCellarGet(_Paced):
    """Cellar's own HTTP getter (it needs content negotiation headers), paced like every engine."""

    via = "urllib"

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.pages: dict[str, str] = {}   # url → body, so the EU text read via Cellar is saved like any page

    def __call__(self, url, headers, *args, **kw):
        self.pause()
        status, final_url, body = cellar.urllib_get(url, headers, *args, **kw)
        if status == 200:
            self.pages[url] = body
        return status, final_url, body


def official_text(url: str, rec: RecordingFetcher, cellar_get) -> str | None:
    """The text behind a reading's evidence: a page of the fetch engines, or a Cellar text (EU fallback)."""
    # why: pop, not get: a run of many acts must not keep every page it read in memory
    page = rec.pages.pop(url, None)
    if page is not None:
        return page.text or page.markdown
    body = getattr(cellar_get, "pages", {}).pop(url, None)
    # why: the same plain text the adapter hashed, so the snapshot name matches evidence.sha256
    return cellar.page_text(body)[1] if body is not None else None


def check_one(act: dict, fetcher, today: _dt.date, *, cellar_get=None) -> dict:
    name, fn = adapter_for(act)
    base = {"act_id": act["id"], "title": act.get("title"), "jurisdiction": act.get("jurisdiction"),
            "priority": act.get("priority")}
    if fn is None:
        kinds = sorted({s.get("kind") for s in act.get("sources") or []})
        res = AdapterResult(act_id=act["id"], adapter="none", status=FETCH_FAILED,
                            error=f"no monitoring source for this act (sources: {kinds or 'none'}); "
                                  "check it by hand and record the version card").to_dict()
        return {**base, **res, "reasons": ["no_source"]}
    if name == "eurlex":
        # Cellar is read with plain HTTP, so it runs only when the user allowed the urllib engine.
        fn = functools.partial(fn, cellar_get=cellar_get, cellar_fallback=cellar_get is not None)
    try:
        res = fn(act, fetcher, today).to_dict()
    except ContractError as e:
        res = AdapterResult(act_id=act["id"], adapter=name, status=PARSE_FAILED,
                            error=f"adapter broke the result contract: {e}").to_dict()
        return {**base, **res, "reasons": ["adapter_crashed"]}
    except Exception as e:  # noqa: BLE001 — a crashed adapter is "not verified", never silence
        res = AdapterResult(act_id=act["id"], adapter=name, status=FETCH_FAILED,
                            error=f"adapter crashed: {type(e).__name__}: {str(e)[:200]}").to_dict()
        return {**base, **res, "reasons": ["adapter_crashed"]}
    return {**base, **res, "reasons": []}


def classify_record(r: dict, *, repeal_held: bool = False, signals: list | None = None) -> dict:
    """Effective status and the reasons an act is not verified (in place)."""
    st, notes = r["status"], r.get("notes") or []
    reasons = r.setdefault("reasons", [])
    if st == NEW_IN_FORCE and any(n.startswith("baseline absent") for n in notes):
        r["adapter_status"], r["status"] = st, BASELINE
    elif st == REPEALED and repeal_held:
        r["adapter_status"], r["status"] = st, REPEAL_KNOWN
    elif st not in VERIFIABLE and not reasons:
        reasons.append("host_only" if HOST_ONLY_ERROR in (r.get("error") or "") else st)
    ev = r.get("evidence") or {}
    if r["status"] in VERIFIABLE and not ev.get("parser_calibrated"):
        reasons.append("parser_uncalibrated")
        if r["status"] in (UNCHANGED, BASELINE, REPEAL_KNOWN):
            r.setdefault("adapter_status", r["status"])
            r["status"] = PARSE_FAILED
            r["error"] = ("the parser of this source is not yet calibrated on a live page: the reading is not "
                          "accepted as a check; confirm the act by hand")
    if signals and r["status"] in (UNCHANGED, BASELINE, REPEAL_KNOWN):
        # The Gazette published something about this act that the consolidated page does not show yet.
        reasons.append("gazette_signal")
        r["gazette_signals"] = signals
    r["checked"] = r["status"] in VERIFIABLE and not reasons
    return r


def change_of(r: dict, run_date: str) -> dict | None:
    st = r["status"]
    if st not in CHANGE_KIND:
        return None
    red = (r.get("next") if st == NEW_FUTURE else r.get("current")) or {}
    return {"act_id": r["act_id"], "title": r.get("title"), "priority": r.get("priority"),
            "kind": CHANGE_KIND[st], "label": red.get("label"), "in_force_from": red.get("in_force_from"),
            "confirmed": bool(r.get("checked")), "reasons": list(r.get("reasons") or []), "run_date": run_date}


def update_state(state: dict, r: dict, day: str, snapshot: str | None) -> None:
    """Move the baseline only on a checked reading: an unconfirmed change keeps being reported until confirmed."""
    if not r.get("checked"):
        return
    held = state["acts"].setdefault(r["act_id"], {})
    if r["status"] == REPEALED:
        held["repealed"] = r.get("current")
    elif r["status"] != REPEAL_KNOWN:
        held["current"] = r.get("current")
        held["next"] = r.get("next")
    ev = r.get("evidence") or {}
    held.update({"sha256": ev.get("sha256"), "url": ev.get("url"), "via": ev.get("via"),
                 "checked_on": day, "snapshot": snapshot or held.get("snapshot")})
    # why: `evidence.via` names the tool that read the page (host or firecrawl), `adapter` "host" means the act was
    # checked by hand from a version card; only the latter resolves amendments and Gazette signals. A record
    # written before `--via` existed carries `via` "host" without the adapter, so that still counts as by hand.
    by_hand = r.get("adapter") == "host" or ev.get("via") == "host"
    # The list of amending acts and corrigenda is the baseline for spotting a new one. A check by hand resolves
    # the ones the reader listed today; a reader without such a list (not Cellar) keeps the old one.
    if by_hand:
        if r.get("related_reviewed") is not None:
            held["related"] = sorted(set(held.get("related") or []) | set(r["related_reviewed"]))
    elif r.get("related") is not None:
        held["related"] = r["related"]
    # A checked reading (a new version, or a check by hand) answers the Gazette's signals for this act.
    if r["status"] in CHANGE_KIND or by_hand:
        state.setdefault("signals", {}).pop(r["act_id"], None)


def finish(profile: Path, out: dict, state: dict, *, dry_run: bool, flag_ids: set[str] | None = None,
           gazette_now: bool = False, by_hand: bool = False, watched: set[str] | None = None) -> dict:
    """Shared tail of `run` and `record`: result, exit code, contract flags, digest, files.

    `flag_ids` limits the contract flags to the acts read now (a hand record must not re-flag the clauses of
    other acts of today's run that the user may already have cleared).
    """
    records = out["acts"]
    # why: url, engine and HTTP code too, so the error log and the report can say what exactly failed
    unverified = [{"act_id": r["act_id"], "title": r.get("title"), "priority": r.get("priority"),
                   "status": r["status"], "reasons": list(r.get("reasons") or []) or [r["status"]],
                   "error": r.get("error"), "url": (r.get("evidence") or {}).get("url"),
                   "via": (r.get("evidence") or {}).get("via"),
                   "http_status": (r.get("evidence") or {}).get("http_status"),
                   "notes": list(r.get("notes") or [])[:5]} for r in records if not r.get("checked")]
    mon = out.get("monitorul")
    if mon is not None and mon.get("status") != SCAN_COMPLETE:
        unverified.append({"act_id": "monitorul_md", "title": "Monitorul Oficial (MD)", "priority": "p2",
                           "status": mon.get("status"), "reasons": ["gazette_scan_incomplete"],
                           "error": mon.get("error"), "url": (mon.get("evidence") or {}).get("url"),
                           "via": (mon.get("evidence") or {}).get("via"),
                           "http_status": (mon.get("evidence") or {}).get("http_status"), "notes": []})
    changes = [c for c in (change_of(r, out["date"]) for r in records) if c]
    if any(u["priority"] == "p1" for u in unverified):
        result = "INCOMPLETE"
    elif changes:
        result = "CHANGES"
    else:
        result = "OK"
    out.update({"result": result, "exit_code": EXIT[result],
                "phrase_no_changes_allowed": result == "OK" and not unverified,
                "changes": changes, "unverified": unverified,
                "summary": {"acts": len(records), "checked": sum(bool(r.get("checked")) for r in records),
                            "baselines": sum(r["status"] == BASELINE for r in records),
                            "unverified": len(unverified),
                            "unverified_p1": sum(u["priority"] == "p1" for u in unverified),
                            "changes": len(changes)}})
    # Order of the writes, so that a failure at any point leaves the change still reported (why):
    # 1. the error log is read, validated and updated in memory first: a damaged log stops here, before anything;
    # 2. contract flags (idempotent), then run.json and the digest: the evidence of the run is on disk;
    # 3. the error log, then the state last: a run that stops before it keeps the old baseline, so a retry finds
    #    the same change again instead of "unchanged".
    log = None
    if not dry_run:
        read = set(flag_ids if flag_ids is not None else (r["act_id"] for r in records))
        log = _issues.prepare_run(profile, out, read | ({"monitorul_md"} if gazette_now else set()),
                                  by_hand=by_hand, watched=watched)
    flagged = []
    if not dry_run:
        to_flag = [c for c in changes if c["confirmed"] and (flag_ids is None or c["act_id"] in flag_ids)]
        flagged = _clauses.flag_changes(profile, to_flag)
    out["contracts_to_review"] = _merge_flagged(out.get("contracts_to_review") or [], flagged)
    if not dry_run:
        runs = [x for x in state["runs"] if x.get("date") != out["date"]]
        state["runs"] = runs + [{"date": out["date"], "result": result, "full": bool(out.get("full")),
                                 "at": now_iso()}]
    out["health"] = _digest.health(state, _dt.date.fromisoformat(out["date"]), out.get("schedule"))
    run_dir = lib.laws_dir(profile) / "runs" / out["date"]
    if dry_run:
        run_dir = run_dir / "dry-run"   # a rehearsal never replaces the real run of the day
    lib.write_json(run_dir / "run.json", out)
    lib.write_atomic(run_dir / "digest.md", _digest.render(out, out.get("language", "en")))
    if not dry_run:
        _issues.save(profile, log)
        lib.save_state(profile, state)
        _report.write(profile, out.get("language", "en"), _dt.date.fromisoformat(out["date"]))
    return out


def watched_ids(acts: list[dict]) -> set[str]:
    """The whole watchlist for the error log; the Gazette counts while a Moldovan act is watched."""
    return {a["id"] for a in acts} | ({"monitorul_md"} if any(a.get("jurisdiction") == "MD" for a in acts) else set())


def _merge_flagged(old: list[dict], new: list[dict]) -> list[dict]:
    by = {k["contract"]: dict(k) for k in old}
    for k in new:
        cur = by.setdefault(k["contract"], {**k, "clauses": []})
        cur["clauses"] = sorted(set(cur["clauses"]) | set(k["clauses"]))
    return list(by.values())


def merge_day(profile: Path, out: dict) -> dict:
    """A run of some acts (or a hand record) joins the day's run instead of replacing it."""
    path = lib.laws_dir(profile) / "runs" / out["date"] / "run.json"
    if not path.exists():
        return out
    day = lib.read_json(path, "run of the day")
    ids = {r["act_id"] for r in out["acts"]}
    out["acts"] = [r for r in day.get("acts", []) if r["act_id"] not in ids] + out["acts"]
    out["full"] = bool(day.get("full")) or bool(out.get("full"))
    out["contracts_to_review"] = day.get("contracts_to_review") or []
    if out.get("monitorul") is None:
        out["monitorul"] = day.get("monitorul")
    return out


def run(profile: Path, acts: list[dict], fetcher, today: _dt.date, *, selector: str = "all",
        dry_run: bool = False, language: str = "en", schedule: str | None = None, scan_gazette: bool = True,
        direct_http: bool = True, mode: str = "live") -> dict:
    """`direct_http`: the user allowed plain HTTP (engine urllib), so Cellar may be read as EUR-Lex fallback."""
    day = today.isoformat()
    state = lib.load_state(profile)
    state.setdefault("signals", {})
    chosen = lib.select(acts, selector)
    rec = RecordingFetcher(fetcher)

    mon = None
    # why: every watched MD act, not only the chosen ones: the scan point is one for all acts, so a partial run
    # that matched only its own acts would move past an issue naming another act and lose that signal for good
    md_acts = [a for a in acts if a.get("jurisdiction") == "MD"]
    if scan_gazette and md_acts:
        since = (state.get("monitorul") or {}).get("checked_through")
        try:
            mon = monitorul_md.scan(md_acts, rec, since, today).to_dict()
        except Exception as e:  # noqa: BLE001
            mon = {"source": "monitorul_md", "status": FETCH_FAILED, "checked_through": since,
                   "previous_checked_through": since, "latest_seen": None, "editions": [], "signals": [],
                   "evidence": None, "error": f"scan crashed: {type(e).__name__}: {str(e)[:200]}"}
        if not dry_run and mon.get("checked_through") is not None:
            state["monitorul"] = {"checked_through": mon["checked_through"], "updated": day}
        for sig in mon.get("signals") or []:
            # Kept in the state until answered: the scan point moves on, the signal must not be lost.
            pending = state["signals"].setdefault(sig["act_id"], [])
            if sig not in pending:
                pending.append(sig)

    cellar_get = PacedCellarGet(pause_range=getattr(fetcher, "pause_range", (5.0, 15.0))) if direct_http else None
    records = []
    for act in chosen:
        r = check_one(act, rec, today, cellar_get=cellar_get)
        r = classify_record(r, repeal_held=bool(act.get("repealed")),
                            signals=state["signals"].get(act["id"]))
        snap = None
        ev = r.get("evidence") or {}
        text = official_text(ev.get("url") or "", rec, cellar_get)
        if r.get("checked") and text is not None and not dry_run:
            snap = lib.save_snapshot(profile, r["act_id"], text, ev.get("sha256"), day)
        r["snapshot"] = snap
        if not dry_run:
            update_state(state, r, day, snap)
        records.append(r)

    out = {"schema_version": 1, "date": day, "generated_at": now_iso(), "mode": mode, "dry_run": dry_run,
           "selector": selector, "full": selector == "all", "language": language, "schedule": schedule,
           "acts": records, "monitorul": mon, "engine_attempts": rec.attempts}
    if not dry_run:
        out = merge_day(profile, out)
    return finish(profile, out, state, dry_run=dry_run, flag_ids={a["id"] for a in chosen},
                  gazette_now=mon is not None, watched=watched_ids(acts))
