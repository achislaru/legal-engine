# Changelog

## 1.2.0 — 2026-11-05

Official sites that refuse plain requests may be read through Firecrawl, a paid service with a free monthly
allowance that the user connects with its own sign-in. It is optional and has no guarantee: skipped, everything
works as in 1.1.0.

- **Wizard, first step `reading`:** connect Firecrawl for conversations (the hosted MCP or the CLI), for monitoring
  (the CLI), both, later or skip; the cost and what is sent (only public official page addresses) are said first,
  and the chosen option is the user's yes. The user signs up and runs every sign-in command; the engine never sees
  a key. The note `conversation: on|off; monitoring: on|off` is the consent: Firecrawl is used only where it says
  `on` (a skipped, pending or 1.1 profile never uses it, even with an MCP server connected), and the scripts check
  it themselves: `watch fetch` needs `conversation: on`; adding the engine needs `monitoring: on`; a run without it
  skips Firecrawl and says so. One part may work while the other waits (`off; waiting: …`). The steps after it
  move by one (documents is step 9).
- **Engine `firecrawl`** for law monitoring, only on legis.md (markdown) and monitorul.gov.md (raw HTML): other
  sites are skipped with no call and no credit, so EU acts stay free through Cellar and legislatie.just.ro waits
  for its reader to be calibrated. The user's logged-in CLI, the page's real HTTP status (without it, or with a
  status other than 2xx, the page is not verified), only the requested format, metadata read inside the fixed
  errors (nothing of the CLI's output reaches the chat or the run files), its own 120 s timeout, fixed errors starting with `firecrawl: `
  (not logged in, out of credits and CLI not found are said once per run), no key.
  Recommended order `urllib,firecrawl,host`; the credit estimate (acts and Gazette pages) is in
  `legal-watch/references/engines.md`, and the digest gives each run's Firecrawl calls as an estimate, not the bill.
- **`watch fetch --url … --out …`:** the safe way to read legis.md or monitorul.gov.md through the CLI in a
  conversation; the CLI's own output never reaches the chat, only an accepted page is saved.
- **`watch engines add|remove <engine>`** (and `engines set …`): connect or disconnect Firecrawl for monitoring
  later, keeping the other engines; acts, state and texts are kept (`legal-workflow-update`).
- **Anti-bot check on markdown:** a challenge page returned as markdown (by `firecrawl` or `command`) counts as
  blocked, never as the act.
- **Schedule PATH:** the weekly job keeps the folders of `firecrawl` and `node`; install it again after installing
  the CLI or Node.js, or after changing the engines.
- **`watch record --via firecrawl`:** a hand check whose page Firecrawl read stays a hand check.
- **Saved `.md` texts:** version cards and hand checks accept Firecrawl markdown, compared as plain text; the stored
  snapshot of a markdown page is the text that is hashed.
- **Doctor:** an optional `Firecrawl CLI` line (logged in, not logged in, unknown, absent), logged in only on a clear
  positive answer; it never prints the CLI's output.
- **Digest and report:** when legis.md or monitorul.gov.md refused reading and Firecrawl was not used, they say it
  may help, with no guarantee.
- **Reading order in conversation**, one rule in `legal-workflow/references/law-check.md`: Firecrawl when allowed,
  then the host's web tools, then the user's browser after their yes. Cookie and tracker screening stays plain GET.
- Live calibration pending: whether Firecrawl passes the protection of legis.md is not yet checked on live pages.

## 1.1.0 — 2026-11-05

Law monitoring learns from its failures, and the law library is described. The whole repository is now under
the MIT License (the texts were CC BY 4.0); official legal texts keep their own status.

- **Error log** `laws/issues.json` in the profile: every act that could not be verified, with each attempt (site,
  engine, HTTP code, error), kept across runs and closed when the act is checked by a run or by hand. A second
  run of the same day no longer wipes the first failure's detail.
- **Next runs adapt:** an engine a site refused on 3 days without a success in between is tried last there, and first again every 7 days.
  Before every monitoring request the agent follows the recipe of each open problem (`legal-watch/references/issues.md`).
- **Page for the person** `laws/report.html` (local, rewritten after every run): open problems with what happened,
  what the agent will do and what the person can do; sites that refuse an engine; solved problems; the library.
- **Commands:** `issues`, `report`, `source add` (gives an act its official source), `prune --runs-older`
  (lists old run folders, deletes them only with `--apply`); `show` lists the text copies; doctor shows the
  number of open problems; the digest points to the page.
- **The law library explained** (`legal-watch/references/library.md`): catalog, watchlist, state, text copies,
  runs and error log, which of them is truth (none), and how research and contracts use them (`held_version`
  from `watch show`; a today's whole-act card also updates the library).

## 1.0.0 — 2026-11-05

First public release: the entry point and wizard, three core modules (contracts, legal questions, law library and
monitoring) and four optional ones (personal data, consumers, trademarks, employment). Known limits are listed in
`docs/STATUS.md`.

Release check (step 10): every test suite with the project libraries (coverage 93 %), a clean install twice
(`READY`, the second run changes nothing), a live monitoring run on official sites, scenario runs by fresh agents
on invented firms, and a review by another model (Codex) of code and texts with every finding fixed.

- Fixes from the live run: EU texts read through the Publications Office are saved to the law library; the digest
  says "last run with every main act checked"; `doctor` reports the browser engine only when it can really run.
- Fixes from the review: "no changes" is written only when nothing is left unverified; a partial run no longer
  loses Official Gazette signals of other acts; a version date always wins over its label; an EU act marked not in
  force without a repeal, or with a new amendment not yet consolidated, is "not verified"; amendments named in a
  hand check count as versions; clauses of Word contracts are read in document order (tables included); the leak
  check reads Word metadata, authors and links and checks exactly what is staged; check reports never overwrite
  the file checked; nothing is written inside the engine folder, even through a link in the profile;
  `install.sh` stops when a dependency step fails. Texts: risks without a sanction weighed by their real
  consequence; digital content and digital services kept apart for withdrawal; contract flags cleared clause by
  clause; a question of a switched-off module goes back to the router; the website check is a static screening;
  README says exactly what stays on the computer and what the AI host processes.
- Fixes from the scenario runs: Romanian clause numbers "1.1." read by the structure check; a source that could
  not be opened may have no version; the wizard asks the firm facts in two questions, writes no weekly schedule
  before the user chooses, lists linked skills among required tools; the router names the setup request; the
  leak check no longer treats example.md and example.ro as reserved (only example.com, .net, .org are).
- `VENDOR.json`: name, version, licences, skills and the hosts the monitoring scripts read; `doctor` prints the
  version.

## Before 1.0.0

- `legal-watch` module (core): a catalog of 10 niches, 21 law categories and 116 MD / RO / EU acts with official
  ids, each dated and `verified` or `reported`; the wizard steps `niches`, `laws`, `first-run`; a watchlist in the
  profile, monitoring of each act (baseline, unchanged, new in force, future, repealed) where any failure or an
  uncalibrated reader is "not verified", never "no changes"; text snapshots, a digest in ru / ro / en, a check by
  hand through a `legal-research` version card; an index "contract clause → law" whose clauses are flagged for
  re-review when a law changes; fetch engines urllib, local browser, the user's own command (no key seen) and by
  hand; a weekly local job installed only after the user's yes. Adapters for legis.md, legislatie.just.ro (with an
  archived copy marked as such), EUR-Lex / Cellar and the Moldovan Official Gazette.
- `legal-employment` module (MD and RO labour codes): ways to engage a person compared by cost and risk
  (employment variants, civil contract, agency, day labourer), seven procedures (hiring, amendment, ending from
  the agreement down, internal rules, contractor or employee, inspection or claim, work across borders), the
  required content of each document, optional documents offered as optional.
- `legal-trademark` module: name check with a verdict on the norms scale (never "available") and ways around a
  conflict, filing strategy by cost and risk (territory, route, priority, sign, classes, owner, representation),
  portfolio deadlines from the profile with `tm_deadlines.py` (raw dates, rule and article, check on the task
  date), office letters, oppositions, a five-rung enforcement ladder, claims against the user, licences.
- `norms.md` §15: compliance configuration — map the constraints, find the levers, compare options by cost and
  residual risk, recommend one. Modules point to it.
- `legal-consumer` made generic: any product and channel, `terms-structure.md` (common core plus a block per
  product), goods exceptions to withdrawal, checkpoints for delivery and risk, subscriptions, marketplaces and
  sales that are not at a distance.
- `legal-privacy` module: GDPR, Moldovan Law 195/2024, Romanian Law 190/2018. Six procedures (website or form,
  processor or DPA, transfer abroad incl. a non-EU controller, DPIA screening, data request, breach with the
  72-hour deadline first), the minimum content of each document with model cards M06–M10, law map as navigation.
  The router sends a data breach to it whatever the module state.
- `legal-consumer` module: sales to consumers online, checkpoints C1–C14 for RO / EU (information, order button,
  withdrawal and its digital-content exceptions, online withdrawal function, conformity, price reductions, unfair
  terms, complaints and ADR) and the Moldovan part, never filled from the Romanian column.
- `tools/tests/test_skills.py`: consistency of every skill (frontmatter, relative links, JSON, module templates
  accepted by `matter update`, optional modules check their switch).
- `legal-workflow-setup` wizard: creates the private profile and fills it one question at a time (firms, whom they
  sell to → suggested modules, modules on/off, languages, side and risk threshold, own samples and contracts with
  house style, local tools after one approval); quick or full depth, resumes from `integration-status.md`, never
  overwrites an answer silently; law-library steps wait for `legal-watch`. Context file templates.
- `legal-workflow-update` skill (human-invoked only): changes the profile after feedback, after a "yes" to the exact
  change; engine-level problems become a drafted issue, never an edit of the engine folder; migration rules.
- `legal_profile.py`: `profile init` (folders and `config.json`, `--switch` to repoint, `--create` for a configured
  folder that is missing; refuses the home folder and any folder inside or around the engine), `modules set` (a
  skipped modules step reads as all off), atomic writes for every profile file, `where` reports the engine folder. The router
  checks that a module is installed before running the wizard for it.
- `legal-research` skill: legal question with quotes from the version in force (lawful path first, labelled
  conclusions, weighed risk, sources and "not verified" blocks) and the current-version check of an act in seven
  points (consolidation, amendments incl. the official journal, delayed entry, secondary acts, case law, repeal,
  status of changes), one version card per act. `check_version.py` checks the card: evidence opened today from an
  official source, archived copies never prove the latest version, future versions and drafts never in force,
  optional quote-in-saved-text check (HTML and PDF artefacts tolerated). Access routes for MD / RO / EU sources,
  traps, answer shell. `law-check.md` and `legal-contracts` point to it instead of copying it.
- `legal-contracts` skill: draft, audit, edit and adapt contracts and commercial documents (MD / RO / EU) inside a
  matter: intake into `module_data`, law check with the shared source register, Romanian model library with official
  links (originals are downloaded on demand, not shipped), templates, audit report shell, delivery checklist.
  Scripts: `build_docx.py`, `docx_redline.py` (real Word tracked changes + clean copy, accept = clean,
  reject = original), `check_ro_style.py`, `check_structure.py`; they re-run in the engine's `.venv` when needed and
  refuse to write inside the engine folder. Tests with the synthetic redline example.
- `legal-workflow`: shared law check (`law-check.md`, `sources.md`, `jurisdiction.md`), source register template and
  `check_register.py`, command `matter update` (modules fill `intake.json` without hand edits).
- Pre-commit hook runs skill tests with `.venv` when present.
- `legal-workflow` skill: entry point and router by module (states core / on / off / unset / not-installed),
  profile lookup via `~/.config/legal-engine/config.json` (a profile inside the engine is refused), only the
  missing setup steps, matters `matters/YYYY-MM-DD-slug/` with an append-only `matters/log.md`, approval
  boundaries, working norms (`references/norms.md`). Script `legal_profile.py` (status, module, step set,
  matter new / log / show / list) with tests; `doctor.py` reuses its profile lookup; the hook runs skill tests.
- Repository skeleton: `install.sh`, `tools/doctor.py` (machine check), `tools/check.py` (leak check of the
  public repo, also inside .docx), tests, licence, disclaimer.
