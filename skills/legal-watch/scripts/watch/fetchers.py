"""Fetch engines for the monitoring adapters.

Adapters never depend on an engine: they take any object with `get(url) -> FetchResult`. The engines:

- `urllib`     — the standard library, free; plain GET. Several official portals refuse it (anti-bot pages, dropped
                 connections); that becomes an honest failure, never "unchanged".
- `playwright` — a local browser through Playwright (free; installed with `WITH_PLAYWRIGHT=1 ./install.sh`).
- `command`    — a command the user configured themselves (for example a paid scraping service wrapped in their
                 own script). The engine runs it with the URL and reads the page from stdout; it never sees, asks
                 for or stores a key.
- `firecrawl`  — the Firecrawl CLI (`firecrawl-cli`, a paid service) that the user installed and logged in to
                 themselves. A dedicated engine rather than a `command`, because it needs a format per site (markdown
                 for legis.md, the whole raw HTML for the MD Gazette), the target's real HTTP status from the JSON
                 metadata, its own timeout and a fixed error list. It runs only on the sites of
                 `FIRECRAWL_FORMAT_BY_HOST`; elsewhere it is skipped without a call. The CLI uses the user's own
                 login; the engine never sees, asks for, passes or stores a key.
- `host`       — not a fetcher: the agent opens the page with its own web tools and records a version card
                 (`legal_watch.py record`).

`ChainFetcher` tries the engines in order and falls to the next on an error or an anti-bot page; the result
names the engine that produced it (`via`). Rules for every engine: GET only, public pages, no forms, logins or
clicks; an anti-bot or CAPTCHA page is reported as blocked and never bypassed.
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import random
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse

USER_AGENT = "Mozilla/5.0 (compatible; legal-engine-watch/1.0)"
PAUSE_RANGE_S = (5.0, 15.0)   # politeness between requests to the same portals
TIMEOUT_S = 45
SETTLE_MS = 3_000
ENGINES = ("urllib", "playwright", "command", "firecrawl")

FIRECRAWL_BIN = "firecrawl"
FIRECRAWL_TIMEOUT_S = 120             # the CLI has no timeout flag of its own, so the engine sets one
# An allowlist, site → the format its reader is calibrated on. Firecrawl spends a credit per page, so it runs only
# where the reader can use what comes back: legis.md (markdown: the act card and the version bar) and the MD
# Gazette (`rawHtml`, the unmodified page: Firecrawl's `html` and `markdown` are trimmed to the "main content" and
# would cut the home table). Not EUR-Lex: Cellar reads EU acts for free. Not just.ro: its reader is not calibrated,
# so a credit would buy a "parse failed" and hide the Wayback fallback. Live calibration may add sites here.
FIRECRAWL_FORMAT_BY_HOST: dict[str, str] = {
    "www.legis.md": "markdown", "legis.md": "markdown",
    "monitorul.gov.md": "rawHtml", "www.monitorul.gov.md": "rawHtml",
}
_HTML_FORMATS = ("rawHtml", "html")

# Signs of an anti-bot check page. A match means blocked, without any interaction.
STRONG_MARKERS = (
    "just a moment", "doar un moment", "attention required", "cf-chl", "challenge-platform",
    "cf-browser-verification", "cf_chl_opt", "checking your browser", "efectuarea verificării de securitate",
    "verify you are human",
)
# CAPTCHA widgets also sit on ordinary pages (a newsletter form), so they count only on a near-empty page.
WIDGET_MARKERS = ("g-recaptcha", "h-captcha", "cf-turnstile")
WIDGET_PAGE_MAX_TEXT = 1500


class FetchConfigError(ValueError):
    """The engine settings are unusable (unknown engine, a command without `{url}`)."""


class FirecrawlOutputError(ValueError):
    """The Firecrawl CLI printed something that is not a page in the expected JSON shape.

    Its message is always one of the fixed `firecrawl: …` texts below, never text from the CLI.
    """


FC_UNREADABLE = "firecrawl: unreadable output"
FC_NO_CONTENT = "firecrawl: no page content"
FC_FAILED = "firecrawl: the service reported a failure"
FC_NO_STATUS = "firecrawl: page status not reported"
FC_NOT_FOUND = "firecrawl: CLI not found on PATH (npm i -g firecrawl-cli, then firecrawl login --browser)"
FC_NOT_LOGGED_IN = "firecrawl: not logged in (run firecrawl login --browser yourself)"
FC_NO_CREDITS = "firecrawl: out of credits (plan limit reached)"
# Errors that the next page of the same run would only repeat (and, logged out, each try would still cost a pause):
# remembered per fetcher, i.e. per run.
FC_FATAL = (FC_NOT_FOUND, FC_NOT_LOGGED_IN, FC_NO_CREDITS)
FC_BAD_URL = "firecrawl: only http(s) page URLs can be read"
# Prefix of the errors where the CLI never ran (no temp folder, the program cannot be executed): no request sent.
FC_NOT_STARTED = "firecrawl: could not start ("


def firecrawl_calls(attempts: list[dict]) -> int:
    """How many pages a run asked Firecrawl for, from the chain's attempts: the base of the digest's credit estimate.

    Not counted: errors that bill nothing (no CLI, not logged in, out of credits, a refused URL, a CLI that could not
    start); a skipped site leaves no attempt at all. A timeout or a failed read still counts: the service may have
    billed it. This is an estimate, never the bill: only the user's Firecrawl account shows what was charged.
    """
    free = set(FC_FATAL) | {FC_BAD_URL}

    def billable(a: dict) -> bool:
        err = a.get("error")
        return err not in free and not (err or "").startswith(FC_NOT_STARTED)
    return sum(1 for a in attempts or [] if a.get("via") == "firecrawl" and billable(a))


@dataclass
class FetchResult:
    url: str
    status: int | None            # HTTP status of the main document; None when there was no answer
    final_url: str | None = None
    title: str = ""
    html: str = ""
    text: str = ""                # visible text
    fetched_at: str = ""
    error: str | None = None      # network error or timeout
    blocked: bool = False         # anti-bot page or HTTP 403
    blocked_reason: str | None = None
    subresource_403: list[str] = field(default_factory=list)
    via: str = "urllib"
    markdown: str = ""            # when an engine returns markdown instead of HTML
    notes: list[str] = field(default_factory=list)


# What the adapters show instead of a page title (or heading) that came from the Firecrawl CLI.
HIDDEN_TITLE = "(not shown: reported by Firecrawl)"


def shown_value(r: FetchResult, value: str | None) -> str:
    """A value read from the page (title, heading) for an error text: quoted, or `HIDDEN_TITLE` for Firecrawl.

    why: errors go to run.json, issues.json, the digest and the report, and everything from the Firecrawl CLI is
    kept out of them (its own errors are fixed texts). The value stays in the result for the identity check;
    other engines keep showing it, it tells the user which page answered.
    """
    return HIDDEN_TITLE if r.via == "firecrawl" else repr(value)


def shown_title(r: FetchResult) -> str:
    return shown_value(r, r.title)


class Fetcher(Protocol):
    def get(self, url: str) -> FetchResult: ...


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def detect_challenge(status: int | None, title: str, html: str, text: str | None = None) -> str | None:
    """The reason a page is an anti-bot page, or None."""
    low_title = (title or "").lower()
    low_html = (html or "")[:200_000].lower()
    for m in STRONG_MARKERS:
        if m in low_title or m in low_html:
            return f"challenge marker: {m!r}"
    if text is not None and len(text.strip()) < WIDGET_PAGE_MAX_TEXT:
        for m in WIDGET_MARKERS:
            if m in low_html:
                return f"captcha widget on near-empty page: {m!r}"
    if status in (403, 429, 503) and ("cloudflare" in low_html or "cf-ray" in low_html):
        return f"HTTP {status} from Cloudflare"
    if status == 403:
        return "HTTP 403"
    return None


def html_to_text(html: str) -> str:
    """A rough innerText: scripts and styles dropped, tags to line breaks, entities decoded."""
    import html as _html
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    body = re.sub(r"(?s)<[^>]+>", "\n", body)
    body = _html.unescape(body)
    return re.sub(r"\n\s*\n+", "\n", body).strip()


def _title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def page_result(url: str, html: str, *, status: int | None = 200, via: str, final_url: str | None = None,
                fetched_at: str | None = None, markdown: str = "", title: str | None = None) -> FetchResult:
    """A FetchResult from a page body; the anti-bot check is applied here for every engine.

    `title`: an engine that knows the page title without HTML (Firecrawl metadata) passes it; it wins over
    the `<title>` of `html`.
    """
    text = html_to_text(html) if html else markdown
    title = title if title is not None else _title(html)
    # A markdown-only page (firecrawl, a `command` engine) is checked on its markdown: with an empty HTML body a
    # "Just a moment..." challenge page used to pass as content.
    reason = detect_challenge(status, title, html or markdown, text)
    return FetchResult(url=url, status=status, final_url=final_url or url, title=title, html=html, text=text,
                       fetched_at=fetched_at or now_iso(), blocked=reason is not None, blocked_reason=reason,
                       via=via, markdown=markdown)


class _Paced:
    """A pause before every request but the first: official portals are public services, not a load test."""

    def __init__(self, pause_range=PAUSE_RANGE_S, sleep: Callable[[float], None] = time.sleep):
        self.pause_range, self.sleep, self._n = pause_range, sleep, 0

    def pause(self) -> None:
        if self._n > 0 and self.pause_range[1] > 0:
            self.sleep(random.uniform(*self.pause_range))
        self._n += 1


class UrllibFetcher(_Paced):
    def __init__(self, *, timeout: float = TIMEOUT_S, opener=urllib.request.urlopen, **kw):
        super().__init__(**kw)
        self.timeout, self.opener = timeout, opener

    def get(self, url: str) -> FetchResult:
        self.pause()
        fetched_at = now_iso()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ro,en;q=0.8"})
        try:
            with self.opener(req, timeout=self.timeout) as r:
                body = r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
                return page_result(url, body, status=r.status, via="urllib", final_url=r.geturl(),
                                   fetched_at=fetched_at)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else ""
            res = page_result(url, body, status=e.code, via="urllib", fetched_at=fetched_at)
            if not res.blocked:
                res.error = f"HTTP {e.code}"
            return res
        except Exception as e:  # noqa: BLE001 — any network failure is "not verified" for the adapter
            return FetchResult(url=url, status=None, fetched_at=fetched_at, via="urllib",
                               error=f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}")


class CommandFetcher(_Paced):
    """Runs the user's own command; `{url}` in it is replaced by the page URL (shell-quoted).

    The command prints the page (HTML or markdown) to stdout. Its credentials, if any, live in the user's own
    setup; this class passes only the URL.
    """

    def __init__(self, command: str, *, timeout: float = 120, run=subprocess.run, **kw):
        super().__init__(**kw)
        if "{url}" not in command:
            raise FetchConfigError("fetch command must contain {url}")
        self.command, self.timeout, self.run = command, timeout, run

    def get(self, url: str) -> FetchResult:
        self.pause()
        fetched_at = now_iso()
        cmd = self.command.replace("{url}", shlex.quote(url))
        try:
            p = self.run(cmd, shell=True, capture_output=True, text=True, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=url, status=None, fetched_at=fetched_at, via="command",
                               error=f"command failed: {type(e).__name__}")
        if p.returncode != 0 or not p.stdout.strip():
            # stderr may echo the user's setup; only its length is kept, never its content.
            return FetchResult(url=url, status=None, fetched_at=fetched_at, via="command",
                               error=f"command exit {p.returncode}, {len(p.stdout)} bytes of output")
        out = p.stdout
        if "<html" in out[:2000].lower() or "<body" in out[:5000].lower():
            return page_result(url, out, via="command", fetched_at=fetched_at)
        return page_result(url, "", via="command", fetched_at=fetched_at, markdown=out)


def firecrawl_format(url: str, table: dict[str, str] | None = None) -> str | None:
    """The Firecrawl output format for a page of an allowlisted site, or None: Firecrawl is not used there."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:   # a malformed URL (bad port, bad IPv6) is simply not on the list
        return None
    return (FIRECRAWL_FORMAT_BY_HOST if table is None else table).get(host)


