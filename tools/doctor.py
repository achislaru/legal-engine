#!/usr/bin/env python3
"""Check that this computer can run the legal engine (stdlib only, read-only).

    python3 tools/doctor.py     # report; exit 0 = all required parts present, 1 = something required is missing

Required: every engine skill linked into the skills folder, python3 >= 3.10, the engine's Python
environment (.venv with the document packages). Optional parts (local tools, Playwright Chromium, the
Firecrawl CLI) are reported with what they serve; they never make the engine "not ready".
The user's profile is reported, not required: the setup wizard creates it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# why: the profile contract belongs to the legal-workflow skill; doctor reuses its lookup instead of a copy.
sys.path.insert(0, str(ROOT / "skills" / "legal-workflow" / "scripts"))
import legal_profile  # noqa: E402
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", Path.home() / ".claude" / "skills"))
CONFIG = legal_profile.CONFIG
DEFAULT_PROFILE = legal_profile.DEFAULT_PROFILE
VENV_PY = ROOT / ".venv" / "bin" / "python"
# why: import names differ from package names (python-docx → docx, PyYAML → yaml).
VENV_IMPORTS = ("docx", "lxml", "pypdf", "pdfplumber", "yaml")
OPTIONAL_CMDS = {
    "soffice": "LibreOffice: render DOCX to PDF for a visual check (or use Word)",
    "pdftoppm": "Poppler: PDF pages to images for the visual check",
    "tesseract": "OCR of scanned contracts (needs the ron / rus / eng language packs)",
    "uv": "./install.sh builds the Python environment with it",
}
PLAYWRIGHT_CACHES = (Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# why "may read, no guarantee": whether Firecrawl gets past a site's anti-bot check is not promised by anyone;
# the scripts (scheduled monitoring) need the CLI, a hosted MCP connection does not serve them.
FIRECRAWL_LINES = {
    "logged-in": (True, "Firecrawl CLI", "logged in: may read official pages that refuse plain requests, "
                  "no guarantee (paid service you connected)"),
    "not-logged-in": (None, "Firecrawl CLI", "installed, not logged in: run firecrawl login --browser yourself"),
    "unknown": (None, "Firecrawl CLI", "installed, login state unknown: run firecrawl --status yourself"),
    "absent": (None, "Firecrawl CLI", "optional: may read official pages that refuse plain requests, no guarantee; "
               "monitoring scripts need this CLI: npm i -g firecrawl-cli, then firecrawl login --browser"),
}
# A status line that says "logged in": only symbols or spaces (a bullet, a tick) before the word.
FIRECRAWL_OK_LINE = re.compile(r"^[\W_]*authenticated\b", re.M)
FIRECRAWL_LOGGED_OUT = ("not authenticated", "unauthenticated")
FIRECRAWL_CONTRARY = FIRECRAWL_LOGGED_OUT + ("fail", "error", "invalid")


def engine_skills(root: Path = ROOT) -> list[str]:
    base = root / "skills"
    return sorted(p.name for p in base.iterdir() if (p / "SKILL.md").is_file()) if base.is_dir() else []


def profile_dir(config: Path = CONFIG) -> tuple[Path, str]:
    """(profile folder, where the path came from). A broken config is reported, never guessed around."""
    try:
        return legal_profile.resolve_profile(config)
    except legal_profile.LegalProfileError as exc:
        raise SystemExit(str(exc)) from exc


def line(ok: bool | None, what: str, note: str = "") -> None:
    tag = {True: "OK  ", False: "MISS", None: "--  "}[ok]
    print(f"{tag} {what}" + (f" — {note}" if note else ""))


def venv_ready(py: Path = VENV_PY) -> bool:
    if not py.is_file():
        return False
    code = "import " + ", ".join(VENV_IMPORTS)
    return subprocess.run([str(py), "-c", code], capture_output=True).returncode == 0


def playwright_ready(py: Path = VENV_PY, caches: tuple[Path, ...] = PLAYWRIGHT_CACHES) -> bool:
    """The browser engine runs only with both parts: the Python package in .venv and a downloaded Chromium.
    why: a Chromium left by another tool in the shared cache made doctor say OK while the engine failed to import."""
    chromium = any(c.is_dir() and any(c.glob("chromium*")) for c in caches)
    if not (chromium and py.is_file()):
        return False
    return subprocess.run([str(py), "-c", "import playwright"], capture_output=True).returncode == 0


def firecrawl_cli(which=shutil.which, run=subprocess.run, timeout: float = 20) -> str:
    """Login state of the optional Firecrawl CLI: "absent", "logged-in", "not-logged-in" or "unknown".

    why `--status` only: it prints the login state and the credits left, never the key (the CLI's status.ts).
    Still, its output is only matched here and then dropped: it is never printed, logged or returned, so nothing
    the CLI says can leak into a report. `view-config`, `env` and `--api-key` are never used, and neither the
    FIRECRAWL_API_KEY variable nor the CLI's credentials file is read: the engine never touches the key.
    """
    path = which("firecrawl")
    if not path:
        return "absent"
    try:
        done = run([path, "--status"], capture_output=True, text=True, timeout=timeout,
                   stdin=subprocess.DEVNULL)
        text = ANSI.sub("", f"{done.stdout or ''}\n{done.stderr or ''}").lower()
        code = done.returncode
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        # why: a hung, broken or odd CLI is reported as "unknown", never as a doctor crash.
        return "unknown"
    # why strict: this line decides whether the wizard offers Firecrawl for monitoring. A substring match took
    # "Unauthenticated" and "authenticated request failed" for a login; anything unsure stays "unknown".
    if any(x in text for x in FIRECRAWL_LOGGED_OUT):
        return "not-logged-in"
    if code == 0 and FIRECRAWL_OK_LINE.search(text) and not any(x in text for x in FIRECRAWL_CONTRARY):
        return "logged-in"
    return "unknown"


def open_watch_issues(profile: Path) -> int:
    """Open problems in the monitoring error log (legal-watch issues.json); 0 when there is none or it is broken."""
    try:
        log = json.loads((profile / "laws" / "issues.json").read_text(encoding="utf-8"))
        return sum(1 for e in (log.get("acts") or {}).values() if e.get("state") == "open")
    except (OSError, ValueError, AttributeError):
        return 0


def engine_version(root: Path = ROOT) -> str:
    """Name and version from VENDOR.json, so a bug report can say which release is installed."""
    try:
        v = json.loads((root / "VENDOR.json").read_text(encoding="utf-8"))
        return f"{v['name']} {v['version']} ({v['released']})"
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown version (VENDOR.json missing or unreadable)"


def main() -> int:
    missing = 0
    print(f"engine: {engine_version()}")
    print(f"skills folder: {SKILLS_DIR}")
    skills = engine_skills()
    if not skills:
        line(None, "engine skills", "none in this repo yet")
    for name in skills:
        dst = SKILLS_DIR / name
        ok = (dst / "SKILL.md").is_file()
        own = dst.is_symlink() and dst.resolve() == (ROOT / "skills" / name).resolve()
        line(ok, f"skill {name}", "this repo" if own else ("another copy" if ok else "run ./install.sh"))
        missing += not ok
    py_ok = sys.version_info >= (3, 10)
    line(py_ok, f"python3 {sys.version.split()[0]}", "3.10 or newer")
    missing += not py_ok
    env_ok = venv_ready()
    line(env_ok, "Python environment .venv (python-docx, lxml, pypdf, pdfplumber, PyYAML)",
         "" if env_ok else "run ./install.sh")
    missing += not env_ok
    for cmd, why in OPTIONAL_CMDS.items():
        line(True if shutil.which(cmd) else None, cmd, why)
    browser = playwright_ready()
    line(True if browser else None, "Playwright Chromium",
         "free engine for scheduled law monitoring; WITH_PLAYWRIGHT=1 ./install.sh")
    line(*FIRECRAWL_LINES[firecrawl_cli()])   # optional: never counted as missing
    prof, source = profile_dir()
    ready = (prof / "context" / "integration-status.md").is_file()
    line(True if ready else None, f"profile {prof}", source if ready else f"{source}; the setup wizard creates it")
    n = open_watch_issues(prof)
    if n:   # informational: a site that refuses access does not make the engine "not ready"
        line(None, f"law monitoring: {n} open problem(s)", f"see {prof / 'laws' / 'report.html'}")
    print("READY" if not missing else f"NOT READY: {missing} required part(s) missing")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
