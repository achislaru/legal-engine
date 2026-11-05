# The error log: what failed, and what to do next time

`laws/issues.json` in the profile remembers every act that could not be verified, across runs. The next run and
the agent read it; the person sees it on `laws/report.html`. Written by the scripts only (`scripts/watch/issues.py`).

## What it holds

- `acts.<id>` — one entry per act not verified: `kind`, `first_seen`, `last_seen`, `count`, `streak` (attempts in
  a row), `last` (engine, url, HTTP code, error ≤ 300 characters, notes), `history` (last 10 attempts), `state`
  `open` / `resolved`, `resolved_on`, `resolved_by`. A check of the act (a run or `watch record`) closes it; a
  solved entry is dropped after 90 days. An act removed from the watchlist is closed as "removed from the watchlist"
  (a run of some acts never counts as removal). A second run of the same day adds an attempt; it never wipes the first.
- `engines.<site>.<engine>` — on how many days that engine failed on that site since its last success (`streak`), `last_error`,
  `last_ok`, `demoted_since`.
- A damaged log (hand-edited, cut short) stops the run with a clear message before anything is written; move the
  file away and the next run starts a new one.
- Not logged: `host_only` (the user chose hand checks) and Official Gazette signals; they are expected work, the
  digest lists them.

## What the next run does by itself

After 3 days with failures of an engine on a site and no success in between, `watch run` tries that engine **last** there (a free
engine would only cost the 5–15 s pause per act; a demoted `firecrawl` still spends a credit when it is reached) and
notes it in the reading. Every 7 days it is tried first again, in case the
site opened up. An engine that is the only one still runs. Nothing is skipped silently: an act not read stays
"not verified".

## What the agent does: step 0 of every monitoring request

Run `watch issues`. For each open problem, p1 first, follow its recipe, then say in one line what was done and
what is left. A recipe never turns a failure into "no changes".

| Kind | Recipe |
|---|---|
| `blocked` | the site refuses automatic access: host check ([monitoring.md](monitoring.md), "Host check", reading order of `<legal-workflow>/references/law-check.md`); then `watch record` (`--via firecrawl` when Firecrawl read the page). On legis.md or monitorul.gov.md with `firecrawl` not in the engines, say that Firecrawl may read them, with no guarantee (wizard step `reading`, or `legal-workflow-update`) |
| `fetch_failed` | the site did not answer: run again (`watch run --acts <id>`); after 3 in a row, host check; a site down for days is said plainly. Error `firecrawl: not logged in (run firecrawl login --browser yourself)`: tell the user to run it themselves; `firecrawl: out of credits (plan limit reached)`: say so (the free route stays); `firecrawl: page status not reported`, `firecrawl: the service reported a failure`, `firecrawl: unreadable output`, `firecrawl: format <markdown or rawHtml> not returned`, `firecrawl: HTTP <n> (reported by Firecrawl, not a page)`: the page was not verified, host check. A digest note that Firecrawl was not allowed for monitoring: ask whether to connect it again (`legal-workflow-update`) or `watch engines remove firecrawl` |
| `parse_failed` | the page was read but not understood: host check now; when it repeats on the same site, the page layout probably changed: save the page (in the profile, never in the engine) and offer the user to report it to the engine's authors — they decide, the engine sends nothing |
| `uncalibrated` | the reader of this site is not calibrated yet: host check until it is (see "Readers calibrated today" in monitoring.md) |
| `no_source` | the act has no official source: find its page on the official site (legis.md / legislatie.just.ro / EUR-Lex), confirm with the user that it is the act, then `watch source add <id> --doc-id <id>` (EU: `--celex`), and `watch run --acts <id>` |
| `stale_fallback` | only an archived copy was read: look for the current official text; an archive is never a check |
| `reader_crashed` | a bug: host check now; keep the error text for a report to the engine's authors (the user decides) |
| `gazette_failed` | the Official Gazette scan did not finish: run again; signals already found are kept in the state |

## For the person

`laws/report.html` (rewritten after every run, or `watch report`): open problems with what happened, what the agent
will do and what the person can do; sites that refuse an engine; recently solved problems; the law library. It is
a local file: tell the user its path, never publish it.