def firecrawl_skip_error(table: dict[str, str] | None = None) -> str:
    """The fixed error for a site Firecrawl is not used on; it names the allowlisted sites."""
    sites = sorted({h.removeprefix("www.") for h in (FIRECRAWL_FORMAT_BY_HOST if table is None else table)})
    return f"firecrawl: not used for this site (only {', '.join(sites)})"


def firecrawl_argv(binary: str, url: str, fmt: str) -> list[str]:
    """The exact CLI call. `--max-age 0`: a law check must read today's page, never Firecrawl's 2-day cache.

    No key, no `login`, `env` or `view-config`: the CLI uses the login the user made themselves. A URL that is not
    http(s) is refused, which also stops a value starting with `-` from being read as an option.
    """
    if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
        raise FetchConfigError(FC_BAD_URL)
    return [binary, "scrape", url, "--format", fmt, "--max-age", "0", "--json"]


def parse_firecrawl_json(stdout: str, fmt: str) -> tuple[str, dict]:
    """`--json` output → (content, metadata). Tolerates the API's `{"success":…, "data":{…}}` wrapper.

    Only the requested format counts: `html` is trimmed to the "main content" and may lack what the reader needs
    (EUR-Lex's forceIndicator), so it never stands in for `rawHtml`, nor the other way round. Output that is not
    JSON is never read as a page: an error printed with exit 0 would pass as content.
    """
    if not (stdout or "").strip():
        raise FirecrawlOutputError(FC_NO_CONTENT)
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise FirecrawlOutputError(FC_UNREADABLE) from e
    if not isinstance(data, dict):
        raise FirecrawlOutputError(FC_UNREADABLE)
    if data.get("success") is False:
        raise FirecrawlOutputError(FC_FAILED)
    if isinstance(data.get("data"), dict):
        data = data["data"]
    content = data.get(fmt)
    if not isinstance(content, str):
        raise FirecrawlOutputError(f"firecrawl: format {fmt} not returned")
    if not content.strip():
        raise FirecrawlOutputError(FC_NO_CONTENT)
    meta = data.get("metadata")
    return content, meta if isinstance(meta, dict) else {}


