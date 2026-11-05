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
                 for legis.md, the whole raw HTML elsewhere), the target's real HTTP status from the JSON metadata, its
                 own timeout and a fixed error list. The CLI uses the user's own login; the engine never sees, asks
                 for, passes or stores a key.
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
# `rawHtml` is the unmodified page: Firecrawl's `html` and `markdown` are trimmed to the "main content" by default,
# which would cut the EUR-Lex <title>/forceIndicator and the Gazette home table the parsers need.
FIRECRAWL_DEFAULT_FORMAT = "rawHtml"
# Sites whose parser is calibrated on Firecrawl markdown (legis.md: the act card and the version bar).
FIRECRAWL_FORMAT_BY_HOST: dict[str, str] = {"www.legis.md": "markdown", "legis.md": "markdown"}
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
    """The Firecrawl CLI printed something that is not a page in the expected JSON shape."""


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


def firecrawl_format(url: str, table: dict[str, str] | None = None) -> str:
    """The Firecrawl output format for a page: per site from the table, else the whole raw HTML."""
    host = (urlparse(url).hostname or "").lower()
    return (FIRECRAWL_FORMAT_BY_HOST if table is None else table).get(host, FIRECRAWL_DEFAULT_FORMAT)


def firecrawl_argv(binary: str, url: str, fmt: str) -> list[str]:
    """The exact CLI call. `--max-age 0`: a law check must read today's page, never Firecrawl's 2-day cache.

    No key, no `login`, `env` or `view-config`: the CLI uses the login the user made themselves. A URL that is not
    http(s) is refused, which also stops a value starting with `-` from being read as an option.
    """
    if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
        raise FetchConfigError("firecrawl: only http(s) page URLs can be read")
    return [binary, "scrape", url, "--format", fmt, "--max-age", "0", "--json"]


def parse_firecrawl_json(stdout: str, fmt: str) -> tuple[str, dict]:
    """`--json` output → (content, metadata). Tolerates the API's `{"success":…, "data":{…}}` wrapper."""
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise FirecrawlOutputError("firecrawl: output is not JSON") from e
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        raise FirecrawlOutputError("firecrawl: JSON output is not an object")
    # rawHtml and html are both whole-document HTML for the parsers; the other one is a usable fallback.
    keys = [fmt] + ([k for k in _HTML_FORMATS if k != fmt] if fmt in _HTML_FORMATS else [])
    content = next((data[k] for k in keys if isinstance(data.get(k), str) and data[k].strip()), "")
    if not content:
        raise FirecrawlOutputError(f"firecrawl: no {fmt} content in the output")
    meta = data.get("metadata")
    return content, meta if isinstance(meta, dict) else {}


# stderr → a fixed message. stderr itself is never copied: it may echo the user's setup.
_FIRECRAWL_STDERR = (
    (("credit", "402"), "firecrawl: out of credits (plan limit reached)"),
    (("not authenticated", "unauthorized", "401", "api key"),
     "firecrawl: not logged in (run firecrawl login --browser yourself)"),
    (("rate limit", "429"), "firecrawl: rate limited"),
)


