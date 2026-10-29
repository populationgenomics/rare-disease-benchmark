# CPG

The Centre for Population Genomics runs the build pipeline through Seqera, in the `rd-benchmark` dataset, launched with
its [analysis-runner](https://github.com/populationgenomics/analysis-runner). It doesn't use `infra/`: CPG's dataset
infrastructure ([cpg-infrastructure](https://github.com/populationgenomics/cpg-infrastructure)) already provides the
project (`rd-benchmark-220215`), the buckets, the Seqera compute environments and the accounts tasks run as.

## Where the pipeline's inputs live

- GRCh38 and the DRAGEN hash table are in `gs://cpg-common-main/references/`, managed by the
  [references](https://github.com/populationgenomics/references) repository (`dragen_hg38_pangenome_ht12` for the hash
  table). The GRCh38 copy is byte-identical to Broad's, which the 1000 Genomes CRAMs decode against.
- The DRAGEN image is built by hand from `build/containers/dragen`, because its installer is behind an Illumina login,
  and pushed to `australia-southeast1-docker.pkg.dev/cpg-common/images-dev/dragen`. Runs at the test access level pull
  it from there. Before runs at higher access levels, an analysis-runner job at the `full` level copies it to
  `cpg-common/images` with `skopeo copy`, keeping its digest.
- The DRAGEN API key is the Secret Manager secret `dragen-api-key` in the dataset's project. The dataset's accounts can
  read it; its analysis group can add and disable versions, but not read them:
  `gcloud secrets versions add dragen-api-key --project=rd-benchmark-220215 --data-file=-`.
- Outputs go to `gs://cpg-rd-benchmark-test` from test runs, and to `gs://cpg-rd-benchmark-main` from higher levels.

`test.params.yaml` holds these as the pipeline's params for test runs, with the image pinned by digest.

## Launching

A Seqera launch takes one params file, so copy `test.params.yaml` and add the run's own params, with the family sheet
and regions as `gs://` or `https://` paths. For the 1000 Genomes slice in `build/slice/`, at the launched commit:

```yaml
background: slice-na19240
family: https://raw.githubusercontent.com/populationgenomics/rare-disease-benchmark/<commit>/build/slice/family.csv
regions: https://raw.githubusercontent.com/populationgenomics/rare-disease-benchmark/<commit>/build/slice/regions.bed
```

Without `regions`, the run prepares the trio's whole genomes with every DRAGEN caller: a background.

Then launch at that commit:

```sh
analysis-runner seqera --dataset rd-benchmark --access-level test \
    --repository https://github.com/populationgenomics/rare-disease-benchmark \
    --main-script build/main.nf --commit-id <commit> \
    --params-file <run>.params.yaml
```

The analysis-runner launches with Nextflow's v2 syntax parser, which the pipeline needs. Access levels above `test` need
the commit to be on `main`.
