"""Scheduled monitoring: a weekly local job (launchd on macOS, cron elsewhere) or a Claude scheduled task.

Nothing is installed silently: `plan` only shows what would run; `install` writes the launchd job after the
user agreed in chat; cron and Claude tasks are printed for the user to add, because editing someone's crontab
or cloud tasks is their act.

PATH: launchd and cron start the job with a minimal PATH (`/usr/bin:/bin`), where the `firecrawl` CLI is not found;
it is also a Node script (`#!/usr/bin/env node`), so `node` must be on PATH too. The job therefore gets a PATH built
at plan/install time from the folders of `firecrawl` and `node`, then the usual system folders. It may show a
home-folder path: it goes only to stdout and the user's own LaunchAgents, never into the repository.
"""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import library as lib

LABEL = "com.legal-engine.watch"
WEEKDAY, HOUR, MINUTE = 1, 9, 0          # Monday 09:00 local time: the Gazettes of the week before are out
KINDS = ("launchd", "cron", "claude-schedule")
SYSTEM_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")


def engine_python() -> Path:
    venv = lib.SKILL.parents[1] / ".venv" / "bin" / "python"
    return venv if venv.exists() else Path(sys.executable)


def command(profile: Path) -> list[str]:
    return [str(engine_python()), str(lib.SKILL / "scripts" / "legal_watch.py"), "--profile", str(profile), "run"]


def launch_path(which=shutil.which) -> str:
    """PATH for the scheduled job: the folders of `firecrawl` and `node` (when found), then the system folders."""
    dirs = [os.path.dirname(p) for p in (which("firecrawl"), which("node")) if p]
    return ":".join(dict.fromkeys(d for d in [*dirs, *SYSTEM_PATH] if d))


def plist(profile: Path, *, which=shutil.which) -> bytes:
    log = str(lib.laws_dir(profile) / "runs" / "schedule.log")
    return plistlib.dumps({
        "Label": LABEL, "ProgramArguments": command(profile),
        "EnvironmentVariables": {"PATH": launch_path(which)},
        "StartCalendarInterval": {"Weekday": WEEKDAY, "Hour": HOUR, "Minute": MINUTE},
        "StandardOutPath": log, "StandardErrorPath": log, "RunAtLoad": False})


def plan(profile: Path, kind: str, *, which=shutil.which) -> dict:
    if kind not in KINDS:
        raise lib.WatchError(f"schedule kind must be one of {list(KINDS)}")
    cmd = " ".join(shlex.quote(c) for c in command(profile))
    if kind == "launchd":
        return {"kind": kind, "file": str(Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"),
                "when": "every Monday 09:00", "command": cmd, "path": launch_path(which)}
    if kind == "cron":
        path = shlex.quote(launch_path(which))
        return {"kind": kind, "line": f"{MINUTE} {HOUR} * * {WEEKDAY} PATH={path} {cmd} >> "
                                      f"{shlex.quote(str(lib.laws_dir(profile) / 'runs' / 'schedule.log'))} 2>&1",
                "how": "add the line with `crontab -e`"}
    return {"kind": kind, "how": "create a weekly Claude scheduled task (/schedule) with this prompt",
            "prompt": "Run the law monitoring of my legal profile (legal-watch, `legal_watch.py run`), then "
                      "check by hand every act it reports as not verified and give me the digest."}


def install(profile: Path, *, run=subprocess.run, home: Path | None = None, which=shutil.which) -> dict:
    """Write and load the launchd job (macOS only). Re-running replaces the job, never duplicates it."""
    if sys.platform != "darwin":
        raise lib.WatchError("launchd exists only on macOS; use `schedule plan --kind cron` instead")
    path = (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    (lib.laws_dir(profile) / "runs").mkdir(parents=True, exist_ok=True)
    run(["launchctl", "unload", str(path)], capture_output=True)   # absent job: harmless error, ignored
    path.write_bytes(plist(profile, which=which))
    p = run(["launchctl", "load", str(path)], capture_output=True, text=True)
    if p.returncode != 0:
        raise lib.WatchError(f"launchctl load failed (exit {p.returncode}): {p.stderr.strip()[:200]}")
    return {"installed": str(path), "when": "every Monday 09:00"}


def remove(*, run=subprocess.run, home: Path | None = None) -> dict:
    path = (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if not path.exists():
        return {"removed": None}
    run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    return {"removed": str(path)}
