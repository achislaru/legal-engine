"""The `host` engine: an act checked by hand by the agent becomes a monitoring result.

When no script engine can read an official page (anti-bot pages, a portal that drops connections), the agent
opens it with its own web tools or the user's browser and fills a version card of `legal-research`
(`<legal-research>/references/version-check.md`). `record` validates the card with that skill's checker, turns it
into an `AdapterResult` of adapter `host` and merges it into today's run: the same comparison with the held
baseline, the same state, digest and contract flags as an automatic reading. A card that is not from today, fails
the checker or is `not_verified` changes nothing.

`via` names the tool the agent read the page with: `host` (its own web tools or the browser) or `firecrawl` (the
Firecrawl CLI, for a site that refuses the script engines). Either way it stays a check by hand (adapter `host`):
the agent read the page and filled the card, so it resolves amendments and Gazette signals the same way.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
from pathlib import Path

from . import library as lib
from . import runner
from .adapters.common import md_to_text
from .contract import AdapterResult, Evidence, Redaction, classify, parse_date, text_sha256

CHECKER = lib.SKILL.parent / "legal-research" / "scripts" / "check_version.py"
# The points of a `scope: "text"` card (version-check.md): all must be closed from a live official page before a
# hand check can count. The checker accepts an `outdated` card with open points; monitoring may not.
REQUIRED_POINTS = ("consolidation", "amendments", "deferred_entry", "repeal", "status_of_changes")
VIA = ("host", "firecrawl")


def open_points(card: dict) -> list[str]:
    """Required points not closed by live evidence (done, with at least one source that is not an archive copy)."""
    out = []
    for name in REQUIRED_POINTS:
        point = (card.get("points") or {}).get(name) or {}
        live = [e for e in point.get("evidence") or [] if isinstance(e, dict) and not e.get("archived_on")]
        if point.get("status") != "done" or not live:
            out.append(name)
    return out


def _consolidation_evidence(card: dict) -> list[dict]:
    return [e for e in ((card.get("points") or {}).get("consolidation") or {}).get("evidence") or []
            if isinstance(e, dict)]


def saved_text(path: Path) -> str:
    """The text of a saved official page, as the evidence hash and the snapshot need it.

    A `.md` file becomes the same plain text the legis_md markdown reader hashes (`md_to_text`), so a page saved
    through Firecrawl gives the same evidence hash and snapshot as a scripted reading of that page; anything else
    is kept as it is.
    """
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    return md_to_text(raw) if Path(path).suffix.lower() == ".md" else raw


def _checker():
    if not CHECKER.exists():
        raise lib.WatchError(f"legal-research is not installed next to legal-watch ({CHECKER} missing)")
    spec = importlib.util.spec_from_file_location("check_version", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def card_to_result(act: dict, card: dict, today: _dt.date, text: str | None = None, *,
                   via: str = "host") -> AdapterResult:
    """A version card that passed the checker → the monitoring result for the act."""
    if (card.get("act") or {}).get("id") != act["id"]:
        raise lib.WatchError(f"the card is for {(card.get('act') or {}).get('id')!r}, not {act['id']}")
    if card.get("result") not in ("current", "outdated"):
        raise lib.WatchError("a not_verified card changes nothing: the act stays not verified in this run")
    latest = card.get("latest_in_force") or {}
    parsed = []
    if latest.get("version_from"):
        parsed.append(Redaction(label=latest.get("label") or f"version from {latest['version_from']}",
                                in_force_from=latest["version_from"]))
    for nxt in card.get("next_versions") or []:
        parsed.append(Redaction(label=nxt.get("label") or f"version from {nxt['applies_from']}",
                                in_force_from=nxt["applies_from"]))
    # why: an amendment in force (or adopted for later) may not be in a consolidation yet; it is a version of the
    # act all the same, or a held consolidation date would make an amended act look "unchanged".
    known = {r.in_force_from for r in parsed}
    for ch in card.get("changes") or []:
        when = ch.get("applies_from") or ch.get("in_force_from")
        if ch.get("status") in ("in_force", "published_not_in_force") and when and when not in known:
            parsed.append(Redaction(label=f"amended by {ch.get('act')} (not consolidated)", in_force_from=when))
            known.add(when)
    rep = card.get("repealed") or {}
    gone = bool(rep.get("from")) and parse_date(rep["from"]) <= today
    if rep.get("from") and not gone:
        # A repeal dated in the future is a next version of the act, not a repeal today.
        parsed.append(Redaction(label=f"repeal by {rep.get('by')}", in_force_from=rep["from"]))
    ev_list = _consolidation_evidence(card)
    ev0 = ev_list[0] if ev_list else {}
    # Only the text read now, hashed like every engine's page text (whitespace-normalised): the card's raw-byte
    # hash or the held hash would mix kinds and let "unchanged" rest on an old reading.
    sha = text_sha256(text) if text else None
    evidence = Evidence(url=ev0.get("url") or (card.get("act") or {}).get("official_record_url") or "",
                        fetched_at=card.get("checked_at") or "", sha256=sha, parser="version-card",
                        parser_calibrated=True, via=via)
    status, cur, nxt, err, notes = classify(act=act, parsed=parsed, today=today, repealed=gone,
                                            repealed_label=f"repealed by {rep.get('by')}" if gone else None)
    if status == "unchanged" and not sha:
        # The contract needs a hash for "unchanged": the agent saves the text it read (text_file + text_sha256).
        status, err = "parse_failed", "no saved text of the reading: give text_file in the card and --root"
    note = "checked by hand from a version card" + (" (page read through Firecrawl)" if via == "firecrawl" else "")
    notes = [note] + notes
    return AdapterResult(act_id=act["id"], adapter="host", status=status, current=cur, next=nxt,
                         evidence=evidence, error=err, notes=notes).validate()


def record(profile: Path, acts: list[dict], card_path: Path, today: _dt.date, *, root: Path | None = None,
           language: str = "en", schedule: str | None = None, via: str = "host") -> dict:
    if via not in VIA:
        raise lib.WatchError(f"--via must be one of {', '.join(VIA)}")
    checker = _checker()
    card = checker.load(Path(card_path))
    check = checker.validate(card, _dt.datetime.now().astimezone(), root)
    if check["errors"]:
        raise lib.WatchError("the version card fails its checker: " + "; ".join(check["errors"]))
    # why: monitoring asks "which version is in force today for the whole act"; a card about an earlier date or
    # about some articles answers another question and must not mark the act checked or clear its signals.
    if card.get("analysis_date") != today.isoformat():
        raise lib.WatchError(f"the card analyses {card.get('analysis_date')}, not today ({today}); monitoring needs "
                             "today's version")
    if card.get("scope") != "text" or "whole act" not in (card.get("cited_provisions") or []):
        raise lib.WatchError('a hand check for monitoring needs scope "text" and cited_provisions ["whole act"]')
    gaps = open_points(card)
    if gaps:
        raise lib.WatchError("a hand check counts only when these points are closed from a live official page: "
                             + ", ".join(gaps))
    act_id = (card.get("act") or {}).get("id")
    act = next((a for a in acts if a["id"] == act_id), None)
    if act is None:
        raise lib.WatchError(f"{act_id!r} is not in the watchlist; add it first")
    text_file = next((e["text_file"] for e in _consolidation_evidence(card) if e.get("text_file")), None)
    text = None
    if text_file and root is not None and (Path(root) / text_file).is_file():
        text = saved_text(Path(root) / text_file)
    res = card_to_result(act, card, today, text, via=via).to_dict()
    r = runner.classify_record({"act_id": act["id"], "title": act.get("title"),
                                "jurisdiction": act.get("jurisdiction"), "priority": act.get("priority"),
                                **res, "reasons": []}, repeal_held=bool(act.get("repealed")))
    state = lib.load_state(profile)
    # The amendments the automatic reader listed today are the ones this check by hand has just reviewed.
    day_run = lib.laws_dir(profile) / "runs" / today.isoformat() / "run.json"
    if day_run.is_file():
        earlier = next((x for x in lib.read_json(day_run, "run of the day").get("acts", [])
                        if x.get("act_id") == act["id"] and x.get("related") is not None), None)
        if earlier is not None:
            r["related_reviewed"] = earlier["related"]
    snap = None
    if r.get("checked") and text:
        snap = lib.save_snapshot(profile, act["id"], text, (r.get("evidence") or {}).get("sha256"), today.isoformat())
    r["snapshot"] = snap
    runner.update_state(state, r, today.isoformat(), snap)

    out = {"schema_version": 1, "date": today.isoformat(), "generated_at": runner.now_iso(), "mode": "host",
           "dry_run": False, "selector": act["id"], "full": False, "language": language, "schedule": schedule,
           "acts": [r], "monitorul": None}
    out = runner.merge_day(profile, out)
    return runner.finish(profile, out, state, dry_run=False, flag_ids={act["id"]}, by_hand=True,
                         watched=runner.watched_ids(acts))
