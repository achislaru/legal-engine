---
name: legal-workflow-update
description: Change the legal engine's profile after feedback - firms, modules on/off, languages, side and risk threshold, house style and recorded decisions, a wizard step to redo, a new profile folder, a file of an older format. Only when the user calls it directly.
disable-model-invocation: true
---

# Legal Workflow Update

Use only when the user invokes it. It changes the **profile**, never the engine folder and never a matter.
The profile script is `<skill-dir>/../legal-workflow/scripts/legal_profile.py` (`<lp>`); the contract is
`../legal-workflow/references/profile.md`.

## Steps

1. **What to change.** Ask what was good, wrong or missing and, if it happened in a matter, which one
   (`<lp> matter list`). Read only the files involved; explain in plain words which file controls it.
2. **Proposal.** Show the smallest change and the exact files, then wait for the user's "yes" to that change.
   The user may also edit the file by hand and come back.
3. **Apply** through the route of the table and confirm what changed.

| Change | Route |
|---|---|
| firm details, whom they sell to | `context/company.md` |
| languages | `context/language.md` |
| side, risk threshold, "always ask before" | `context/side-and-risk.md` |
| a preference for documents, default forum, a decision to remember | `context/house-style.md` (decisions table: date, decision, applies to) |
| turn a module on or off | `<lp> modules set <id>=on|off` |
| redo a wizard step | the step from `../legal-workflow-setup/references/questionnaire.md`, then `<lp> step set <id> --status done` |
| connect or disconnect Firecrawl, or change where it is used | step `reading` of `../legal-workflow-setup/references/questionnaire.md`: connecting a part needs the cost, then the user's yes, sign-in by the user; then `<lp> step set reading` with the resulting note (disconnect: `off`, or `--status skipped --note "not connected"`; a global logout is not needed), then its "Monitoring follows the resulting note": `watch engines add firecrawl` or `watch engines remove firecrawl` (the other engines stay), nothing for a conversation-only change, and the schedule reinstalled after `"changed": true` |
| a new profile folder | `<lp> profile init --dir <new> --switch`; offer to copy (never move or delete) the old folder's files after a "yes" |
| a file of another `schema_version` | the migrations below |
| how the engine itself works (a wrong rule, a missing check, a bug) | not here: draft a short issue (what happened, what was expected, without personal data or document text) for the user to file in the engine's repository; the engine folder is a shared checkout that `git pull` updates |

## Never

- edit a matter, its `intake.json`, its files or a row of `matters/log.md` (they are the history);
- turn one isolated case into a general rule without the user saying so;
- write a context file or `modules.json` before the user's "yes" to that exact change;
- edit the engine folder, or print, ask for or store a key, a token or a password.

## Migrations

Current `schema_version` of `modules.json` and `intake.json`: 1. No migration exists yet. A file with a higher
version was written by a newer engine: tell the user to update the engine (`git pull && ./install.sh` in the
engine folder); never lower it. A future migration is listed here with its from/to versions and is applied only after
the user's "yes", with the old file kept next to it as `<name>.v<old>.json`.
