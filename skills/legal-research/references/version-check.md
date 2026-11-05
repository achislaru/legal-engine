# Current-version check of one act

The answer to "is this the version in force, and does anything else change how it applies?" for one act of
Moldova, Romania or the EU. Run it for every act a material conclusion rests on, before writing "the rule is in
force". It deepens step 7 of `<legal-workflow>/references/law-check.md`; it never replaces the register.

## Rule zero

"Current" is allowed only when every required point below is closed by an official source opened today, with a
verbatim quote. A point that could not be closed is `not_verified` with its reason and what depends on it. There is
no "ok", "probably unchanged" or "from memory". An empty list of amendments is a claim too: its evidence is the
page that shows the list and its last entry.

Strictness is in the **label**, not in stopping. When a point stays open the act is `not_verified` with a
**working conclusion**: the last text actually read, its date, the routes tried, what stays open. Work goes on
with that label; the dependent findings are `partial` in the register and are named to the user.

Today's date (system clock) is the check date; take every `checked_at` / `opened_at` from it (`date +%FT%T%z`), never type a time. The model knows no law after its training cut-off: anything newer
comes only from a source opened now.

## Input

For each act: an id (`<jurisdiction>.<kind>.<number>-<year>`, for example `ro.lege.287-2009`,
`eu.reg.2016-679`), the version we hold if any (label, date it applies from, date and SHA-256 of a saved copy) and
the provisions the answer cites. Check the cited provisions first: a change there that alters the conclusion
blocks it; other changes are information.

## The seven points

1. **`consolidation` — latest consolidated version against the one we hold.** Open the official record of the
   act and its list of versions. The version in force is the **latest one with a start date on or before the
   analysis date**; a later one is `next`, never current. Record its label and date, the held version and the
   difference.
2. **`amendments` — amending acts after the held version.** List every act published after it that changes this
   act: kind and number, adoption, official publication, entry into force, provisions touched. Look in the act's
   list of amendments **and separately** in the official journal for the period "held version → today": a
   consolidation lags the journal by days or weeks, and a change already published but not yet consolidated is
   the most dangerous place.
3. **`deferred_entry` — delayed entry and transitional rules.** For the act and each change: "intră în vigoare
   la …", "se aplică de la …", "în termen de N luni de la publicare", conditions. Keep four dates apart:
   adoption, publication, entry into force, start of application. A quote taken from a future version is wrong
   even when the words are right.
4. **`secondary_acts` — acts that detail or change the rule.** Government decisions, ministers' orders,
   regulators' decisions and instructions, EU implementing and delegated acts, adequacy decisions, standard
   clauses. For each: kind, publication, start date, effect, provisions touched, binding force and addressees.
   Guidelines and FAQs are not law; mark them so.
5. **`case_law` — decisions that change application.** Constitutional courts (a provision declared
   unconstitutional stops applying; when, depends on the system and is read in the decision and the
   constitution, never assumed), binding unification decisions of the supreme courts, CJEU rulings on the cited
   articles (an interpretation applies from the entry into force of the rule unless the judgment itself limits
   its effects in time). Record court, number or ECLI, date, operative part and binding force; check the binding
   force of each instrument in its own procedural rules, and mark a recommendation as such.
6. **`repeal` — repeal or replacement and the fate of references.** If the act was repealed, replaced or
   absorbed: the repealing act, the date, the transitional rules and, where it exists, the correlation table.
   Every reference of ours to a repealed rule is a finding: its new address or "no address found". Record it in
   the card's `repealed` (`by`, `from`).
7. **`status_of_changes` — in force / published, not in force / draft.** Each change mentioned gets one status:
   `in_force` (applies on the analysis date), `published_not_in_force` (in the official journal, later date),
   `draft` (a bill, a draft decision, a Commission proposal, a law passed but not promulgated or published). A
   draft does not change the law: it is mentioned for information, never as a risk or a finding.

`scope: "full"` requires all seven. `scope: "text"` (a quick question where the user accepts it) requires 1–3, 6
and 7; points 4–5 left open are still listed as gaps. Related acts and case law (points 4–5): where to look per
jurisdiction is in [access.md](access.md).

## Evidence

For each closed point: the URL of the official source (not an aggregator), the time it was opened **today** and a
verbatim quote of 15 to 300 characters in the language of the act: the line the conclusion stands on (the consolidation
label, "intră în vigoare", the operative part). Save the text you read when you can
(`<matter>/work/sources/<act>-<date>.txt`, `.html` or `.md`) and give `text_file` and `text_sha256`: the checker
then confirms that each quote is really in it (saved HTML is compared without tags and entities, saved markdown from
Firecrawl as plain text). The engine's Firecrawl reader writes such a file itself (`legal_watch.py fetch --url <url>
--out <matter>/work/sources/<act>-<date>.md`, only when allowed: `<legal-workflow>/references/law-check.md`). A
quote that was not machine-checked is reported as such.

An archived copy (for example the Wayback Machine) of an official page confirms the text on its own date, not the
current version: give `official: true` and `archived_on`. It never closes `consolidation`, `amendments` or
`status_of_changes` for "current" (only the live page shows whether something newer exists), and older than 14
days it closes no point for "current". A copy from an unofficial site is never evidence (`traps.md`).

The analysis date is never after the check date: a question about future conduct is answered as of today, with
adopted future changes in `next_versions` and `changes`.

## The card

One file per act: `<matter>/work/versions/<act-id>.json`, from [`../assets/version-card.json`](../assets/version-card.json).
Results:

- `current` — the required points are closed today, the held version (if any) equals the latest in force, no
  change in force after it, future versions recorded in `next_versions`;
- `outdated` — the held version is not the latest in force (older or future), a change in force is missing from
  it, or the act is repealed (`repealed.from` on or before the analysis date); `outdated_reason` says which;
- `not_verified` — a required point stays open; `working_conclusion` says what the answer may still rely on.

```bash
python3 <skill-dir>/scripts/check_version.py <matter>/work/versions/<act-id>.json --root <matter>
```

Exit 0 = the card's structure passed, 1 = errors listed, 2 = unreadable. It does not visit sites or judge a
reading; a green card still needs the agent's own reading.

## Into the source register

Each rule the answer cites from this act is a source in `<matter>/source-register.json` (`law-check.md`). The
card fills its checks: `full_text` from reading the provision, `amendments` (point 2), `repeal` (6),
`renumbering` (the cited provision's address now), `entry_into_force`, `application_date` and `transitional` (3).
Each note names the card (`work/versions/<act-id>.json`). Card → register source status:

| Card | Source in the register |
| --- | --- |
| `current` | `verified` (the provision itself read in that version) |
| `not_verified` | `partial`, with `unverified_impact`; never `verified` |
| `outdated` | the held text is `superseded`; the conclusion is drawn from the version in force (a new source) or the finding stays open |
| a version in `next_versions` | `future`, only for a notice about the future |

No script checks this link yet: reconcile it yourself before delivery. An `outdated` cited provision that changes the conclusion,
or a repealed act, blocks any "yes".
