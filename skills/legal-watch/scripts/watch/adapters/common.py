"""Helpers shared by the page adapters: where the page of an act is, and how a markdown page becomes text.

Kept apart from the adapters so that `just_ro` and `legis_md` do not import each other.
"""
from __future__ import annotations

import re

from ..fetchers import FetchResult

_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def source_doc_id(act: dict, kind: str) -> str | None:
    """The document id of the act's first source of `kind` (a page of that portal), or None."""
    for s in act.get("sources") or []:
        if s.get("kind") == kind and s.get("doc_id"):
            return str(s["doc_id"])
    return None


def is_markdown(r: FetchResult) -> bool:
    """The engine returned markdown instead of HTML (the `firecrawl` or a user `command` engine): the markdown parsers apply."""
    return bool(r.markdown) and not r.html


def md_to_text(md: str) -> str:
    """Markdown → plain text close to a browser's innerText (for parsing and the snapshot hash).

    Links keep only their label: on legis.md the version bar is a list of links (`- [25-10-2025](…)`), and
    the bar parser reads the bare dates.
    """
    t = md or ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = _MD_LINK.sub(r"\1", t)
    t = t.replace("\\_", "_")
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    t = re.sub(r"\*\*|__", "", t)
    t = re.sub(r"(?<![\w])_(?=\S)|(?<=\S)_(?![\w])", "", t)
    t = re.sub(r"(?m)^\s*\|?\s*-{3,}\s*(\|\s*-{3,}\s*)*\|?\s*$", "", t)
    t = re.sub(r"\s*\|\s*", " | ", t)
    t = re.sub(r"_{3,}", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def page_text(r: FetchResult) -> str:
    """The text the parsers read: the visible text of an HTML page, or the markdown turned into text."""
    return md_to_text(r.markdown) if is_markdown(r) else (r.text or "")
