# Law check and the source register

Shared by every module that states what the law says. Run it before the legal text and conclusions of each task.
A row in the register never replaces reading the rule.

## Procedure

1. Take the current date and timezone from the system clock: this is the check date (`checked_at`). Record
   separately the analysis date (`analysis_date`, the date the question is about; it may be in the past), the
   dates of the events and the period of performance. A re-audit, a new substantive edit or a new day is a new
   check.
2. List the legal questions and links. Give each material question a finding id (`F001`, …) and candidate acts.
   Search by the subject of the rule, without the client's details (see `norms.md` §13 and
   the search rule in `SKILL.md`).
3. Open the **full official texts**: the act, the amendments you need, corrections, repealing acts, transitional
   provisions. A snippet, a results page, an empty HTTP 200/202, a CAPTCHA, a press release or the model's memory
   is not the text of a rule.
4. Establish separately adoption, publication, entry into force and start of application; do not compute a date
   from a general formula when there are exceptions. Check separate dates for the articles you need and any delays.
5. For a historical question rebuild the version in force then. For future performance list the amendments
   already adopted and the transition terms. Do not swap the applicable version for the newest publication.
   Future amendments not yet adopted are not law.
6. Check each provision you use: content, number, neighbouring exceptions, cross-references, special rules. On
   renumbering record the old number, the date and the confirmed new address, or that it is unresolved.
7. Check the official history of amendments up to `checked_at`. For a consolidated text establish its date and
   coverage; if it lags, compare with the official publications. Do not call a consolidation authentic unless the
   source says so. For each act a material conclusion rests on, the full current-version check (seven points, one
   card per act, `check_version.py`) is `<legal-workflow>/../legal-research/references/version-check.md`; every
   module uses it, none copies it.
8. For a court decision: court, date, number/ECLI, relevant paragraphs, finality/appeal and its effect in that
   system. For an authority's decision: addressees, competence and binding force. For guidance or practice say
   plainly that it is not law.
9. Tie the rule to the facts: not only "the article exists" but why its conditions are met. Record alternative
   readings and unknown facts in the finding.
10. Before delivery reconcile every material finding with the register. A new edit or rule is checked too. If
    the work crossed midnight, check for updates again.

## The register

One file per matter: `<matter>/source-register.json`, from the template
[`assets/source-register.json`](../assets/source-register.json) (`schema_version` 1).

- `task_id` = `<matter-id>@<YYYY-MM-DD>` of the check date. A check on another day gets a new id; before
  replacing an older register, rename it to `source-register.<its date>.json` (nothing is deleted).
- Each material source needs: title and number, country, type and legal force, article/part/point, version date
  and period, a direct URL of the full text, the actual time it was opened, the applicable date, the results of
  the seven checks (`full_text`, `amendments`, `repeal`, `renumbering`, `entry_into_force`, `application_date`,
  `transitional`) and the linked findings.
- Source `status`: `verified` — the check of this rule is complete; `partial` — a named gap; `unavailable` — the
  text was not obtained; `superseded` — the replacement was checked; `future` — published but not applicable on
  the analysis date (still checked for currency). `applicability` explains the conditions; `unverified_impact`
  shows the effect of a gap.
- Each finding has `kind` `mandatory`, `risk_recommendation` or `editorial`, and `basis_kind` `law` or
  `practice`. A recommendation that cites law also needs a verified source. An editorial change with no legal
  claim may have no `source_ids`. A material unresolved question stays in the register; it never disappears.
- `completion`: `verified_scope` only when nothing material is unresolved; otherwise `partial`.

Check the structure (never the legal truth):

```bash
python3 <legal-workflow>/scripts/check_register.py <matter>/source-register.json --task-id <matter-id>@<YYYY-MM-DD>
```

Exit 0 = the structure passed, 1 = errors listed, 2 = the file cannot be read. It does not visit sites or judge
an interpretation; even a green result needs the agent's own reading.

## When a source is unavailable

**Reading order** (the one rule; the other skills link here). Read an official page in this order:

1. **Firecrawl, only if the user allowed it for conversations:** the `reading` row of
   `<profile>/context/integration-status.md` is `done` and its note contains `conversation: on`. A skipped or
   pending row, `conversation: off`, no row (a profile from 1.1) → not used, even when Firecrawl tools are
   connected. Allowed: the Firecrawl tools in this session (scrape the official URL, no cache: `maxAge` 0); for
   legis.md and monitorul.gov.md also the CLI through the engine's reader,
   `<engine>/.venv/bin/python <legal-workflow>/../legal-watch/scripts/legal_watch.py fetch --url <url> --out
   <matter>/work/sources/<act>-<date>.md` (`.html` for monitorul.gov.md). Never run `firecrawl` itself: the
   reader keeps the CLI's own output out of the chat and saves only an accepted page. Exit 0 prints
   `{url, via, status, format, saved, sha256}` (`sha256` names the saved file; it is not the text hash that
   monitoring keeps); exit 2 means "not verified", with a fixed `error` and nothing saved. Each Firecrawl page
   costs the user one credit, and it may not get through.
2. Else the host's web tools.
3. Else the user's own browser after their yes (a local browser the user installed counts, or the user pastes
   the text).

Firecrawl comes first here because the user is waiting for one answer and allowed the credit; monitoring puts
the free engines first because every run repeats every act (`legal-watch/references/engines.md`). Only public
official URLs go to Firecrawl, never document text or personal data. A page that is still an anti-bot check stays
"not verified". (On 2026-11-05 legis.md answered 403 and legislatie.just.ro dropped
the host's web tools.) After a failure try the direct record or official PDF, another allowed way of reading, or
another official publication (register → official journal → the issuing authority). Keep each address and result.
Never get around access restrictions and never take an anti-bot page for the act. A few meaningful routes are
enough.

Another official copy may confirm the text but not the current version: check later amendments separately. If
that fails, mark `partial`, list the dependent findings and continue the independent checks. The result reads:
"Partial analysis: the current version of [rule] is not confirmed; finding [ID] and edit [ID] need a check." Never
call this a complete legal audit and never fill an unknown with an invented value.