def firecrawl_status(meta: dict) -> int:
    """The target page's HTTP status from the metadata; missing or odd → error, never a made-up 200.

    A status of digits in a string ("403") is read as the number; a bool, a float or a value outside 100–599 is not
    a status.
    """
    v = meta.get("statusCode")
    if isinstance(v, str) and re.fullmatch(r"\s*[0-9]{3}\s*", v):
        v = int(v)
    if isinstance(v, int) and not isinstance(v, bool) and 100 <= v <= 599:
        return v
    raise FirecrawlOutputError(FC_NO_STATUS)


# stderr → a fixed message. stderr itself is never copied: it may echo the user's setup.
_FIRECRAWL_STDERR = (
    (("credit", "402"), FC_NO_CREDITS),
    (("not authenticated", "unauthorized", "401", "api key"), FC_NOT_LOGGED_IN),
    (("rate limit", "429"), "firecrawl: rate limited"),
)


class FirecrawlFetcher(_Paced):
    """The user's logged-in Firecrawl CLI, called with an argv list (never a shell).

    One instance serves one run (or one `legal_watch.py fetch`): it remembers a fatal error (no CLI, not logged in,
    out of credits) and answers every later page with it at once, without calling the CLI or pausing.
    """

    via = "firecrawl"

    def __init__(self, *, binary: str | None = None, timeout: float = FIRECRAWL_TIMEOUT_S,
                 formats: dict[str, str] | None = None, run=subprocess.run, which=shutil.which, **kw):
        super().__init__(**kw)
        self.binary, self.timeout, self.formats, self.run, self.which = binary, timeout, formats, run, which
        self.fatal: str | None = None

    def accepts(self, url: str) -> bool:
        """Whether Firecrawl is used for this page at all (allowlist). `ChainFetcher` skips it elsewhere."""
        return firecrawl_format(url, self.formats) is not None

    def _error(self, url: str, fetched_at: str, error: str) -> FetchResult:
        if error in FC_FATAL:
            self.fatal = error
        return FetchResult(url=url, status=None, fetched_at=fetched_at, via="firecrawl", error=error)

    def _call(self, argv: list[str]):
        """(completed process, None) or (None, fixed error). Only "could not start" errors mean no request was sent.

        why the split: the credit estimate leaves out a call that never started (no temp folder, the CLI vanished
        or cannot be executed), but keeps a timeout or a failure while running: the service may have billed those.
        """
        try:
            # A fresh temp working folder: the CLI may save session files where it runs, and they must land neither
            # in this repository nor in the user's legal profile.
            tmp = tempfile.TemporaryDirectory(prefix="legal-watch-fc-")
        except Exception as e:  # noqa: BLE001 — a full or read-only disk: "not verified", never a crash
            return None, f"{FC_NOT_STARTED}{type(e).__name__})"
        p = err = None
        try:
            with tmp as wd:
                try:
                    p = self.run(argv, capture_output=True, text=True, timeout=self.timeout, cwd=wd,
                                 stdin=subprocess.DEVNULL)
                except subprocess.TimeoutExpired:
                    err = f"firecrawl: timed out after {self.timeout:g} s"
                except OSError as e:   # subprocess raises OSError when the program cannot be executed at all
                    err = f"{FC_NOT_STARTED}{type(e).__name__})"
                except Exception as e:  # noqa: BLE001 — e.g. undecodable output: the call ran, so it may have billed
                    err = f"firecrawl: failed while running ({type(e).__name__})"
        except Exception:  # noqa: BLE001 — why: a temp folder that cannot be removed does not undo the call's answer
            pass
        if p is None and err is None:   # why: cleanup failed before an answer was kept (should not happen)
            err = "firecrawl: failed while running (cleanup)"
        return p, err

    def get(self, url: str) -> FetchResult:
        fetched_at = now_iso()
        fmt = firecrawl_format(url, self.formats)
        # why before the pause: a skipped site or a remembered fatal error sends no request, so it needs no pause
        if fmt is None:
            return self._error(url, fetched_at, firecrawl_skip_error(self.formats))
        if self.fatal:
            return self._error(url, fetched_at, self.fatal)
        binary = self.binary or self.which(FIRECRAWL_BIN)
        if not binary:
            return self._error(url, fetched_at, FC_NOT_FOUND)
        try:
            argv = firecrawl_argv(binary, url, fmt)
        except FetchConfigError as e:   # why: one odd URL is "not verified" for that act, never a crashed run
            return self._error(url, fetched_at, str(e))
        self.pause()
        p, err = self._call(argv)
        if err:
            return self._error(url, fetched_at, err)
        stdout, stderr = p.stdout or "", p.stderr or ""
        if p.returncode != 0:
            low = stderr.lower()
            msg = next((m for pats, m in _FIRECRAWL_STDERR if any(x in low for x in pats)),
                       f"firecrawl: exit {p.returncode}, {len(stderr)} bytes on stderr")
            return self._error(url, fetched_at, msg)
        try:
            content, meta = parse_firecrawl_json(stdout, fmt)
            # why: without the target's real status a challenge or error page could pass as a read act
            status = firecrawl_status(meta)
            # why inside the try: the metadata is CLI data too; a malformed URL makes urlparse raise with the value
            # in its message, which must never reach the agent, the run record or the error log
            final_url, title = firecrawl_page_meta(meta, url)
        except FirecrawlOutputError as e:   # its message is a fixed text, never the CLI's output
            return self._error(url, fetched_at, str(e))
        if fmt in _HTML_FORMATS:
            res = page_result(url, content, status=status, via="firecrawl", final_url=final_url,
                              fetched_at=fetched_at)
        else:
            res = page_result(url, "", status=status, via="firecrawl", final_url=final_url, fetched_at=fetched_at,
                              markdown=content, title=title)
        # Firecrawl exits 0 for a target 403/404 that still returned a page: the real status decides. Only 2xx is a
        # fresh page: a 1xx, a redirect it did not follow or a 304 "not modified" says nothing about today's text.
        if not res.blocked and not 200 <= status < 300:
            res.error = (f"HTTP {status} (reported by Firecrawl)" if status >= 400
                         else f"firecrawl: HTTP {status} (reported by Firecrawl, not a page)")
        return res


