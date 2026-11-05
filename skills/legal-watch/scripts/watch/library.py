"""The law library in the user's profile: the catalog shipped with the engine, the user's watchlist, the
machine state (versions held) and the text snapshots.

    <profile>/laws/watchlist.yaml   what the user chose (written by the wizard, editable by hand)
    <profile>/laws/state.json       what the engine holds per act (written only by the scripts)
    <profile>/laws/texts/<act>/     snapshots of official texts, one file per distinct text
    <profile>/laws/runs/<date>/     run.json and digest.md of each monitoring run
    <profile>/laws/issues.json      the error log (issues.py); laws/report.html, the page for the person (report.py)

How the skills use these layers: references/library.md.

The watchlist holds choices, the state holds facts read from official pages: keeping them apart lets the user
edit the watchlist without breaking the baseline, and a lost state only means the next run re-reads baselines.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
CATALOG_DIR = SKILL / "assets" / "catalog"
ACT_ID_RE = re.compile(r"^(md|ro|eu)\.[a-z]+\.[0-9a-z]+(?:[-.][0-9a-z]+)*$")
JURISDICTIONS = ("MD", "RO", "EU")
PRIORITIES = ("p1", "p2", "p3")
SOURCE_KINDS = {"legis_md": "doc_id", "just_ro": "doc_id", "eurlex": "celex"}
ENGINES = ("urllib", "playwright", "command", "firecrawl", "host")
SCHEDULES = ("on-request", "weekly", "claude-schedule")
LANGUAGES = ("ru", "ro", "en")
STATE_SCHEMA = 1
RUN_HISTORY = 30


class WatchError(ValueError):
    """The watchlist, the state or an argument is unusable; the message says what to fix."""


def today_iso() -> str:
    return _dt.date.today().isoformat()


ENGINE_ROOT = SKILL.parent.parent


def refuse_engine(path: Path) -> None:
    """why: a profile (or a link inside it: laws/, contracts/) pointing into the engine checkout would put the
    user's laws, state and contract indexes where a commit can publish them. Checked on the resolved target."""
    real, engine = Path(path).expanduser().resolve(), ENGINE_ROOT.resolve()
    if real == engine or engine in real.parents:
        raise WatchError(f"refusing to write {path}: it is inside the engine folder {engine}; the profile must "
                         "live outside it (default ~/legal-profile)")


def write_atomic(path: Path, text: str) -> None:
    """Write through a temporary file: a crash mid-write must not leave half a state file."""
    refuse_engine(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, data: object) -> None:
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise WatchError(f"{what} not found: {path}") from e
    except json.JSONDecodeError as e:
        raise WatchError(f"{what} is not valid JSON ({path}): {e}") from e
    if not isinstance(data, dict):
        raise WatchError(f"{what} must be a JSON object: {path}")
    return data


# ---------------------------------------------------------------- catalog

def load_catalog(catalog_dir: Path = CATALOG_DIR) -> tuple[dict[str, dict], dict]:
    """→ (acts by id, niches document)."""
    acts = read_json(Path(catalog_dir) / "acts.json", "act catalog")
    niches = read_json(Path(catalog_dir) / "niches.json", "niche catalog")
    return {a["id"]: a for a in acts.get("acts", [])}, niches


def suggest(niches_doc: dict, acts: dict[str, dict], niche_ids: list[str], *, b2c: bool,
            countries: list[str]) -> dict:
    """Categories and acts suggested for the chosen niches, filtered by the user's countries."""
    known = niches_doc.get("niches", {})
    unknown = [n for n in niche_ids if n not in known]
    if unknown:
        raise WatchError(f"unknown niche(s): {', '.join(unknown)}; see `legal_watch.py catalog niches`")
    cats: list[str] = list(niches_doc.get("general", []))
    if b2c:
        cats += niches_doc.get("b2c", [])
    for n in niche_ids:
        cats += known[n].get("categories", [])
    cats = list(dict.fromkeys(cats))
    wanted = {c.upper() for c in countries}
    out = []
    for c in cats:
        cat = niches_doc.get("categories", {}).get(c)
        if cat is None:
            raise WatchError(f"catalog: category {c!r} is used but not defined")
        ids = [i for i in cat.get("acts", []) if i in acts and acts[i]["jurisdiction"] in wanted]
        out.append({"category": c, "label": cat.get("label", {}), "acts": ids})
    return {"niches": niche_ids, "categories": out}


# ---------------------------------------------------------------- watchlist

def _yaml():
    try:
        import yaml
    except ImportError as e:  # the engine's .venv has it (requirements.txt)
        raise WatchError("PyYAML is missing: run the script with the engine's .venv/bin/python") from e
    return yaml


def default_settings() -> dict:
    return {"countries": ["MD", "RO", "EU"], "language": "ru", "engines": ["urllib"], "fetch_command": None,
            "schedule": "weekly"}


def load_watchlist(path: Path) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise WatchError(f"watchlist not found: {path} (run the setup steps `niches` and `laws`)") from e
    try:
        data = _yaml().safe_load(raw) or {}
    except Exception as e:  # noqa: BLE001 — any YAML error is a user-fixable file problem
        raise WatchError(f"watchlist is not valid YAML ({path}): {e}") from e
    return validate_watchlist(data)


