# Profile contract

The profile holds everything that belongs to one user. It lives **outside the engine folder** (the script
refuses a profile inside it). The engine never commits, uploads or shares it.

## Where it is

`~/.config/legal-engine/config.json` (another file: environment variable `LEGAL_ENGINE_CONFIG`):

```json
{"profile_dir": "~/legal-profile"}
```

`profile_dir` is absolute or starts with `~`. No config means the default `~/legal-profile`.
A broken config is an error to show the user, never a reason to guess another folder.

The setup wizard creates the folders and writes the config with `legal_profile.py profile init [--dir <folder>]`
(idempotent; refuses the home folder itself, a folder inside the engine or containing it and, without
`--switch`, a second folder when the config already names one; a configured folder that is missing, for example on
a disk that is not connected, is recreated only with `--create`; nothing is ever moved or deleted). `where` also reports the engine folder.

## Layout

```text
<profile>/
  context/
    company.md            firms: country, legal form, VAT, activity, B2B/B2C, website
    side-and-risk.md      whose side we hold, threshold "decide myself / ask" (default: norms.md §6)
    language.md           language of conversation and language of documents, separately
    house-style.md        own placeholders, preferred clauses, default court/arbitration, user decisions
    integration-status.md setup steps (table below)
  modules.json            optional modules on/off
  templates/              the user's own sample documents (optional)
  matters/                see matters.md
  laws/                   watchlist.yaml, state.json, texts/, runs/, issues.json, report.html (legal-watch,
                          see its references/library.md)
  contracts/              the user's contracts in force + index/ (legal-watch)
  trademarks/             portfolio.json: own marks and their dates (legal-trademark; created on first use)
```

## modules.json

```json
{"schema_version": 1, "privacy": true, "consumer": false, "trademark": false, "employment": true}
```

Written only by `legal_profile.py modules set <id>=on|off …` (a new file lists every optional module). Only the
optional modules from `assets/modules.json` are allowed; a missing key means off. Core modules (contracts,
research, watch) are always on and are not listed.

## Setup steps (`context/integration-status.md`)

The wizard keeps one table row per step; a missing row means `pending`.

```markdown
| Step | Status | Updated | Note |
|---|---|---|---|
| firms | done | 2026-11-04 | |
| audience | skipped | 2026-11-04 | |
```

Status is `done`, `skipped` or `pending`. The wizard and the update skill write rows **only through the script**
(`legal_profile.py step set <step> --status <status> [--note …]`), never by hand. The step ids and the file each
step writes are listed once, in `assets/modules.json` (`steps`); the table below explains them:

| Step id | Wizard question | File it writes |
|---|---|---|
| reading | 1. reading official sites (Firecrawl, optional) | — (step note) |
| firms | 2. your firms | `context/company.md` |
| audience | 3. whom you sell to → suggested modules | `context/company.md` |
| modules | 4. confirm modules | `modules.json` |
| language | 5. languages | `context/language.md` |
| side-risk | 6. side and risk threshold | `context/side-and-risk.md` |
| niches | 7. business niches and law categories | `laws/watchlist.yaml` |
| laws | 8. acts to download, frequency, engine | `laws/watchlist.yaml` |
| documents | 9. own samples and contracts in force | `templates/`, `contracts/` |
| tools | 10. local tools | — |
| first-run | 11. first download and trial monitoring | `laws/runs/` |

Every module needs `firms`, `modules`, `language`, `side-risk` (`base_needs`); a module may need more
(`legal-watch`: `niches`, `laws`). `reading` is not a base need and no module needs it: skipping it, or leaving it
`pending`, never blocks a module. A step marked `done` whose file is missing counts as `pending`.
`legal_profile.py status --module <id>` returns exactly the missing steps.

`skipped` counts as satisfied; then the modules use these defaults:

| Skipped step | Default |
|---|---|
| reading | no reading service: the host's web tools, then the user's browser; monitoring engines `urllib,host` |
| firms | ask for the party in each matter; unknown details go in as `[DE COMPLETAT: …]` |
| modules | all optional modules off (`status` reports them `off`, not `unset`) |
| language | the language of the user's message; legal text in the language of the governing law |
| side-risk | the represented party is asked once in each matter (the user's firm is the recommended answer); threshold of `norms.md` §6 |

## Versions

`modules.json` and `intake.json` carry `schema_version`. A file of another version is an error that names the
file; `legal-workflow-update` migrates it. The script never rewrites a user file to a new version on its own.
