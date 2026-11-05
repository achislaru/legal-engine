# Fetch engines and the schedule

## Engines (`settings.engines`, tried in order)

| Engine | Cost | What it needs | Honest limits |
|---|---|---|---|
| `urllib` | free | nothing (Python standard library) | several official portals block it or drop the connection: those acts end "not verified" |
| `playwright` | free | `WITH_PLAYWRIGHT=1 ./install.sh` (a local browser) | anti-bot pages are never bypassed; slower; the browser profile lives in `laws/.browser/` |
| `command` | the user's choice (for example a paid reading service) | `settings.fetch_command`: the user's own command with `{url}`, printing the page (HTML or markdown) to stdout | the user sets up the service and its key themselves; the engine passes only the URL and never reads, asks for or stores a key |
| `firecrawl` | the user's Firecrawl plan (on 2026-11-05 Free: 1,000 credits a month, 1 credit per page) | `npm i -g firecrawl-cli`, then `firecrawl login --browser`, both run by the user; `tools/doctor.py` shows `OK   Firecrawl CLI` | runs only on legis.md (markdown) and monitorul.gov.md (raw HTML): other sites are skipped, with no call and no credit (`firecrawl: not used for this site (only legis.md, monitorul.gov.md)`); it may read pages that refuse plain requests, with no guarantee; anti-bot pages are not bypassed (a challenge page stays `blocked_403`); the page's HTTP status is required (without it: `firecrawl: page status not reported`, not verified); 120 s timeout per page; errors start with `firecrawl: `, and not logged in, out of credits or CLI not found stop it for the rest of the run; the engine passes only the URL and never reads, asks for, prints or stores a key |
| `host` | free | the agent in a conversation | not automatic: acts left not verified are checked by hand (monitoring.md, "Host check") |

When an engine fails on a page, the next one is tried; the run records which engine produced each reading
(`evidence.via`). The EU fallback to the Publications Office (Cellar) uses plain HTTP, so it runs only when
`urllib` is among the engines; with `host` alone, scripts open no page at all. Every engine sends GET requests
to public pages only, waits 5–15 s between pages, and never fills forms, logs in or solves a CAPTCHA.

**Recommended order with Firecrawl: `urllib,firecrawl,host`.** Free first: a page `urllib` reads costs nothing, so
Firecrawl is used only where plain requests are refused (a conversation puts Firecrawl first instead, when allowed:
`<legal-workflow>/references/law-check.md`). A site that refuses `urllib` on 3 days in a row gets Firecrawl first
there (`issues.md`, demotion), so the refused request is not repeated every run. Whether Firecrawl passes the
protection of legis.md is not yet checked live: a page it returns as a challenge is still "not verified". EU acts
stay free: EUR-Lex is not on Firecrawl's list, and the Cellar fallback reads them (it needs `urllib`). Romanian acts
on legislatie.just.ro are not sent to Firecrawl until its reader is calibrated on a live page; they keep the
archived-copy route and the check by hand.

**Credits.** About one page per act on legis.md or monitorul.gov.md that `urllib` could not read, per run: such
acts × runs a month (weekly: 4–5 runs). For example, 20 such acts weekly ≈ 100 credits a month, inside the Free
plan; EU and Romanian acts cost nothing. A hand check through Firecrawl costs one credit a page too. When the plan
limit is reached the error is `firecrawl: out of credits (plan limit reached)` and the act stays "not verified".

**Connect or disconnect later:** `watch engines set urllib,firecrawl,host` (or `urllib,host`) changes only the
engines; acts, state and texts are kept. If a weekly job is installed, install it again (below).

## Schedule (`settings.schedule`)

| Choice | How | Who installs it |
|---|---|---|
| `weekly` (default) | macOS: a launchd job every Monday 09:00 (`watch schedule plan`, then `watch schedule install`); Linux: a cron line (`watch schedule plan --kind cron`) | launchd: the script, only after the user's explicit yes in chat; cron: the user, with `crontab -e` |
| `claude-schedule` | a weekly Claude scheduled task with the prompt from `watch schedule plan --kind claude-schedule` | the user (`/schedule`) |
| `on-request` | nothing runs by itself | — |

A scheduled run writes the digest into `laws/runs/<date>/` and its log into `laws/runs/schedule.log`; it sends
nothing. At the next conversation the agent reads the latest digest first, closes what stayed not verified if
the user wants, and reports. `watch schedule remove` uninstalls the launchd job.

The job runs with the `PATH` captured when it was installed (the folders of `firecrawl` and `node`, then the
system ones). After installing or updating the Firecrawl CLI or Node.js, run `watch schedule install` again (cron:
copy the new line from `watch schedule plan --kind cron`), or the scheduled run will not find the CLI.