def firecrawl_page_meta(meta: dict, url: str) -> tuple[str, str | None]:
    """(final URL, title) from the metadata, or `FC_UNREADABLE`.

    A missing or non-http(s) final URL falls back to the requested one (as before); a URL that does not even parse
    (a bracket, a fullwidth slash, a bad port) is unreadable output. The parse error itself is dropped: its message
    quotes the value.
    """
    final, title = meta.get("url"), meta.get("title")
    if title is not None and not isinstance(title, str):
        title = None
    if not isinstance(final, str):
        return url, title
    try:
        parsed = urlparse(final)
        parsed.port   # noqa: B018 — raises on a bad port; the adapters read it later
    except ValueError:
        raise FirecrawlOutputError(FC_UNREADABLE) from None
    return (final if parsed.scheme in ("http", "https") and parsed.hostname else url), title


class BrowserBusy(RuntimeError):
    """Another monitoring run holds the browser profile."""


class PlaywrightFetcher(_Paced):
    """A context manager: one persistent browser profile per run (kept in the user's profile, never here)."""

    def __init__(self, profile_dir: Path, *, headless: bool = True, channel: str | None = None,
                 nav_timeout_ms: int = TIMEOUT_S * 1000, **kw):
        super().__init__(**kw)
        self.profile_dir, self.headless, self.channel = Path(profile_dir), headless, channel
        self.nav_timeout_ms = nav_timeout_ms
        self._pw = self._ctx = self._lock = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # imported here: tests and urllib runs need no Playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._lock = open(self.profile_dir.parent / (self.profile_dir.name + ".lock"), "a+")
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            self._lock.close()
            raise BrowserBusy(f"browser profile {self.profile_dir} is used by another run; run them one by one") from e
        self._pw = sync_playwright().start()
        opts = {"user_data_dir": str(self.profile_dir), "headless": self.headless, "accept_downloads": False,
                "locale": "ro-RO"}
        if self.channel:
            opts["channel"] = self.channel
        self._ctx = self._pw.chromium.launch_persistent_context(**opts)
        self._ctx.set_default_navigation_timeout(self.nav_timeout_ms)
        return self

    def __exit__(self, *exc):
        try:
            if self._ctx is not None:
                self._ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            if self._lock is not None:
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
                self._lock.close()
        return False

    def get(self, url: str) -> FetchResult:
        self.pause()
        fetched_at = now_iso()
        page = self._ctx.new_page()
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        sub403: list[str] = []
        page.on("response", lambda resp: sub403.append(resp.url)
                if resp.status == 403 and host in resp.url and resp.url != url else None)
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
            page.wait_for_timeout(SETTLE_MS)
            status = resp.status if resp is not None else None
            html, title = page.content(), page.title()
            try:
                text = page.inner_text("body", timeout=10_000)
            except Exception:  # noqa: BLE001
                text = ""
            reason = detect_challenge(status, title, html, text)
            return FetchResult(url=url, status=status, final_url=page.url, title=title, html=html, text=text,
                               fetched_at=fetched_at, blocked=reason is not None, blocked_reason=reason,
                               subresource_403=sub403, via="playwright")
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=url, status=None, fetched_at=fetched_at, via="playwright",
                               error=f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}",
                               subresource_403=sub403)
        finally:
            page.close()


