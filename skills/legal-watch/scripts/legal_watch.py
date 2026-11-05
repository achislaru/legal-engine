#!/usr/bin/env python3
"""legal-watch: law library, monitoring and contract re-review. Run with the engine's .venv/bin/python.

    legal_watch.py catalog [niches|categories|acts] [--countries MD,RO,EU]
    legal_watch.py suggest --niches a,b [--b2c] [--countries MD,RO,EU]
    legal_watch.py init --niches a,b --categories c,d [--acts p1|all|id,…] [--add id,…] [--b2c]
                        [--countries …] [--language ru|ro|en] [--engines urllib,playwright,command,firecrawl,host]
                        [--fetch-command CMD] [--schedule on-request|weekly|claude-schedule] [--force]
    legal_watch.py show
    legal_watch.py issues [--all]           the error log (open problems; --all with solved and per-site engines)
    legal_watch.py report                   write laws/report.html (also written after every run)
    legal_watch.py source add <act> (--doc-id ID | --celex CELEX) [--kind legis_md|just_ro|eurlex]
    legal_watch.py prune --runs-older DAYS [--apply]   list (or, with --apply, delete) old run folders
    legal_watch.py run [--acts all|p1|id,…] [--today YYYY-MM-DD] [--dry-run] [--no-gazette]
    legal_watch.py record --card <version-card.json> [--root <matter>] [--via host|firecrawl]
    legal_watch.py fetch --url <url> --out <file> [--engine firecrawl]
                        read one official page through the Firecrawl CLI for a conversation: saves only an
                        accepted page (.md for legis.md, .html for monitorul.gov.md), prints a short JSON; exit 0
                        saved, 2 not verified (the CLI's own output is never shown)
    legal_watch.py engines set <engine,…>   change only settings.engines (e.g. urllib,firecrawl,host to connect
                        Firecrawl, urllib,host to disconnect); acts, state and texts are kept
    legal_watch.py digest [--date YYYY-MM-DD]
    legal_watch.py index scan <contract> --jurisdiction MD|RO [--write] [--force]
    legal_watch.py index check | pending
    legal_watch.py index clear --contract <file> [--clause N] --matter <matter-id>
    legal_watch.py schedule plan|install|remove [--kind launchd|cron|claude-schedule]

Global: --profile <dir> (default: the profile of legal-workflow's config.json).
Exit codes: 0 ok (run: OK), 1 run: CHANGES / check: errors, 2 bad input, run: INCOMPLETE or fetch: not verified,
3 unexpected error.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shutil  # noqa: E402

from watch import clauses, issues, library as lib, manual, report, runner, schedule  # noqa: E402
from watch.fetchers import (BrowserBusy, FetchConfigError, FirecrawlFetcher, HostOnly, build_chain,  # noqa: E402
                            firecrawl_format, firecrawl_skip_error)

WORKFLOW_SCRIPTS = lib.SKILL.parent / "legal-workflow" / "scripts"


def resolve_profile(raw: str | None) -> Path:
    if raw:
        path = Path(raw).expanduser()
        lib.refuse_engine(path / "laws")
        return path
    sys.path.insert(0, str(WORKFLOW_SCRIPTS))
    try:
        import legal_profile
        return legal_profile.resolve_profile()[0]
    except ImportError as e:
        raise lib.WatchError("legal-workflow is not installed next to legal-watch; pass --profile") from e
    except Exception as e:  # noqa: BLE001 — the profile script raises its own typed errors
        raise lib.WatchError(f"cannot find the profile: {e}") from e


def _csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _watch(profile: Path):
    wl = lib.load_watchlist(lib.laws_dir(profile) / "watchlist.yaml")
    catalog, _ = lib.load_catalog()
    acts = lib.resolve_acts(wl, catalog, lib.load_state(profile))
    return wl, acts


def cmd_catalog(a) -> int:
    acts, niches = lib.load_catalog()
    countries = set(_csv(a.countries) or lib.JURISDICTIONS)
    if a.what == "niches":
        _print({k: v["label"] for k, v in niches["niches"].items()})
    elif a.what == "categories":
        _print({k: v["label"] for k, v in niches["categories"].items()})
    else:
        _print([{k: x.get(k) for k in ("id", "title", "jurisdiction", "priority", "status", "checked_on")}
                for x in acts.values() if x["jurisdiction"] in countries])
    return 0


def cmd_suggest(a) -> int:
    acts, niches = lib.load_catalog()
    _print(lib.suggest(niches, acts, _csv(a.niches), b2c=a.b2c, countries=_csv(a.countries) or list(lib.JURISDICTIONS)))
    return 0


def cmd_init(a) -> int:
    profile = resolve_profile(a.profile)
    path = lib.laws_dir(profile) / "watchlist.yaml"
    if path.exists() and not a.force:
        raise lib.WatchError(f"{path} exists; re-run with --force to replace it (the state and texts are kept)")
    acts, niches = lib.load_catalog()
    countries = _csv(a.countries) or list(lib.JURISDICTIONS)
    sug = lib.suggest(niches, acts, _csv(a.niches), b2c=a.b2c, countries=countries)
    chosen_cats = _csv(a.categories) or [c["category"] for c in sug["categories"]]
    unknown = [c for c in chosen_cats if c not in niches["categories"]]
    if unknown:
        raise lib.WatchError(f"unknown categories: {', '.join(unknown)}")
    ids = list(dict.fromkeys(i for c in chosen_cats for i in niches["categories"][c]["acts"]
                             if i in acts and acts[i]["jurisdiction"] in countries))
    if a.acts == "p1":
        ids = [i for i in ids if acts[i].get("priority") == "p1"]
    elif a.acts != "all":
        # Chosen from the whole catalog (`catalog acts`), not only from the chosen categories.
        ids = [i for i in _csv(a.acts) if i != "none"]
    extra = [i for i in _csv(a.add) if i not in ids]
    unknown = [i for i in ids + extra if i not in acts]
    if unknown:
        raise lib.WatchError(f"not in the catalog: {', '.join(unknown)}; an own act is added to the watchlist by "
                             "hand with title, jurisdiction and sources (setup.md)")
    ids += extra
    data = {"schema_version": 1,
            "settings": {"countries": countries, "language": a.language, "engines": _csv(a.engines),
                         "fetch_command": a.fetch_command, "schedule": a.schedule},
            "niches": _csv(a.niches), "categories": chosen_cats, "acts": [{"id": i} for i in ids]}
    lib.validate_watchlist(json.loads(json.dumps(data)))
    lib.write_atomic(path, lib.dump_watchlist(data))
    _print({"watchlist": str(path), "acts": len(ids), "categories": chosen_cats})
    return 0


def cmd_show(a) -> int:
    profile = resolve_profile(a.profile)
    wl, acts = _watch(profile)
    state = lib.load_state(profile)
    laws = lib.laws_dir(profile)
    _print({"settings": wl["settings"], "acts": [
        {"id": x["id"], "priority": x.get("priority"), "held": (x.get("current") or {}).get("label"),
         # why: ready to copy into a version card; without its date the checker cannot see an outdated holding
         "held_version": {"label": (x.get("current") or {}).get("label"),
                          "version_from": (x.get("current") or {}).get("in_force_from")} if x.get("current") else None,
         "next": x.get("next"), "repealed": x.get("repealed"),
         "checked_on": (state["acts"].get(x["id"]) or {}).get("checked_on"),
         "sha256": (state["acts"].get(x["id"]) or {}).get("sha256"),
         # why: the copies are evidence of what was read and when; a task re-reads the official text anyway
         "texts": [f"texts/{x['id']}/{n}" for n in report._texts(laws, x["id"])]} for x in acts],
        "last_runs": state["runs"][-5:], "contracts_to_review": clauses.pending(profile)})
    return 0


def cmd_issues(a) -> int:
    log = issues.load(resolve_profile(a.profile))
    if a.all:
        _print(log)
    else:
        _print({"open": issues.open_issues(log), "sites": issues.site_issues(log)})
    return 0


def cmd_report(a) -> int:
    profile = resolve_profile(a.profile)
    wl = lib.load_watchlist(lib.laws_dir(profile) / "watchlist.yaml")
    print(report.write(profile, wl["settings"]["language"]))
    return 0


SOURCE_GUESS = {"MD": "legis_md", "RO": "just_ro", "EU": "eurlex"}


def cmd_source(a) -> int:
    """Give an act its official source in the watchlist (the recipe for a `no_source` issue)."""
    profile = resolve_profile(a.profile)
    path = lib.laws_dir(profile) / "watchlist.yaml"
    wl = lib.load_watchlist(path)
    catalog, _ = lib.load_catalog()
    entry = next((x for x in wl["acts"] if x["id"] == a.act), None)
    if entry is None:
        raise lib.WatchError(f"{a.act} is not in the watchlist")
    jur = entry.get("jurisdiction") or (catalog.get(a.act) or {}).get("jurisdiction")
    kind = a.kind or SOURCE_GUESS.get(jur or "")
    if kind not in lib.SOURCE_KINDS:
        raise lib.WatchError(f"give --kind ({', '.join(sorted(lib.SOURCE_KINDS))})")
    key = lib.SOURCE_KINDS[kind]
    value = a.celex if key == "celex" else a.doc_id
    if not value:
        raise lib.WatchError(f"a {kind} source needs --{'celex' if key == 'celex' else 'doc-id'}")
    entry["sources"] = [x for x in entry.get("sources") or [] if x.get("kind") != kind] + [{"kind": kind, key: value}]
    data = {"schema_version": wl["schema_version"], "settings": wl["settings"], "niches": wl["niches"],
            "categories": wl["categories"], "acts": wl["acts"]}
    lib.validate_watchlist(json.loads(json.dumps(data)))
    lib.write_atomic(path, lib.dump_watchlist(data))
    _print({"act": a.act, "sources": entry["sources"], "next": f"legal_watch.py run --acts {a.act}"})
    return 0


def cmd_prune(a) -> int:
    """Old run folders only; the state, the error log and the text copies are never removed here."""
    profile = resolve_profile(a.profile)
    runs = lib.laws_dir(profile) / "runs"
    if a.runs_older < 30:
        raise lib.WatchError("--runs-older must be at least 30 days: the health line reads recent runs")
    limit = dt.date.today() - dt.timedelta(days=a.runs_older)
    old = []
    for p in sorted(runs.iterdir()) if runs.is_dir() else []:
        try:
            if p.is_dir() and dt.date.fromisoformat(p.name) < limit:
                old.append(p)
        except ValueError:
            continue   # not a run folder (schedule.log and the like)
    if a.apply:
        for p in old:
            lib.refuse_engine(p)
            shutil.rmtree(p)
    _print({"older_than": limit.isoformat(), "removed" if a.apply else "would_remove": [p.name for p in old]})
    return 0


def cmd_run(a) -> int:
    profile = resolve_profile(a.profile)
    wl, acts = _watch(profile)
    s = wl["settings"]
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    engines = [e for e in s["engines"] if e != "host"]
    with contextlib.ExitStack() as stack:
        if engines:
            # why: an engine a site kept refusing in recent runs goes last there (error log, issues.py)
            fetcher = build_chain(engines, command=s.get("fetch_command"),
                                  browser_dir=lib.laws_dir(profile) / ".browser", stack=stack,
                                  demote=issues.demoted(issues.load(profile), today))
        else:  # host only: nothing is fetched; every act is listed for the agent to check by hand
            fetcher = HostOnly()
        out = runner.run(profile, acts, fetcher, today, selector=a.acts, dry_run=a.dry_run,
                         language=s["language"], schedule=s["schedule"], scan_gazette=not a.no_gazette and bool(engines),
                         direct_http="urllib" in engines, mode="live" if engines else "host", engines=engines)
    sm = out["summary"]
    print(f"{out['result']} · checked {sm['checked']}/{sm['acts']} · not verified (p1): {sm['unverified_p1']} · "
          f"changes: {sm['changes']} · {lib.laws_dir(profile) / 'runs' / out['date'] / 'digest.md'}"
          + ("" if a.dry_run else f" · {report.path(profile)}"))
    return out["exit_code"]


def cmd_record(a) -> int:
    profile = resolve_profile(a.profile)
    wl, acts = _watch(profile)
    out = manual.record(profile, acts, Path(a.card), dt.date.today(), root=Path(a.root) if a.root else None,
                        language=wl["settings"]["language"], schedule=wl["settings"]["schedule"], via=a.via)
    rec = next(x for x in out["acts"] if x["act_id"] == json.loads(Path(a.card).read_text())["act"]["id"])
    _print({"act": rec["act_id"], "status": rec["status"], "checked": rec["checked"], "result": out["result"]})
    return 0


# The file suffix a saved page needs: `.md` makes manual.saved_text and check_version read it as markdown.
FETCH_SUFFIXES = {"markdown": (".md",), "rawHtml": (".html", ".htm")}


def cmd_fetch(a) -> int:
    """One official page through the Firecrawl CLI, for a conversation (the hand check route).

    why a command and not the bare `firecrawl scrape … -o`: the bare CLI shows its stdout and stderr to the agent
    (stderr may echo the user's setup), runs in the agent's folder (session files) and has no timeout. Here the
    same FirecrawlFetcher as monitoring runs it: argv only, temp folder, timeout, the allowlist, the anti-bot check,
    fixed errors. Only an accepted page is written; nothing of the CLI's own output is printed.
    """
    fmt = firecrawl_format(a.url)
    if fmt is None:
        _print({"url": a.url, "via": "firecrawl", "status": None, "error": firecrawl_skip_error(), "saved": None})
        return 2
    out = Path(a.out).expanduser()
    if out.suffix.lower() not in FETCH_SUFFIXES[fmt]:
        raise lib.WatchError(f"--out must end in {' or '.join(FETCH_SUFFIXES[fmt])} for a {fmt} page of this site")
    lib.refuse_engine(out)   # why: an official text saved for a matter belongs to the user's profile, never here
    res = FirecrawlFetcher(pause_range=(0, 0)).get(a.url)
    ok = not res.error and not res.blocked and res.status is not None and res.status < 400
    if not ok:
        _print({"url": a.url, "via": "firecrawl", "status": res.status,
                "error": res.error or res.blocked_reason or f"HTTP {res.status}", "saved": None})
        return 2
    content = res.markdown if fmt == "markdown" else res.html
    lib.write_atomic(out, content)
    _print({"url": a.url, "via": "firecrawl", "status": res.status, "format": fmt, "saved": str(out),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    return 0


def cmd_engines(a) -> int:
    """Change only `settings.engines` (connect or disconnect Firecrawl later); acts, state and texts stay."""
    profile = resolve_profile(a.profile)
    path = lib.laws_dir(profile) / "watchlist.yaml"
    wl = lib.load_watchlist(path)
    engines = _csv(a.engines)
    if len(set(engines)) != len(engines):
        raise lib.WatchError(f"an engine is named twice in {','.join(engines)}")
    data = {"schema_version": wl["schema_version"], "settings": {**wl["settings"], "engines": engines},
            "niches": wl["niches"], "categories": wl["categories"], "acts": wl["acts"]}
    lib.validate_watchlist(json.loads(json.dumps(data)))
    lib.write_atomic(path, lib.dump_watchlist(data))
    # why the hint: a launchd job keeps the PATH of its install; after installing the CLI it must be installed again
    _print({"engines": engines, "next": "if a weekly job is installed, run `legal_watch.py schedule install` again "
                                        "(cron: `schedule plan --kind cron`) so it gets the current PATH"})
    return 0


def cmd_digest(a) -> int:
    profile = resolve_profile(a.profile)
    runs = lib.laws_dir(profile) / "runs"
    day = a.date
    if day is None and runs.exists():
        day = max((p.name for p in runs.iterdir() if (p / "digest.md").exists()), default=None)
    if not day or not (runs / day / "digest.md").exists():
        raise lib.WatchError("no digest yet: run `legal_watch.py run` first")
    print((runs / day / "digest.md").read_text(encoding="utf-8"))
    return 0


def cmd_index(a) -> int:
    profile = resolve_profile(a.profile)
    if a.op == "scan":
        if not a.contract or not a.jurisdiction:
            raise lib.WatchError("index scan needs <contract> and --jurisdiction MD|RO")
        catalog, _ = lib.load_catalog()
        draft = clauses.scan(Path(a.contract), a.jurisdiction, clauses.catalog_codes(catalog))
        if a.write:
            _print({"written": str(clauses.save(profile, draft, force=a.force)), "clauses": len(draft["clauses"])})
        else:
            _print(draft)
        return 0
    if a.op == "check":
        # Only watched acts reach a clause: an act merely in the catalog is never monitored.
        known = {x["id"] for x in lib.load_watchlist(lib.laws_dir(profile) / "watchlist.yaml")["acts"]}
        report = {p.name: clauses.validate(ix, known) for p, ix in clauses.load_all(profile).items()}
        _print(report)
        return 1 if any(report.values()) else 0
    if a.op == "pending":
        _print(clauses.pending(profile))
        return 0
    if not a.contract_name:
        raise lib.WatchError("index clear needs --contract")
    _print({"cleared": clauses.clear(profile, a.contract_name, a.clause, a.matter)})
    return 0


def cmd_schedule(a) -> int:
    profile = resolve_profile(a.profile)
    if a.op == "plan":
        _print(schedule.plan(profile, a.kind))
    elif a.op == "install":
        if a.kind != "launchd":
            raise lib.WatchError(f"install handles launchd only; for {a.kind} use `schedule plan --kind {a.kind}`")
        _print(schedule.install(profile))
    else:
        _print(schedule.remove())
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("what", nargs="?", default="niches", choices=("niches", "categories", "acts"))
    c.add_argument("--countries")
    s = sub.add_parser("suggest")
    s.add_argument("--niches", required=True)
    s.add_argument("--b2c", action="store_true")
    s.add_argument("--countries")
    i = sub.add_parser("init")
    i.add_argument("--niches", default="")
    i.add_argument("--categories")
    i.add_argument("--acts", default="all")
    i.add_argument("--add")
    i.add_argument("--b2c", action="store_true")
    i.add_argument("--countries")
    i.add_argument("--language", default="ru", choices=lib.LANGUAGES)
    i.add_argument("--engines", default="urllib,host")
    i.add_argument("--fetch-command")
    i.add_argument("--schedule", default="weekly", choices=lib.SCHEDULES)
    i.add_argument("--force", action="store_true")
    sub.add_parser("show")
    iss = sub.add_parser("issues")
    iss.add_argument("--all", action="store_true")
    sub.add_parser("report")
    so = sub.add_parser("source")
    so.add_argument("op", choices=("add",))
    so.add_argument("act")
    so.add_argument("--doc-id")
    so.add_argument("--celex")
    so.add_argument("--kind", choices=sorted(lib.SOURCE_KINDS))
    pr = sub.add_parser("prune")
    pr.add_argument("--runs-older", type=int, required=True)
    pr.add_argument("--apply", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--acts", default="all")
    r.add_argument("--today")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-gazette", action="store_true")
    rc = sub.add_parser("record")
    rc.add_argument("--card", required=True)
    rc.add_argument("--root")
    # why: a page the agent read through Firecrawl is still a check by hand; the flag only records the tool
    rc.add_argument("--via", default="host", choices=manual.VIA)
    fe = sub.add_parser("fetch")
    fe.add_argument("--url", required=True)
    fe.add_argument("--out", required=True)
    fe.add_argument("--engine", default="firecrawl", choices=("firecrawl",))
    en = sub.add_parser("engines")
    en.add_argument("op", choices=("set",))
    en.add_argument("engines")
    d = sub.add_parser("digest")
    d.add_argument("--date")
    x = sub.add_parser("index")
    x.add_argument("op", choices=("scan", "check", "pending", "clear"))
    x.add_argument("contract", nargs="?")
    x.add_argument("--jurisdiction", choices=("MD", "RO"))
    x.add_argument("--write", action="store_true")
    x.add_argument("--force", action="store_true")
    x.add_argument("--contract", dest="contract_name")
    x.add_argument("--clause")
    x.add_argument("--matter")
    sc = sub.add_parser("schedule")
    sc.add_argument("op", choices=("plan", "install", "remove"))
    sc.add_argument("--kind", default="launchd", choices=schedule.KINDS)
    return ap


COMMANDS = {"catalog": cmd_catalog, "suggest": cmd_suggest, "init": cmd_init, "show": cmd_show, "run": cmd_run,
            "issues": cmd_issues, "report": cmd_report, "source": cmd_source, "prune": cmd_prune,
            "record": cmd_record, "digest": cmd_digest, "index": cmd_index, "schedule": cmd_schedule,
            "fetch": cmd_fetch, "engines": cmd_engines}


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        return COMMANDS[a.cmd](a)
    except (lib.WatchError, FetchConfigError, BrowserBusy) as e:
        print(f"legal_watch: {e}", file=sys.stderr)
        return 2
    except ImportError as e:
        print(f"legal_watch: a package is missing ({e.name}); run with the engine's .venv/bin/python, and for the "
              "playwright engine install it with `WITH_PLAYWRIGHT=1 ./install.sh`", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — exit 1 means "changes found": a crash must never look like it
        print(f"legal_watch: unexpected error {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
