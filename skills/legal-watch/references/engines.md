# Fetch engines and the schedule

## Engines (`settings.engines`, tried in order)

| Engine | Cost | What it needs | Honest limits |
|---|---|---|---|
| `urllib` | free | nothing (Python standard library) | several official portals block it or drop the connection: those acts end "not verified" |
| `playwright` | free | `WITH_PLAYWRIGHT=1 ./install.sh` (a local browser) | anti-bot pages are never bypassed; slower; the browser profile lives in `laws/.browser/` |
| `command` | the user's choice (for example a paid reading service) | `settings.fetch_command`: the user's own command with `{url}`, printing the page (HTML or markdown) to stdout | the user sets up the service and its key themselves; the engine passes only the URL and never reads, asks for or stores a key |
| `firecrawl` | the user's Firecrawl plan (on 2026-11-05 Free: 1,000 credits a month, 1 credit per page) | `npm i -g firecrawl-cli`, then `firecrawl login --browser`, both run by the user; `tools/doctor.py` shows `OK   Firecrawl CLI` | anti-bot pages are not bypassed (a challenge page stays `blocked_403`); legis.md is read as markdown, other sites as raw HTML; 120 s timeout per page; errors start with `firecrawl: `; the engine passes only the URL and never reads, asks for, prints or stores a key |
| `host` | free | the agent in a conversation | not automatic: acts left not verified are checked by hand (monitoring.md, "Host check") |

When an engine fails on a page, the next one is tried; the run records which engine produced each reading
(`evidence.via`). The EU fallback to the Publications Office (Cellar) uses plain HTTP, so it runs only when
`urllib` is among the engines; with `host` alone, scripts open no page at all. Every engine sends GET requests
to public pages only, waits 5–15 s between pages, and never fills forms, logs in or solves a CAPTCHA.

**Recommended order with Firecrawl: `urllib,firecrawl,host`.** Free first: a page `urllib` reads costs nothing, so
Firecrawl is used only where plain requests are refused. `urllib` stays in the list so the EU fallback to Cellar
keeps working. A site that refuses `urllib` on 3 days in a row gets Firecrawl first there (`issues.md`, demotion),
so the refused request is not repeated every run. Whether Firecrawl passes the protection of legis.md and
legislatie.just.ro is expected, not yet checked live: a page it returns as a challenge is still "not verified".
On EUR-Lex (empty 202 to plain requests) Firecrawl is tried before the Cellar fallback and spends a credit; the
user who wants EU reads free keeps `urllib,host`.

**Credits.** About one page per act read through Firecrawl and run: acts on refusing sites × runs a month (weekly:
4–5 runs). For example, 20 such acts weekly ≈ 100 credits a month, inside the Free plan. A hand check through
Firecrawl costs one credit a page too. When the plan limit is reached the error is `firecrawl: out of credits` and
the act stays "not verified".

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
