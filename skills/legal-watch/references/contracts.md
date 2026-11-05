# Contracts in force: the clause index and re-review

The user's contracts in force are copies in `<profile>/contracts/` (step 9 of the wizard, or later on request);
the originals are never touched. Each gets an index `contracts/index/<file-stem>.json`:

```json
{"schema_version": 1, "contract": "services-2025.docx", "jurisdiction": "RO", "indexed_on": "2026-11-04",
 "clauses": [
   {"clause": "7.1", "topic": "personal data", "acts": [{"id": "eu.reg.2016-679", "provision": "art. 28"}],
    "source": "cited", "needs_reverify": false, "reverify": []},
   {"clause": "4.3", "topic": "late payment interest", "acts": [{"id": "ro.oug.13-2011", "provision": null}],
    "source": "inferred", "needs_reverify": false, "reverify": []}]}
```

## Building an index

1. `watch index scan <profile>/contracts/<file> --jurisdiction MD|RO` prints a draft from the citations in the
   text (laws, government decisions, ordinances, codes, EU regulations and directives, with the article when one
   is cited). `--write` saves it; an existing index is never replaced without `--force`.
2. Read the contract and complete the draft by hand: give each row a `topic`; add `inferred` rows for clauses
   whose subject is governed by an act they do not cite (payment terms, liability limits, withdrawal, personal
   data, employment terms, jurisdiction); drop citations that do not bear on a clause (a law named only in the
   definitions). Keep it short: only clauses a change of law could break.
3. Every act of an index must be in the watchlist, or its changes will never reach the clause:
   `watch index check` lists the ones that are not watched (being in the catalog is not enough); add them in the
   watchlist (setup.md §8). The scanner reads Romanian (`Legea nr. 287/2009`) and Moldovan (`Legea nr. 133 din
   08.07.2011`) citations, codes (a Romanian code under its approving law), EU acts in their cited order, and table
   cells of a DOCX.

The index names clause numbers and laws, never the parties or amounts: the working notes stay anonymous.

## When a law changes

A confirmed change (`new_in_force`, `new_future`, `repealed`) marks every clause that depends on that act:
`needs_reverify: true` with the change in `reverify`. A change that is only *possible* flags nothing.
`watch index pending` lists what waits. For each contract, propose one matter:

```bash
python3 <legal-workflow>/scripts/legal_profile.py matter new --slug reverify-<file-stem> --title "Re-review <file>" --module contracts
```

The matter audits the flagged clauses against the new version (read on the task date through `legal-research`),
proposes a Word redline or an addendum through `legal-contracts`, and the user decides. A future change is
prepared before its start date; nothing is sent to the other party by the engine. Clear a flag clause by clause,
only once that clause is re-reviewed against the law verified on the task date:
`watch index clear --contract <file> --clause N --matter <matter-id>`; the flag moves to `reviewed` with the
matter id. Without `--clause` every flag of the contract is cleared: only when all of them are re-reviewed. A partial
report (a source not verified, a clause left open) keeps the open flags; note the matter id in the report.