class ChainFetcher:
    """Engines in order; the next one is tried when a page failed or was an anti-bot page.

    `demote`: site → engines to try last there (from the error log: they kept failing on that site, so waiting
    for them first on every act only costs time). A demoted engine still runs when nothing before it worked.
    Every engine tried is kept in `attempts` for the error log.
    """

    def __init__(self, fetchers: list[Fetcher], *, names: list[str] | None = None,
                 demote: dict[str, set[str]] | None = None):
        if not fetchers:
            raise FetchConfigError("no fetch engine configured")
        self.fetchers = fetchers
        self.names = names or [getattr(f, "via", f"engine{i}") for i, f in enumerate(fetchers)]
        self.demote = demote or {}
        self.attempts: list[dict] = []

    def _order(self, host: str | None) -> tuple[list[tuple[str, Fetcher]], list[str]]:
        pairs = list(zip(self.names, self.fetchers))
        late = self.demote.get(host or "", set())
        if not late or len(pairs) < 2:
            return pairs, []
        first = [p for p in pairs if p[0] not in late]
        return first + [p for p in pairs if p[0] in late], [n for n, _ in pairs if n in late]

    def get(self, url: str) -> FetchResult:
        host = urlparse(url).hostname
        pairs, moved = self._order(host)
        tried: list[str] = []
        res = None
        skipped = None
        for name, f in pairs:
            accepts = getattr(f, "accepts", None)
            if accepts is not None and not accepts(url):
                # why: an engine not used on this site (Firecrawl's allowlist) is no attempt: it costs nothing,
                # must not count as a failure there (demotion) and must not hide the result of the engine before it
                skipped = skipped or f
                continue
            res = f.get(url)
            ok = not res.error and not res.blocked and res.status is not None and res.status < 400
            self.attempts.append({"host": host, "via": res.via or name, "ok": ok, "http_status": res.status,
                                  "error": None if ok else (res.error or res.blocked_reason or f"HTTP {res.status}")})
            if ok:
                break
            tried.append(f"{res.via}: {res.error or res.blocked_reason or f'HTTP {res.status}'}")
        if res is None:   # every engine skipped this site: its own error says why, nothing was sent
            return skipped.get(url)
        if tried:
            res.notes = [f"engine failed, next tried: {t}" for t in tried if not t.startswith(res.via + ":")] \
                + list(res.notes)
        if moved:
            res.notes = [f"tried last on {host}: {', '.join(moved)} (refused there in recent runs, see the error log)"] \
                + list(res.notes)
        return res


