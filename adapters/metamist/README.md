# metamist

Adapters between the build pipeline (`build/`) and [Metamist](https://github.com/populationgenomics/metamist), for
deployments that keep their samples there. The pipeline knows no registry: it takes a sample sheet and publishes a
manifest (`samples.json`, `family.json`; see `build/README.md`). These adapters write the sheet from Metamist and
register the manifest's outputs in it.

The commands run as `python -m rare_disease_benchmark.metamist <command>`; from the repository root, prefix them with
`uv run --package rare-disease-benchmark-metamist`. They use the Metamist client's own configuration: `SM_URL` or
`SM_ENVIRONMENT` picks the deployment, and the user's Google credentials authenticate, as they do for reading the CRAMs
in cloud storage. Project names, families and bucket paths are always arguments, so the commands suit any deployment.
Every command stops with an error on records that are missing, ambiguous or contradictory, rather than guessing.

## ingest

Copies chosen participants from a source project into a target project, as one family:

```sh
python -m rare_disease_benchmark.metamist ingest \
    --source <source project> --target <target project> --family <background> \
    --cram-template 'gs://<bucket>/cram/{sequencing_group}.cram' \
    [--ped <file>] [--dry-run] <external id>...
```

Each member becomes a participant in the target with the source's external id and the member's sex. It holds one sample
with one genome sequencing group, whose one assay reads the source's CRAM and CRAI where they lie, so no file is copied.
The target mints its own sample and sequencing group ids, so the benchmark owns its records. The members then form the
family named by `--family`, with fathers and mothers from the pedigree.

- The source must hold exactly one participant per external id, and that participant exactly one active genome
  sequencing group (samples without a genome are ignored).
- `--cram-template` turns the source sequencing group's id into its CRAM's URL; the CRAI is the same URL with `.crai`
  appended. Both must exist.
- Sex and parents come from the source project's participants and families. If the source lacks them, give a PED file
  with `--ped`; its columns are read by position (family, individual, father, mother, sex), its family column is
  ignored, and so are the rows of anyone not being ingested, so the public 1000 Genomes pedigrees work as they are. When
  both record a member, they must agree.
- Every parent must be one of the members. Ingesting a child without both parents fails, because the source pedigree (or
  the PED file) names a parent outside the family.
- A rerun finds what the target already holds and writes only what is missing. An existing record that disagrees
  (another sex, another CRAM, the member in another family, the family holding someone else) stops the run before
  anything is written.
- `--dry-run` reads the source and target as usual, then prints the two calls it would make instead of making them: the
  participant upsert with its JSON payload, and the pedigree import with its PED file.

## sample-sheet

Writes the pipeline's sample sheet for one family in a project:

```sh
python -m rare_disease_benchmark.metamist sample-sheet --project <project> --family <background> --output <path>
```

There is one row per member. `sample` is the member's genome sequencing group id, `sex` is `male` or `female`, `father`
and `mother` are the parents' sequencing group ids (empty for a founder), and `cram` and `crai` are the files the
sequencing group's assay reads. `--output` takes a local path or a `gs://` URL.

## register

`register` reads a run's manifest and records its outputs in Metamist as analyses of the run's sequencing groups. The
sample sheet must have named each sample by its sequencing group id in the project:

```sh
python -m rare_disease_benchmark.metamist register \
    gs://<bucket>/<output_dir>/backgrounds/<background>/<version>/ \
    --project <metamist project> --pipeline-version <version> --dry-run
```

`--dry-run` still reads the manifest, checks every file it names and queries Metamist, then prints the `PUT` and `PATCH`
requests a real run would send. Without it the command sends them with the user's Google credentials.

For each sample it creates a `cram` and a `gvcf` analysis of the sample's sequencing group, and for the family one
`joint-calling` analysis of all of them, each as `completed`. The primary file's path goes in the `output` field, the
one seqr's CRAM sync and cpg-flow read. `meta` holds the keys CPG's pipelines write (`sequencing_type`, `stage`,
`dataset`, `sequencing_group`, `size`) and three that trace the analysis to its run: `background`, `pipeline_version`
and `published_dir`. The companion files (indexes, and the joint VCF's PED file) are checked but not registered: indexes
sit beside their files, and `published_dir` leads to the rest, as it does to the metrics and logs.

A rerun on the same manifest creates nothing, because an analysis is found by its type and its primary file's path. A
run of a newer version supersedes the older one: once its analyses exist, the command deactivates the analyses it
registered earlier for the same type, background and sequencing group, so that consumers taking the latest or every
active analysis see only the new files. It leaves analyses of other backgrounds, and analyses anything else registered,
alone. The module docstring of `register.py` covers the remaining cases: a rerun of an older version, a run interrupted
midway, and a version rolled back by hand.

Metamist records a file's size and checksum, and marks it valid, only if its service account can read the bucket.

## Around a pipeline run

A deployment puts a background family into its benchmark project once, then for each run writes the sheet and registers
what the run produced:

1. Run `ingest --dry-run` from the project holding the source samples into the benchmark's test project, and read the
   plan.
1. Run it again without `--dry-run`, then for the main project.
1. Run `sample-sheet` for the family, writing the sheet to the bucket the run reads from.
1. Launch the pipeline with that sheet as `family` and the family's name as `background` (`build/README.md`).
1. After the run, `register` its manifest, first with `--dry-run`.

The sheet's ids are the benchmark project's own sequencing group ids. The pipeline names samples after them, inside the
files too, so a source's sample names do not reach the outputs.
