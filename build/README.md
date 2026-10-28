# build

The Nextflow pipeline that prepares background families and, in later steps, builds cases into them. For now it prepares
a background over a set of regions: it cuts each member's public CRAM down to the regions, has DRAGEN 4.6 in Software
Mode map the reads afresh and call each member, and genotypes the family jointly in pedigree mode. Phasing, added
variants and read editing follow.

## Running on Google Cloud Batch

Every task runs on its own short-lived VM, so nothing runs between pipeline runs. The Nextflow process that orchestrates
a run can stay on a laptop.

The infrastructure is a Pulumi program in `infra/`; its README sets up a deployment. Once a stack is up and the
references are in its data bucket:

- the references, which `infra/references.py` puts into the data bucket and checks: GRCh38 under `references/grch38/`,
  and Illumina's hg38 pangenome hash table under `references/dragen/`. The CRAMs were compressed against
  `GRCh38_full_analysis_set_plus_decoy_hla.fa`; Broad's `Homo_sapiens_assembly38.fasta` has the same 3,366 sequences
  (names, lengths and MD5s, in order), and copies within GCS;
- the DRAGEN image, built from `containers/dragen` with Illumina's Software Mode installer and pushed under the stack's
  `imagePrefix` output (the Dockerfile shows the command; the installer and the image are never published);

generate the site config and run:

```sh
uv run --group infra python infra/nextflow_site_config.py --stack <stack> --dragen-image-tag <tag>
cd build
nextflow run main.nf -profile google -c <stack>.site.config \
    --background <name> \
    --family slice/family.csv \
    --regions slice/regions.bed
```

Adding `--dragen_metering_preview true` asks Illumina how each member's DRAGEN run would be billed instead of running
it: DRAGEN prints the application, the tier and the features that put the run there, then exits without analysing
anything or charging. The reports land in `metering-preview/` of the output directory. Run it before a new kind of run
costs anything.

Adding `--dragen_target_regions true` passes the regions to DRAGEN as its target BED (`--vc-target-bed`), restricting
small variant calling to them. Illumina then bills the run by the number of genes the regions touch rather than by
coverage.

`slice/` holds a 1000 Genomes trio and two regions of 2 Mb around the placed sites of the schema's test fixture, which
is enough to exercise every step in minutes.

## Memory

DRAGEN Software Mode refuses to start with less than 120 GB of memory unless `--min-memory` lowers the gate, and its
memory use is set by the reference rather than the input: on a 64 GB VM it ran out on a few megabases of reads, having
loaded the hash table and sized its sort buffers for a whole genome. The DRAGEN processes therefore run on 16-vCPU
highmem VMs (128 GB, which Illumina recommends even for panels and low-pass genomes), ask for 120 GB and lower the gate
to match.

## Checks

The pre-commit hook `nextflow-lint` runs `nextflow lint -format` over this folder, in the official Nextflow image, so it
needs Docker but no local Nextflow. `nextflow run main.nf -stub-run -profile stub ...` with the same parameters runs the
wiring between processes locally, with placeholder outputs instead of DRAGEN. CI does both.
