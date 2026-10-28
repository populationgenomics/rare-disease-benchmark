# metamist

Adapters between the build pipeline (`build/`) and [Metamist](https://github.com/populationgenomics/metamist), for
deployments that keep their samples there. The pipeline knows no registry: it takes a sample sheet and publishes a
manifest (`samples.json`, `family.json`; see `build/README.md`). These adapters write the sheet from Metamist and
register the manifest's outputs in it.

## Registering a run's outputs

`register` reads a run's manifest and records its outputs in Metamist as analyses of the run's sequencing groups. The
sample sheet must have named each sample by its sequencing group id in the project:

```sh
uv run python -m rare_disease_benchmark.metamist.register \
    gs://<bucket>/<output_dir>/backgrounds/<background>/<version>/ \
    --project <metamist project> --pipeline-version <version> --dry-run
```

`--dry-run` still reads the manifest, checks every file it names and queries Metamist, then prints the `PUT` and `PATCH`
requests a real run would send. Without it the command sends them with the user's Google credentials.

For each sample it creates a `cram` and a `gvcf` analysis of the sample's sequencing group, and for the family one
`joint-calling` analysis of all of them, each as `completed`. The `outputs` field holds the primary file with its index
(and, for the joint VCF, the PED file) as secondary files. `meta` holds the keys CPG's pipelines write
(`sequencing_type`, `stage`, `dataset`, `sequencing_group`, `size`) and three that trace the analysis to its run:
`background`, `pipeline_version` and `published_dir`. Metrics and logs are not registered, since nothing looks them up
as analyses and `published_dir` leads to them.

A rerun on the same manifest creates nothing, because an analysis is found by its type and its primary file's path. A
run of a newer version supersedes the older one: once its analyses exist, the command deactivates the analyses it
registered earlier for the same type, background and sequencing group, so that consumers taking the latest or every
active analysis see only the new files. It leaves analyses of other backgrounds, and analyses anything else registered,
alone. The module docstring of `register.py` covers the remaining cases: a rerun of an older version, a run interrupted
midway, and a version rolled back by hand.

Two consequences of how Metamist stores `outputs` matter to consumers. An analysis registered this way reads back with
an empty `output` field and the path in `outputs.path`, so tools that read only `output` (seqr's CRAM sync, for one) see
no file. And Metamist records a file's size and checksum, and marks it valid, only if its service account can read the
bucket.
