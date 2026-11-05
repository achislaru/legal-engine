# Status

Version: 1.2.0 (2026-11-05; branch `phase-1/firecrawl`, not on `main` yet; 1.1.0 is on `main`, tagged, published).
Updated: 2026-11-05.

| Step | What | State |
|---|---|---|
| 1 | Skeleton: install.sh, doctor, leak check + tests, licence, disclaimer, README | done |
| 2 | `legal-workflow`: router, profile, matters, working norms | done (branch `phase-1/legal-workflow`) |
| 3 | `legal-contracts` (draft / audit / redline, MD-RO-EU) | done (branch `phase-1/legal-contracts` on top of step 2) |
| 4 | `legal-research` (question with citations, current-version check) | done (branch `phase-1/legal-research` on top of step 3) |
| 5 | `legal-workflow-setup` wizard + `legal-workflow-update` | done (branch `phase-1/legal-workflow-setup` on top of step 4; merge to `main` only after the owner's «да») |
| 6 | modules `legal-privacy`, `legal-consumer` | done (branch `phase-1/legal-privacy-consumer` on top of step 5; merge only after «да») |
| 7 | module `legal-trademark`; norms §15 (cost against risk); `legal-consumer` made generic | done (branch `phase-1/legal-trademark` on top of step 6; merge only after «да») |
| 8 | module `legal-employment` | done (branch `phase-1/legal-employment` on top of step 7; merge only after «да») |
| 9 | `legal-watch`: niche → law catalog, law library, monitoring, contract re-review | done (branch `phase-1/legal-watch` on top of step 8; merge only after «да») |
| 10 | end-to-end check, cross-model review, v1.0.0 | done (branch `phase-1/release-1.0` on top of step 9; merge only after «да») |
| 10a | monitoring error log + `laws/report.html`, law library described (`legal-watch/references/issues.md`, `library.md`), v1.1.0; Codex review in 4 rounds: 3/5 → 3/5 → 4/5 → 5/5 | done (branch `phase-1/watch-issues` on top of step 10; merge only after «да») |
| 11 | public GitHub repository and first push | done 2026-11-05: github.com/achislaru/legal-engine (public, MIT, `main` + tags v1.0.0, v1.1.0); fork github.com/Automall-Training/legal-engine |
| 12 | Firecrawl: wizard step `reading`, engine `firecrawl`, hand check via Firecrawl | done on branch `phase-1/firecrawl`; live calibration (E) pending, merge only after «да» |

Release check (step 10, 2026-11-05): 566 tests, coverage 93 %; clean install twice → `READY`; live monitoring
run; scenario runs by fresh agents (wizard for an invented online-courses firm, NDA and Word redline, legal
question, privacy policy, module switched off) all passed, their findings fixed; Codex review of code and texts
in two rounds, every finding fixed (round 1: code 2/5, texts 3/5; round 2 fixes after it not re-reviewed).
Live findings: plain requests and the host's web tools are refused by legis.md (403 challenge) and
legislatie.just.ro (connection dropped); EU acts are read through the Publications Office (EUR-Lex itself
answers an empty 202); the user's Chrome opened legis.md, while legislatie.just.ro did not open even in a browser
that day. So Moldovan acts are checked by hand through the user's browser, Romanian ones when the portal answers.
Still open after 1.0.0: calibrate the just.ro reader on a live page (the portal was down for the whole check);
`civil` and other code pages of just.ro; 38 catalog acts without a document id; MD document ids `reported`; PDF
scan of MD omnibus laws; trademark bulletin watch; `matter new` does not copy the represented party and languages
from the profile; `suggest` does not show act priorities; minor: the digest keeps source labels in the source's
language ("consolidare …").

Checks: `python3 tools/check.py` · `python3 -m unittest discover -s tools/tests` ·
`.venv/bin/python -m unittest discover -s skills/<skill>/tests` (the pre-commit hook runs all of them; contract tools
need `.venv` from `./install.sh`). Coverage: `COVERAGE_FILE=<temp> uvx coverage run -m unittest discover -s
<tests>` (keep the data file outside the repo: a `.coverage` in it fails the leak check).

Contracts later steps must follow (in `skills/legal-workflow/references/`): `profile.md` (profile layout,
`modules.json`, setup steps written only via `legal_profile.py step set`), `matters.md` (matter folder,
`input/` · `output/` deliverables · `work/` working files, `intake.json` core + `module_data` written via
`matter update`, `log.md`, handoff to a module), `norms.md`,
`law-check.md` (law check and the shared `source-register.json`, task_id `<matter-id>@<date>`, checked by
`scripts/check_register.py`), `sources.md`, `jurisdiction.md`. The current-version check of an act (seven points,
version card in `work/versions/`, `check_version.py`) lives in `legal-research/references/version-check.md`; every
module uses it and step 9 (`legal-watch`) builds monitoring on the same card. Document tools (DOCX, Word redline, Romanian style
and structure checks, model library) live in `legal-contracts`; other modules reuse them by path.

Minor, later: `check_register.py` stops at the first malformed source or finding (one `try`); per-item checks
would list all errors at once.
Minor, later: no script yet checks that a register source's status matches its version card (the table in
`version-check.md` is applied by hand). Live run against real official sites: step 10 (`legal-research/tests/scenarios.md`).
Rollout: do not install the engine next to a personal contracts skill with overlapping trigger phrases.
`legal-watch` (step 9): the wizard steps `niches`, `laws`, `first-run` follow `legal-watch/references/setup.md`;
the profile holds `laws/watchlist.yaml` (choices), `laws/state.json` (versions held, scripts only), `laws/texts/`,
`laws/runs/<date>/`, and `contracts/index/`. Scripts need `.venv` (PyYAML, python-docx). Readers calibrated on live
pages: legis.md markdown (via a command engine), EUR-Lex / Cellar, the MD Gazette table of contents, Wayback; not
calibrated: legis.md HTML, both just.ro readers (their readings are "not verified" until confirmed by hand). On
2026-11-04 plain requests were refused by legis.md (403), legislatie.just.ro (connection dropped) and EUR-Lex
(empty 202): expect checks by hand. Open, live run (step 10): calibrate the just.ro reader on a live page; just.ro
code pages known only for the fiscal and labour codes; 38 catalog acts lack a document id (the agent finds them: recipe `no_source`, `watch source add`);
Moldovan document ids are all `reported`; PDF scan of omnibus laws in the MD Gazette not ported; trademark bulletin
watch (BOPI) not ported (later option).
Optional modules (from step 6) check `legal_profile.py module <id>` first, decide the content of a document and
hand the drafting to the contract tools by path; `tools/tests/test_skills.py` checks every skill (frontmatter, links,
JSON, module templates against `matter update`, the switch check). A data breach skips the module switch (router).
Open, live run (step 10): the Moldovan consumer part (withdrawal period and its exceptions in the Civil Code, which
e-commerce law is in force) and the cookie rule in Moldova are found per matter; the library has no cookie-notice
model yet.
Every module follows `norms.md` §15: for "how do I do X" it compares two to four configurations (what each needs,
cost, residual risk, verdict), the simplest lawful one first. `legal-consumer` covers any product (goods, services,
apps and subscriptions, marketplaces, shop sales; courses are one block of `terms-structure.md`).
`legal-trademark` keeps the user's marks in `<profile>/trademarks/portfolio.json`; `tm_deadlines.py` prints raw
dates, every rule `reported` or `not-read`. Open, live run (step 10): which Moldovan trademark law applies on the
task date (Law 38/2008 or Law 25/2024), the AGEPI terms and the representation rule; current fees of the three
offices; no trademark licence model in the library (M05 is a structure for licences in general).
`legal-employment` has no model card in the contract library: its documents follow the module's own structure
(`references/documents.md`), a contract with a self-employed person uses M01. Open, live run (step 10): the
current article numbers of both labour codes, REVISAL deadlines, the MD-RO social security agreement, current
minimum wages and contribution rates.
