# rare-disease-benchmark

Groups building tools to diagnose rare genetic disease need test cases with known answers, and real cases can almost
never be shared. This repository holds the code for a benchmark built around that constraint: curated cases are placed
into the sequencing data of real, consented, public families, which yields synthetic genomes that look like a real case
to the tool under test, carry a known answer, and identify nobody. Releases of them can be exchanged and run by any
group.

## Concepts

A **case** is what a curator records for one solved case: the family, the clinical presentation of each member, the
placements (each putting one variant on one chromosome copy of one family member) and the diagnosis. A case names no
background genome, so it can be built into any background whose family structure fits.

A **background** is a real sequenced family, prepared once and fixed, into which cases are built.

A **case instance** is one case built into one background, as issued in one release: a synthetic genome for each family
member, with the pedigree and the clinical presentation. A release can hold several instances of the same case in
different backgrounds, so that results can be checked for robustness to the background.

A **release** is a versioned set of case instances that never changes after it is issued. Everything in it is on the
open side, which the system under test may see, or on the withheld side, which it may not. The schema makes the split
structural: every model is declared open or withheld, and one function produces the open side from the withheld records.

## Layout

| Folder    | Contents                                                                                    |
| --------- | ------------------------------------------------------------------------------------------- |
| `schema/` | The shared types: the case record, backgrounds, case instances, and what a system receives. |

Each top-level folder is its own package under the `rare_disease_benchmark` namespace and installs on its own.

This repository holds code and configuration only. No case, background genome or withheld side of any release is
committed, and the test fixtures are invented.

## Development

The workspace is managed with [uv](https://docs.astral.sh/uv/).

```sh
uv sync --group lint
uv run pre-commit install
uv run pytest
```

`uv run pre-commit run --all-files` runs the same static checks as CI: ruff, pyright and the formatters.

Dependency resolution ignores releases younger than seven days (`exclude-newer` in `pyproject.toml`), and Dependabot
waits the same period.

## Licence

Apache-2.0; see [LICENSE](LICENSE).
