---
name: legal-watch
description: Law library and monitoring module of the legal engine (Moldova, Romania, EU) - picks the laws that concern the user's business from a catalog of niches, keeps their official texts and versions in the user's profile, checks them for new, future and repealed versions with an honest "not verified" when a site cannot be read, writes a short digest in the user's language, and flags the clauses of the user's contracts in force that depend on a changed law for re-review. Use for "какие законы касаются моего бизнеса", "скачай законы", "что изменилось в законах", "проверь изменения законов", "перепроверь договоры после изменения закона", "ce legi mă privesc", "ce s-a schimbat în lege", "monitorizare legislație", "which laws apply to my business", "what changed in the law", and for the setup steps niches, laws and first-run.
---

# Legal Watch

Resolve this skill's directory (`<skill-dir>` below); the entry skill is `<skill-dir>/../legal-workflow/`
(`<legal-workflow>` below), the version check is `<skill-dir>/../legal-research/` (`<legal-research>`), the
document tools are `<skill-dir>/../legal-contracts/` (`<legal-contracts>`). Scripts run with the engine's
`.venv/bin/python` (PyYAML, python-docx); below `watch` stands for
`<engine>/.venv/bin/python <skill-dir>/scripts/legal_watch.py`.

## Before anything

1. **Core module.** `watch` is always on. It needs the setup steps `niches` and `laws`
   (`python3 <legal-workflow>/scripts/legal_profile.py status --module watch`); missing → run them from
   [references/setup.md](references/setup.md), one question at a time.
2. **Norms.** Read `<legal-workflow>/references/norms.md` once per session. The law rule of the engine applies
   to every line here: a stored text or version is a lead, never the law of today; "the rule is in force" in an
   answer still goes through `<legal-research>` (version check on the task date).
3. **Data.** Everything lives in the user's profile (`laws/`, `contracts/`), never in the engine. What is kept
   where, and how other skills use it: [references/library.md](references/library.md).
4. **Error log.** Before any monitoring request run `watch issues` and follow the recipe of each open problem,
   p1 first ([references/issues.md](references/issues.md)); say in one line what was done and what is left.

## What the user can ask

| Request | Route |
|---|---|
| which laws concern my business; add or remove a law | [setup.md](references/setup.md) §7–8: catalog, suggestion, `watch init` |
| download the laws / check for changes now | [monitoring.md](references/monitoring.md): `watch run`, then check by hand what stayed not verified |
| what changed | the latest digest (`watch digest`), explained in plain words with what it means for the business |
| re-check my contracts after a change | [contracts.md](references/contracts.md): pending flags → a re-review matter through `legal-contracts` |
| a new contract in force to follow | [contracts.md](references/contracts.md): `watch index scan`, completed by reading the clauses |
| what went wrong / show me the problems | `watch issues`; the page `laws/report.html` (`watch report`) — give the user its path |
| how are the laws stored | [library.md](references/library.md), in plain words |
| run it every week | [engines.md](references/engines.md): schedule, only after the user's yes |

## Route of a monitoring request

1. **Run** — `watch run` (all acts, or `--acts p1` / ids). Exit 0 OK, 1 changes, 2 incomplete or bad input,
   3 unexpected error.
2. **Close the gaps** — every act listed "not verified" is checked by hand when the user wants it now:
   open the official page in the reading order of `<legal-workflow>/references/law-check.md` (Firecrawl only when
   the user allowed it for conversations), fill a
   version card (`<legal-research>/references/version-check.md`, `scope: "text"` is enough for monitoring), save the
   text read, then `watch record --card <card> --root <folder of the card> [--via firecrawl]`. Never write "no changes" for an act that was
   not read today.
3. **Explain** — from the digest: what changed, from when, whom it touches (the user's firms, niches and
   contracts), what to do now and what can wait. A future version is announced with its date, never as law in force.
4. **Contracts** — a confirmed change that flags clauses → propose one matter per contract, "re-review
   contract X" (`legal_profile.py matter new --slug … --title … --module contracts`); the audit and the Word
   redline follow `<legal-contracts>/SKILL.md`. Clear a flag only when its clause is re-reviewed with the law
   verified on the date (`watch index clear --contract X --clause N --matter <id>`); a partial report keeps open flags.

## Rules

- **A failure is never "no changes".** Not read, blocked, archived copy only, uncalibrated reader → "not verified",
  with the reason and the way to close it.
- **The first reading is a baseline**, not a change; the user is told that comparisons start from it.
- **Future versions stay future** until their start date; repeals are named with the repealing act.
- **Look for room, not only for danger.** A change can open a lawful option (a lighter regime, a new form of
  activity, a later deadline): say so, `norms.md` §15.
- **No key, no silent install, no sending.** Paid engines (`firecrawl`, or the user's own `command`) run on the
  user's own login; the engine never sees a key. The weekly job is installed only after the user's yes; the engine never sends the digest anywhere, signs or files anything.
- **Catalog entries are leads.** Each carries its check date and `verified` / `reported`; a document id that no
  longer opens the act is a finding for the run, not a reason to guess another one.

## Resources

- [references/setup.md](references/setup.md) — wizard steps `niches`, `laws`, `first-run`; the watchlist format.
- [references/monitoring.md](references/monitoring.md) — statuses, results, the host check, the digest.
- [references/contracts.md](references/contracts.md) — the clause index and re-review.
- [references/engines.md](references/engines.md) — fetch engines and the schedule.
- [references/issues.md](references/issues.md) — the error log, its recipes and the page for the person.
- [references/library.md](references/library.md) — the layers of the law library and how skills use them.
- `assets/catalog/` — niches → categories → acts with official ids; `templates/watchlist.yaml` — an example.
- `scripts/legal_watch.py` and `scripts/watch/` — the tools; `tests/` — their tests.
