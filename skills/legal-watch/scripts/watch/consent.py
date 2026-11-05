"""The user's consent to Firecrawl, read from the setup step `reading` of the profile.

Firecrawl is a paid service, so the scripts check the consent themselves instead of trusting the agent to read the
note: `fetch` needs `conversation: on`, adding the `firecrawl` engine and a monitoring run that calls it need
`monitoring: on`. The row is written by the wizard through `legal_profile.py step set reading` (contract:
`legal-workflow/references/profile.md`); its note grammar is `conversation: on|off; monitoring: on|off`, optionally
followed by `waiting: <what>`.

Only a single `done` row counts. No file, no row (a profile from 1.1), more than one `reading` row, a `pending` or
`skipped` row, a part that is not `on`, or a file that cannot be read all mean "not allowed": the scripts fail closed, never open.
"""
from __future__ import annotations

from pathlib import Path

STATUS_FILE = Path("context") / "integration-status.md"
STEP = "reading"
PARTS = ("conversation", "monitoring")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def note_parts(note: str) -> dict[str, str]:
    """`conversation: on; monitoring: off; waiting: cli login` → {"conversation": "on", …} (keys lowercased)."""
    out: dict[str, str] = {}
    for part in note.split(";"):
        key, sep, value = part.partition(":")
        if sep:
            out[key.strip().lower()] = value.strip().lower()
    return out


def reading(profile: Path) -> dict[str, bool]:
    """{"conversation": bool, "monitoring": bool}: which uses of Firecrawl the user allowed (both False if none)."""
    allowed = {p: False for p in PARTS}
    path = Path(profile) / STATUS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    except (OSError, UnicodeDecodeError):   # why: an unreadable file is no consent, never a crash of the run
        return allowed
    rows = [_cells(line) for line in lines if line.lstrip().startswith("|")]
    rows = [cells for cells in rows if cells[0] == STEP]
    # why exactly one: with two rows (a hand edit, an old writer) it is unclear which one is the user's current
    # answer, and picking one could keep Firecrawl on after a withdrawal. The wizard's next write leaves one row.
    if len(rows) != 1:
        return allowed
    cells = rows[0]
    state = cells[1].lower() if len(cells) > 1 else ""   # only `done` is consent
    parts = note_parts(cells[3]) if len(cells) > 3 else {}
    return {p: state == "done" and parts.get(p) == "on" for p in PARTS}


def allowed(profile: Path, part: str) -> bool:
    if part not in PARTS:
        raise ValueError(f"unknown Firecrawl use {part!r}; known: {', '.join(PARTS)}")
    return reading(profile)[part]
