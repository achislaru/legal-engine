# legal-engine — rules for agents

Public repository: an AI lawyer (Moldova, Romania, EU) as Claude Code skills, set up per user by a wizard.

- **No personal data, ever.** The engine is generic. A user's firms, niches, contracts, downloaded laws and
  matters live only in their profile (default `~/legal-profile/`, path in `~/.config/legal-engine/config.json`),
  never in this repo. Examples use invented firms and the reserved domains example.com / .net / .org (example.md and
  example.ro are real sites).
- `python3 tools/check.py` must show **0 FAIL** before every commit (the pre-commit hook runs it). The owner
  keeps a git-ignored `tools/denylist.local.txt` with real names; never commit it, never print it.
- No keys: the engine works with the host's built-in web tools, a local browser, or a reading service the user
  connected themselves (Firecrawl, through its own sign-in: the hosted MCP or the CLI's own login). A skill never
  reads, asks for, prints or stores a key; skipped, the free route stays.
- Law is never cached as truth: every conclusion "the rule is in force" is re-checked against the official
  text on the task date. A failed fetch is "not verified", never "no changes".
- The engine never signs, sends, publishes or files anything; that needs the user.
- Code: stdlib or `requirements.txt` only, typed errors with clear messages, tests in `tools/tests` and each
  skill's `tests/` (coverage ≥ 85 %). Comment the *why*.
- Git: one feature per branch `phase-1/<slug>`, steps as separate commits, explicit paths (no `git add -A`),
  never `--no-verify`. Nothing reaches `main` without the owner's literal «да».
- Read at session start: this file, `README.md`, `docs/STATUS.md`. On demand: skill files, `CHANGELOG.md`.
