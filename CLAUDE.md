# Rules for this repository

## This repository is public

Every file, commit message, branch name, pull request, issue and review comment here is world-readable once pushed, and
stays cached after deletion.

- No patient data, and nothing derived from a real case: no real variant tied to a phenotype, no case or sample
  accession, no text from a real referral or report. Fixtures are invented and say so.
- No names of case sources, cohorts or programmes, and nothing internal to any collaborating organisation: projects,
  datasets, systems, infrastructure (buckets, cloud projects, hosts), private repositories, documents or discussions.
  The schema takes such values as free-form data; they never appear as literals, enum members, examples, comments or
  test values.
- Give the reasoning in the text itself instead of pointing at a private document, thread or ticket.
- When unsure whether something may be public, leave it out and ask.

## Design invariants

- Every model derives from `visibility.OpenModel` or `visibility.WithheldModel`. Decide the side of a new model or field
  deliberately; put case fields in `Case.open` only if a system under test should receive them.
- `blinding.py` is the only code that copies withheld data to the open side. Do not add another path.
- A case names no background. What connects a case to a background is a `CaseInstance`.
- The open side says nothing about how a case instance was built: no background, no pipeline version. No open model has
  a field typed `CaseId` or `BackgroundId`.
- Open ids (case instance ids, release sample ids) reveal nothing about the case and differ between instances.

## Working norms

- Push back when a design, name or approach seems worse, with reasoning; offer a better alternative with its trade-offs.
  The author makes the final call.
- Investigate before producing: read the code and verify constraints rather than assuming a convention applies.
- Fail loudly: raise on missing or malformed input; never fall back to a default to carry on.
- Explain a non-obvious change before showing the diff. Ask when unsure rather than assume intent.

## Code style

- Python 3.13, `from __future__ import annotations` in every module.
- Import modules, not symbols (`import pathlib`, then `pathlib.Path`), except names from `typing` and `collections.abc`.
  No `TYPE_CHECKING` blocks.
- Models are frozen (`frozen=True` on every class, which pyright checks) and use tuples for sequences.
- Comments only for a non-obvious mechanism or constraint; no history narration.
- Tests assert invariants and test each validator with an input that violates it, not today's values.
- Never bypass the dependency age gate (`exclude-newer`, Dependabot cooldown).
