# Monitoring: a run, its statuses and the digest

`watch run [--acts all|p1|<ids>] [--dry-run]` reads every watched act from its official source, compares it with
the version held, stores a new text when it differs, writes `laws/runs/<date>/run.json` and `digest.md`, and
flags dependent contract clauses. A run of some acts, or a check by hand, joins the day's run instead of replacing
it; only a run of all acts counts as a complete run. `--dry-run` writes into `runs/<date>/dry-run/` only, with no
state, texts, flags or error log. Every real run also updates the error log `laws/issues.json` and the page
`laws/report.html` ([issues.md](issues.md)); the layers of the library are in [library.md](library.md).

## Sources

| Kind | Site | What is read |
|---|---|---|
| `legis_md` | www.legis.md (Moldova, State Register of Legal Acts) | the act's card: amendments with their dates, the bar of versions, repeal. A `doc_id` points to one version; later versions are listed on its page |
| `just_ro` | legislatie.just.ro (Romania, Legislative Portal) | the act's heading and its list of consolidations, delayed application dates, repeal notes; when the portal fails, an archived copy (Wayback Machine) is read and marked as such |
| `eurlex` | EUR-Lex and the Publications Office (EU) | in-force status, consolidated versions and their dates |
| Moldovan Official Gazette | monitorul.gov.md | new issues since the last run; items whose title names a watched act are **signals** to check that act, not changes |

## Statuses of an act

| Status | Meaning | Checked? |
|---|---|---|
| `baseline` | first reading: the version in force is recorded | yes |
| `unchanged` | the version in force equals the one held | yes |
| `new_in_force` | a newer version is in force | yes, a change |
| `new_future` | a version with a later start date was published | yes, a change of kind `future` |
| `repealed` | the act is repealed | yes, a change |
| `repealed_known` | still repealed, as already held | yes |
| `fetch_failed` | the site did not answer | **no** |
| `blocked_403` | the site blocked automatic access (anti-bot page) | **no** |
| `parse_failed` | the page could not be read reliably, or the reader is not yet calibrated on this site | **no** |
| `stale_fallback` | only an archived copy was read | **no** |

A reading is accepted only from a reader calibrated on a live page of that site. A change found by an
uncalibrated reader is reported as *possible*: it does not move the held version and flags no contract until it is
confirmed by hand. Two readings with the same start date are the same version (readers label versions
differently); a held next version whose date has passed while the page still shows the old one (postponed, or
not yet consolidated) is "not verified", never "in force". An act named in a new issue of the Moldovan Official
Gazette stays "not verified" until a new version is read or it is checked by hand.

Readers calibrated today: legis.md through markdown (the `firecrawl` engine, checked live on 2026-11-05, or a
`command` engine), EUR-Lex and Cellar, the Gazette's
table of contents, archived copies. Not yet: legis.md HTML and both just.ro readers. So with the free engines
most Moldovan and Romanian acts end "not verified" and need the host check; acts without a source in the catalog
always do.

**Result of the run:** `OK` (every p1 act checked, no change) → exit 0; `CHANGES` → exit 1; `INCOMPLETE` (a p1
act not verified) → exit 2; a bad input also exits 2, an unexpected error 3. The words "no changes" are allowed
only when the result is `OK` and nothing is left not verified; otherwise "no changes in the acts checked; N not
verified".

## Host check (the agent reads the page)

For each act left not verified that the user wants closed now:

1. Open the official page (from the catalog's `official_url` or the act's source) in the reading order of
   `<legal-workflow>/references/law-check.md` (Firecrawl on legis.md and monitorul.gov.md:
   `watch fetch --url <url> --out <folder>/<act>-<date>.md`, `.html` for monitorul.gov.md). A page that is still
   an anti-bot check stays "not verified".
   Live run of 2026-11-05: the web tools were refused too (legis.md 403, legislatie.just.ro dropped the connection); the user's browser opened legis.md, while
   legislatie.just.ro did not open even in a browser that day. A site that does not open leaves the act "not
   verified", never "no changes".
2. Fill a version card as in `<legal-research>/references/version-check.md`, `scope: "text"`, `analysis_date` = today, `held_version` =
   the version in `watch show`, `cited_provisions: ["whole act"]`. The points `consolidation`, `amendments`,
   `deferred_entry`, `repeal`, `status_of_changes` must be `done` from a live official page (an archived copy does
   not count). Save the text read next to the card and give `text_file` (Firecrawl markdown as `.md`); without it
   the act cannot be `unchanged`.
3. `python3 <legal-research>/scripts/check_version.py <card> --root <folder>` must pass; then
   `watch record --card <card> --root <folder> [--via firecrawl]`. The act joins today's run as checked by hand
   (`via: host`, or `firecrawl` when the page was read through Firecrawl); the digest is rewritten.

A card that is not from today or not about today, not about the whole act, fails its checker, is `not_verified`, or leaves one of those points open changes
nothing.

## The digest

`laws/runs/<date>/digest.md`, in the language of the watchlist: the result line, changes (confirmed first),
contracts to re-review with the proposed matter, acts not verified with the reason and the offer to check them by
hand, first readings, Official Gazette signals, and the date of the last complete run (a weekly schedule that has
not completed for 9 days is marked overdue). When talking to the user, translate it into consequences: what the
change does for their firms, from when, and the simplest lawful way to adapt.
