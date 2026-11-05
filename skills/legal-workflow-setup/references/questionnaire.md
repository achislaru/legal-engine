# Questionnaire

One question per message, in the conversation language, with answer options: the recommended one first, each
with one plain line on what it leads to. "Default" and "skip" are always accepted. Explain once, at the start,
that the answers become ordinary text files in the profile which the user can edit later (step 1 `reading`
writes only a note in the step table).

Never invent a fact about the user. An answer that cannot be used gets one follow-up; after that the unknown part is
written as `[DE COMPLETAT: …]`.

## 0. Where the profile lives (before any step)

Run `legal_profile.py where`. If `exists` is false and `source` is a config, the profile was set up before and
its folder is missing (often a disk that is not connected): say so and ask — connect it and try again (recommended:
nothing changes) · start an empty profile in that place (`profile init --create`) · use another folder
(`profile init --dir <folder> --switch`). Never create it without that answer. If `exists` is false and there is
no config, ask:

- `~/legal-profile` (recommended) — a private folder in the home folder, outside the engine; back it up like any
  documents folder;
- another folder — any absolute path outside the engine (for example an encrypted or synced disk).

Then `legal_profile.py profile init [--dir <folder>]`. If it answers that the config already points elsewhere, ask
whether to keep the old profile (recommended: nothing changes) or to start the new one with `--switch` (the old
folder stays as it is).

## Depth

Ask once: **quick** (recommended for a first try, about 5 minutes: steps 1–4, where step 1 `reading` recommends
"later"; language taken from the user's messages, side and risk by default, the rest later: law monitoring and
documents stay for later) or **full** (about 15 minutes, every step). Quick still writes
the files of steps 5 and 6 and marks them `done` with the note `default`: conversation in the language of the
user's messages, documents in Romanian; risk threshold default; represented party the firm of step 2 when there is
exactly one, otherwise "ask in each matter".

## Steps

| Id | Question | Writes |
|---|---|---|
| `reading` | 1. Reading official sites (Firecrawl, optional) | — (step note) |
| `firms` | 2. Your firms | `context/company.md` |
| `audience` | 3. Whom you sell to | `context/company.md` (section "Whom the firms sell to") |
| `modules` | 4. Which modules to turn on | `modules.json` via `modules set` |
| `language` | 5. Languages | `context/language.md` |
| `side-risk` | 6. Side and risk | `context/side-and-risk.md` |
| `niches` | 7. Business niches and law categories | `legal-watch` (below) |
| `laws` | 8. Laws to download, how often, which engine | `legal-watch` (below) |
| `documents` | 9. Own samples, contracts in force, house style | `templates/`, `contracts/`, `context/house-style.md` |
| `tools` | 10. Local tools | — |
| `first-run` | 11. First download and trial monitoring | `legal-watch` (below) |

### 1. `reading`

Optional, and never needed by a module: "skip" keeps today's behaviour. One question per message, as everywhere.

**Why.** Official portals often refuse plain requests and the host's web tools (on 2026-11-05: legis.md answered
403, legislatie.just.ro dropped the connection; EU acts are still read free through the Publications Office).
Firecrawl is a service that may read such public pages for the engine, with no guarantee (on 2026-11-05 it read legis.md; legislatie.just.ro did not answer).
Without it those acts are checked by hand in the user's own browser, and in unattended monitoring runs they stay
"not verified". Monitoring sends it only legis.md and monitorul.gov.md pages
(`../legal-watch/references/engines.md`).

**Cost** (on 2026-11-05, check firecrawl.dev/pricing): Free plan 1,000 credits a month, 1 credit per page; Hobby
$19 a month (5,000 credits); Standard $99 a month (100,000 credits). An estimate, not a bill: monitoring costs about
the acts on legis.md and monitorul.gov.md that refuse plain requests × runs a month, plus the Gazette scan when it
refuses them too (up to 41 pages a run); a matter reads a few pages (`../legal-watch/references/engines.md`).

**Data.** Only the addresses of public official pages go to Firecrawl (a US service), never document text or
personal data.

"Shall the engine read official sites through Firecrawl?" Ask it in the message that gives the cost and the
data above. Options:

- connect both (recommended in the full depth: conversations and scheduled monitoring);
- only for conversations (the MCP tools, or the CLI through the engine's reader);
- only for monitoring (the CLI);
- later (recommended in the quick depth, then shown first: nothing is connected now; `legal-workflow-update`
  connects it any time);
- skip (today's behaviour: the host's web tools, then the user's browser, acts checked by hand).

Turning on a paid service needs the user's literal "yes" (`../legal-workflow/SKILL.md`): one of the three connect
options, chosen after the cost was said, is that yes for this step; a vague answer gets one follow-up.

**Connect.** First the user creates a Firecrawl account at firecrawl.dev (the Free plan is enough to start); the
sign-in commands below then open the browser to it. The user runs every command themselves, best in a plain
terminal: in Claude Code `! <command>` in the chat works too, but its output enters the conversation. The agent
never types a login command, a key or a token. Conversations need the MCP or the CLI; monitoring needs the CLI.

- MCP in Claude Code: `claude mcp add --scope user --transport http firecrawl https://mcp.firecrawl.dev/v2/mcp-oauth`,
  then `/mcp` → firecrawl → sign in in the browser.
- MCP in Codex: `codex mcp add firecrawl --url https://mcp.firecrawl.dev/v2/mcp-oauth`, then
  `codex mcp login firecrawl`.
- CLI: `npm i -g firecrawl-cli` (needs Node.js), then `firecrawl login --browser`.

Never use a key in chat, the `--api-key` option, the CLI's credentials file, `firecrawl view-config` or
`firecrawl env`, or the local `firecrawl-mcp` package (it needs a key).

**Verify.**

- MCP: Firecrawl tools (for example a scrape tool named `firecrawl_scrape`) appear in the agent's own tool list. If
  they don't, a reconnect or a new session may be needed.
- CLI: run `python3 <engine>/tools/doctor.py` and read the `Firecrawl CLI` line: `OK` means logged in; `installed,
  not logged in` or `login state unknown` means not yet.
- No test scrape without a separate "yes": it costs a credit.

**Record** (the note is the consent; the scripts check it too; grammar `conversation: on|off; monitoring: on|off`,
then `waiting: <what>` for a part not working yet):

- connected as chosen: `legal_profile.py step set reading --status done --note "conversation: on; monitoring: on"`
  (`off` for the part not chosen);
- one chosen part works, the other not yet: `done` with the working part `on` and the other `off; waiting: <what>`,
  for example `"conversation: on; monitoring: off; waiting: cli login"` (the doctor line is not `OK`); record it
  again with `on` once it works;
- nothing chosen works yet: `--status pending --note "conversation: on; monitoring: on; waiting: <what>"`, for
  example `waiting: restart for MCP tools`; the wizard asks again at the next run, until then Firecrawl is not used;
- later: `--status skipped --note "later"`; skip: `--status skipped --note "not connected"`.

**Monitoring follows the resulting note** once `laws/watchlist.yaml` exists (after step 8, also when this row becomes
`done` later; before it, step 8 offers the engine). `watch` = `legal_watch.py` of `../legal-watch/SKILL.md`:

- `monitoring: on` in a `done` row: `watch engines add firecrawl`;
- `monitoring` no longer `on` (off, pending, skipped): `watch engines remove firecrawl`;
- only `conversation` changed: no engines command.

Both keep the other engines and change nothing when there is nothing to change (`"changed": false`). After
`"changed": true`, if a weekly job is installed: `watch schedule plan`, then `watch schedule install` again after the
user's yes (cron: the new line of `watch schedule plan --kind cron`).

The scripts check the note themselves: `watch fetch` refuses without `conversation: on`, adding `firecrawl` (`watch
init --engines`, `watch engines add|set`) refuses without `monitoring: on`, and a run whose engines still name
`firecrawl` without it skips Firecrawl (no credit) and says so in the digest. A skipped or pending row never turns
it on, even when an MCP server is connected (`../legal-workflow/references/law-check.md`).

### 2. `firms`

Two questions, one after the other (facts, so no recommended option): "Which firm (or firms) is this for, in
which country and with which legal form?", then for each firm "What does it do, is it a VAT payer, does it have a
website, employees, a brand of its own?". A person without a firm is fine: write "natural person" and the country. Several
firms → one section each. Registration numbers are optional; never ask for personal identity numbers.

### 3. `audience`

"Whom do you sell to?" (a fact: options, none recommended) Options: firms only · people, online · people, offline · both. Then, only if not known
yet: where the clients are, whether there are employees, whether a brand name is used. Suggest modules:

| Fact | Suggests |
|---|---|
| sells to consumers (any channel) | `consumer` |
| consumers, employees, a website with forms or analytics, or any client list | `privacy` |
| employees, or plans to hire | `employment` |
| a brand or product name other than the firm's own legal name | `trademark` |

Write the facts and the suggestion into the section of `company.md`.

### 4. `modules`

Show every optional module from `../legal-workflow/assets/modules.json` (its `label`), mark the suggested ones and
whether each is in the installed version (`legal_profile.py status` → `modules`; `not-installed` = comes with a later
engine version, it can be switched on now and starts working after the update). Options: the suggestion
(recommended) · choose myself · all off for now. Core modules (contracts, legal question, law monitoring) are always
on; say so. Write with `legal_profile.py modules set <id>=on|off …` for every optional module, so the file records
an explicit answer for each.

### 5. `language`

"In which language shall we talk, and in which language are documents written?" Conversation: the language of the
user's messages (recommended). Documents: Romanian for documents under Moldovan or Romanian law (recommended,
`recomandare`), Russian, English, or bilingual. The language a law requires for a given document is checked in the
matter, not here.

### 6. `side-risk`

"When a choice carries little risk, may I decide it myself?" Options: default (recommended: low risk decided by the
engine and listed in the summary; medium or high risk, money or the business model asked, `norms.md` §6) ·
stricter (ask about every choice beyond wording) · looser (also decide medium risks that involve no money: no
price, payment, penalty or liability amount). Then the default
represented party: the firm from step 2 (recommended when there is one firm) or "ask in each matter".

### 7, 8, 11. `niches`, `laws`, `first-run` (law library and monitoring)

These belong to the `legal-watch` module. If `../legal-watch/references/setup.md` exists, follow it for each of these
steps. If it does not (`modules.watch` is `not-installed`), do not ask anything and do not invent a watchlist: leave
the steps `pending` with the note `legal-watch not installed`
(`legal_profile.py step set <id> --status pending --note "legal-watch not installed"`) and tell the user that
the law library and monitoring come with an engine update; every answer still checks the law live.

### 9. `documents`

"Do you have your own contract samples or contracts in force that the engine should know?" Options: not now
(recommended for a first try) · samples · contracts in force · both. Copy (never move) each file the user names:
samples into `templates/`, contracts in force into `contracts/`; the originals stay untouched. Name the copies
with short latin words (`supply-contract-2025.docx`); a name already taken gets `-02`, `-03`, … (never overwrite
an earlier copy). The clause index of each contract in force is built by
`legal-watch` (`../legal-watch/references/contracts.md`) at the step `first-run`, or right away when the law library
already exists; until `legal-watch` is installed the files just wait there.

Then, optional (skip by default): default forum for disputes and any preferred clauses → `context/house-style.md`
from `assets/context/house-style.md`. Write the file even when nothing is chosen, so `legal-workflow-update`
has a place for later decisions.

### 10. `tools`

Run `python3 <engine>/tools/doctor.py` (`<engine>` is the `engine` field of `legal_profile.py where`). List in one message
what is missing and what each missing part serves for the modules that are on; required first:

| Part | Needed for | Install |
|---|---|---|
| engine skills linked into the skills folder (`MISS skill …`) | every module, required | `cd <engine> && ./install.sh` |
| Python environment `.venv` | every document (DOCX), required | `cd <engine> && ./install.sh` |
| LibreOffice (`soffice`), Poppler (`pdftoppm`) | visual check of a document as PDF | the user's package manager (e.g. `brew install --cask libreoffice`, `brew install poppler`) |
| `tesseract` with ron, rus, eng | scanned contracts | `brew install tesseract tesseract-lang` |
| Playwright Chromium | law monitoring without a conversation (`legal-watch`); it never passes an anti-bot page, so Moldovan and Romanian acts are still checked by hand in a conversation | `cd <engine> && WITH_PLAYWRIGHT=1 ./install.sh` |
| Firecrawl CLI (optional, step 1) | only when the `reading` note has `monitoring: on`: monitoring of legis.md and monitorul.gov.md when they refuse plain requests | shown, never installed by the agent: the user runs `npm i -g firecrawl-cli` and `firecrawl login --browser` themselves; not offered again when `reading` was skipped |

One request for approval for the whole list (the Firecrawl row is not part of it) (options: install all (recommended when only required parts are missing)
· only the required ones · none now). Install only after the user's literal "yes" for that list. Declined parts are
written in the step note (`--note "no LibreOffice: visual check off"`); the work goes on without them. The step is
`done` when everything required is present, `skipped` when the user declined a required part.

## After the last step

Run `legal_profile.py status`. Tell the user in a few lines: the profile folder, the files written (each can be
edited by hand), the modules on and off, steps still pending and why, and that `legal-workflow-update` changes any
of it later. The profile files stay on this computer and never go into the engine repository; what is said in
the conversation and the documents the agent reads are processed by the AI host the user chose, under its
provider's terms. The engine itself sends nothing anywhere, except the addresses of official pages it asks Firecrawl
to read where the user allowed it (step `reading`).