class HostOnly:
    """The `host` engine alone: scripts fetch nothing, every act waits for a check by hand."""

    def get(self, url: str) -> FetchResult:
        return FetchResult(url=url, status=None, fetched_at=now_iso(), via="host",
                           error="engine 'host' only: no automatic reading; check by hand and record a version card")


class FixtureFetcher:
    """Tests and offline runs: url → FetchResult; an unknown URL is a fetch error."""

    def __init__(self, mapping: dict[str, FetchResult]):
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url not in self.mapping:
            return FetchResult(url=url, status=None, fetched_at="2026-11-04T07:00:00Z", via="fixture",
                               error="FixtureFetcher: no fixture for url")
        return self.mapping[url]


def fixture_result(url: str, html: str, *, status: int = 200, title: str | None = None, text: str | None = None,
                   via: str = "fixture", markdown: str = "") -> FetchResult:
    """A FetchResult from saved HTML (or markdown), as an engine would return it."""
    res = page_result(url, html, status=status, via=via, fetched_at="2026-11-04T07:00:00Z", markdown=markdown)
    if title is not None:
        res.title = title
    if text is not None:
        res.text = text
    reason = detect_challenge(status, res.title, html or markdown, res.text)
    res.blocked, res.blocked_reason = reason is not None, reason
    return res


def build_chain(engines: list[str], *, command: str | None = None, browser_dir: Path | None = None,
                stack=None, pause_range=PAUSE_RANGE_S, demote: dict[str, set[str]] | None = None) -> ChainFetcher:
    """Engines named in the watchlist → a ChainFetcher. `stack` is an ExitStack that owns the browser."""
    out: list[Fetcher] = []
    for name in engines:
        if name == "urllib":
            out.append(UrllibFetcher(pause_range=pause_range))
        elif name == "command":
            if not command:
                raise FetchConfigError("engine 'command' needs settings.fetch_command")
            out.append(CommandFetcher(command, pause_range=pause_range))
        elif name == "playwright":
            if stack is None or browser_dir is None:
                raise FetchConfigError("engine 'playwright' needs a browser profile folder")
            out.append(stack.enter_context(PlaywrightFetcher(browser_dir, pause_range=pause_range)))
        elif name == "firecrawl":
            out.append(FirecrawlFetcher(pause_range=pause_range))
        else:
            raise FetchConfigError(f"unknown engine {name!r}; allowed: {', '.join(ENGINES)}")
    return ChainFetcher(out, names=list(engines), demote=demote)