def validate_watchlist(data: dict) -> dict:
    if not isinstance(data, dict):
        raise WatchError("watchlist must be a mapping")
    settings = {**default_settings(), **(data.get("settings") or {})}
    errs = []
    if not set(settings["countries"]) <= set(JURISDICTIONS) or not settings["countries"]:
        errs.append(f"settings.countries must be a non-empty subset of {list(JURISDICTIONS)}")
    if settings["language"] not in LANGUAGES:
        errs.append(f"settings.language must be one of {list(LANGUAGES)}")
    engines = settings["engines"]
    if not isinstance(engines, list) or not engines or any(e not in ENGINES for e in engines):
        errs.append(f"settings.engines must be a non-empty list from {list(ENGINES)}")
    elif "command" in engines and "{url}" not in str(settings.get("fetch_command") or ""):
        errs.append("settings.fetch_command must contain {url} when the engine 'command' is used")
    if settings["schedule"] not in SCHEDULES:
        errs.append(f"settings.schedule must be one of {list(SCHEDULES)}")
    acts = data.get("acts") or []
    if not isinstance(acts, list):
        errs.append("acts must be a list")
        acts = []
    seen = set()
    for i, a in enumerate(acts):
        if isinstance(a, str):
            a = {"id": a}
            acts[i] = a
        if not isinstance(a, dict) or not ACT_ID_RE.match(str(a.get("id", ""))):
            errs.append(f"acts[{i}]: id must look like ro.lege.53-2003 or md.cod.muncii")
            continue
        if a["id"] in seen:
            errs.append(f"acts[{i}]: duplicate id {a['id']}")
        seen.add(a["id"])
        if a.get("priority") is not None and a["priority"] not in PRIORITIES:
            errs.append(f"{a['id']}: priority must be one of {list(PRIORITIES)}")
        for s in a.get("sources") or []:
            key = SOURCE_KINDS.get(s.get("kind"))
            if key is None or not s.get(key):
                errs.append(f"{a['id']}: source {s} needs kind in {sorted(SOURCE_KINDS)} with its {key or 'id'}")
    if errs:
        raise WatchError("watchlist: " + "; ".join(errs))
    return {"schema_version": data.get("schema_version", 1), "settings": settings,
            "niches": list(data.get("niches") or []), "categories": list(data.get("categories") or []),
            "acts": acts}


def dump_watchlist(data: dict) -> str:
    head = ("# Laws the engine keeps and monitors (legal-watch). Edit by hand or re-run the wizard.\n"
            "# acts: ids from the engine catalog; an own act also needs title, jurisdiction and sources.\n")
    return head + _yaml().safe_dump(data, allow_unicode=True, sort_keys=False)


def resolve_acts(watchlist: dict, catalog: dict[str, dict], state: dict) -> list[dict]:
    """Watchlist entries completed from the catalog and the held baseline; unknown acts must be complete."""
    out = []
    for entry in watchlist["acts"]:
        base = dict(catalog.get(entry["id"], {}))
        act = {**base, **{k: v for k, v in entry.items() if v is not None}}
        if not base and not (act.get("title") and act.get("jurisdiction") in JURISDICTIONS):
            raise WatchError(f"{entry['id']} is not in the catalog: give title, jurisdiction and sources")
        act.setdefault("priority", "p2")
        held = (state.get("acts") or {}).get(act["id"]) or {}
        act["current"] = held.get("current")
        act["next"] = held.get("next")
        act["related"] = held.get("related")
        act["repealed"] = held.get("repealed")
        out.append(act)
    return out


def select(acts: list[dict], selector: str) -> list[dict]:
    if selector == "all":
        return list(acts)
    if selector in PRIORITIES:
        return [a for a in acts if a.get("priority") == selector]
    wanted = [s.strip() for s in selector.split(",") if s.strip()]
    by_id = {a["id"]: a for a in acts}
    unknown = [w for w in wanted if w not in by_id]
    if unknown:
        raise WatchError(f"not in the watchlist: {', '.join(unknown)}")
    return [by_id[w] for w in wanted]


# ---------------------------------------------------------------- state and snapshots

def laws_dir(profile: Path) -> Path:
    return Path(profile) / "laws"


def load_state(profile: Path) -> dict:
    path = laws_dir(profile) / "state.json"
    if not path.exists():
        return {"schema_version": STATE_SCHEMA, "acts": {}, "monitorul": {}, "runs": []}
    data = read_json(path, "watch state")
    if data.get("schema_version") != STATE_SCHEMA:
        raise WatchError(f"watch state {path} has schema {data.get('schema_version')!r}, expected {STATE_SCHEMA}")
    data.setdefault("acts", {})
    data.setdefault("monitorul", {})
    data.setdefault("runs", [])
    return data


def save_state(profile: Path, state: dict) -> None:
    state["runs"] = state.get("runs", [])[-RUN_HISTORY:]
    write_json(laws_dir(profile) / "state.json", state)


def save_snapshot(profile: Path, act_id: str, text: str, sha256: str, day: str) -> str | None:
    """Keep a copy of the official text when it differs from the last one kept; → path relative to laws/."""
    if not text or not sha256:
        return None
    folder = laws_dir(profile) / "texts" / act_id
    existing = sorted(folder.glob("*.txt")) if folder.exists() else []
    if existing and existing[-1].stem.endswith(sha256[:12]):
        return str(existing[-1].relative_to(laws_dir(profile)))
    path = folder / f"{day}-{sha256[:12]}.txt"
    write_atomic(path, text)
    return str(path.relative_to(laws_dir(profile)))
