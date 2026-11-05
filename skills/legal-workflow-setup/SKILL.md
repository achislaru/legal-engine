---
name: legal-workflow-setup
description: Setup wizard of the legal engine (Moldova, Romania, EU). Creates the user's private profile outside the engine and fills it one question at a time - an optional page-reading service (Firecrawl) first, then firms, whom they sell to, modules on/off, languages, side and risk threshold, business niches and the laws to keep and monitor (through legal-watch), own samples and contracts, local tools, a first law download. Resumes where it stopped and never overwrites an answer silently. Use for "настрой юриста", "настроить юриста", "configurează juristul", "set up the lawyer", "legal engine setup", and when legal-workflow reports missing setup steps.
---

# Legal Workflow Setup

Resolve this skill's directory (`<skill-dir>`); the profile script is
`<skill-dir>/../legal-workflow/scripts/legal_profile.py` (`<lp>` below). The profile contract is
`../legal-workflow/references/profile.md`: read it first. The questions are in
[references/questionnaire.md](references/questionnaire.md); the starting text of each context file is in
`assets/context/`.

## Rules

- **One question per message**, with options, recommended first, each with what it leads to. Accept "default"
  and "skip". Talk in the user's language from their first message.
- **Script-only files.** `config.json`, `modules.json` and `context/integration-status.md` are written only by
  `<lp> profile init`, `<lp> modules set` and `<lp> step set`. Context files (`context/*.md`) are written from the
  templates with the user's answers.
- **Never overwrite silently.** Before writing a context file that exists, show its relevant part and ask: keep
  (recommended when it still fits) or replace with the new answer. A copied document never replaces an earlier
  copy (a taken name gets `-02`). Never delete a file or a folder of the profile; never touch `matters/`.
- **Nothing of the user goes into the engine folder**, the conversation is the only place answers are shown.
  Never ask for, read, print or store an API key, a token or a password; a paid service (for example Firecrawl,
  step `reading`) is connected by the user themselves through its own sign-in.
- **No legal conclusions here.** The wizard records preferences; any rule of law is checked later, in a matter.

## Run

1. `<lp> where` → profile folder and engine folder. No profile → step 0 of the questionnaire (`profile init`).
   A typed error (broken config, profile inside the engine) → tell the user which file to fix and stop.
2. `<lp> status` → `steps`. Called by `legal-workflow` for missing steps → run **only those**, each in full, with
   no depth question, and hand back; when `modules` is missing and `audience` is still `pending`, ask `audience`
   first (it gives the module suggestion). Called by the user → run every `pending` step in the order of the
   questionnaire; a `done` step is repeated only when the user asks (then: show, keep or replace).
3. Called by the user with more than three steps pending: ask the depth once (quick / full).
4. For each step: ask → write its file → `<lp> step set <id> --status done|skipped [--note …]` right away, so an
   interrupted run resumes at the next step. `skipped` means the defaults of `profile.md` apply; say which.
5. Finish with the summary of the questionnaire ("After the last step").

## Re-running

The wizard can be run again any time: it resumes from `context/integration-status.md`. To change one answer the
user can also use `legal-workflow-update`, or edit the file by hand (the wizard and the modules read the files,
not a copy of them).