class FirecrawlFetcher(_Paced):
    """The user's logged-in Firecrawl CLI, called with an argv list (never a shell)."""

    via = "firecrawl"

    def __init__(self, *, binary: str | None = None, timeout: float = FIRECRAWL_TIMEOUT_S,
                 formats: dict[str, str] | None = None, run=subprocess.run, which=shutil.which, **kw):
        super().__init__(**kw)
        self.binary, self.timeout, self.formats, self.run, self.which = binary, timeout, formats, run, which

    def _error(self, url: str, fetched_at: str, error: str) -> FetchResult:
        return FetchResult(url=url, status=None, fetched_at=fetched_at, via="firecrawl", error=error)

    def get(self, url: str) -> FetchResult:
        self.pause()
        fetched_at = now_iso()
        binary = self.binary or self.which(FIRECRAWL_BIN)
        if not binary:
            return self._error(url, fetched_at, "firecrawl: CLI not found on PATH "
                                                "(npm i -g firecrawl-cli, then firecrawl login --browser)")
        fmt = firecrawl_format(url, self.formats)
        argv = firecrawl_argv(binary, url, fmt)
        try:
            # A fresh temp working folder: the CLI may save session files where it runs, and they must land neither
            # in this repository nor in the user's legal profile.
            with tempfile.TemporaryDirectory(prefix="legal-watch-fc-") as wd:
                p = self.run(argv, capture_output=True, text=True, timeout=self.timeout, cwd=wd,
                             stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return self._error(url, fetched_at, f"firecrawl: timed out after {self.timeout:g} s")
        except Exception as e:  # noqa: BLE001 — a missing node, a permission error: "not verified", never a crash
            return self._error(url, fetched_at, f"firecrawl: could not start ({type(e).__name__})")
        stdout, stderr = p.stdout or "", p.stderr or ""
        if p.returncode != 0:
            low = stderr.lower()
            msg = next((m for pats, m in _FIRECRAWL_STDERR if any(x in low for x in pats)),
                       f"firecrawl: exit {p.returncode}, {len(stderr)} bytes on stderr")
            return self._error(url, fetched_at, msg)
        notes: list[str] = []
        try:
            content, meta = parse_firecrawl_json(stdout, fmt)
        except FirecrawlOutputError:
            if not stdout.strip():
                return self._error(url, fetched_at, "firecrawl: no page content")
            try:
                parsed = json.loads(stdout)
            except ValueError:
                pass
            else:
                # Valid JSON without the page is never read as a page: the JSON text would pass as markdown.
                return self._error(url, fetched_at, "firecrawl: no page content" if isinstance(parsed, dict)
                                   else "firecrawl: unreadable output")
            # Not JSON (a CLI that prints the raw page): read it like the `command` engine does.
            notes.append("firecrawl: output was not JSON; status not reported")
            low = stdout.lower()
            if "<html" in low[:2000] or "<body" in low[:5000]:
                res = page_result(url, stdout, via="firecrawl", fetched_at=fetched_at)
            else:
                res = page_result(url, "", via="firecrawl", fetched_at=fetched_at, markdown=stdout)
            res.notes.extend(notes)
            return res
        status = meta.get("statusCode")
        if not isinstance(status, int) or isinstance(status, bool):
            status = 200
            notes.append("status not reported by Firecrawl")
        final = meta.get("url")
        final_url = final if isinstance(final, str) and urlparse(final).scheme in ("http", "https") else url
        title = meta.get("title") if isinstance(meta.get("title"), str) else None
        if fmt in _HTML_FORMATS:
            res = page_result(url, content, status=status, via="firecrawl", final_url=final_url,
                              fetched_at=fetched_at)
        else:
            res = page_result(url, "", status=status, via="firecrawl", final_url=final_url, fetched_at=fetched_at,
                              markdown=content, title=title)
        # Firecrawl exits 0 for a target 403/404 that still returned a page: the real status decides.
        if res.status is not None and res.status >= 400 and not res.blocked:
            res.error = f"HTTP {res.status} (reported by Firecrawl)"
        res.notes.extend(notes)
        return res


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
        for name, f in pairs:
            res = f.get(url)
            ok = not res.error and not res.blocked and res.status is not None and res.status < 400
            self.attempts.append({"host": host, "via": res.via or name, "ok": ok, "http_status": res.status,
                                  "error": None if ok else (res.error or res.blocked_reason or f"HTTP {res.status}")})
            if ok:
                break
            tried.append(f"{res.via}: {res.error or res.blocked_reason or f'HTTP {res.status}'}")
        if tried and res is not None:
            res.notes = [f"engine failed, next tried: {t}" for t in tried if not t.startswith(res.via + ":")] \
                + list(res.notes)
        if moved and res is not None:
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
