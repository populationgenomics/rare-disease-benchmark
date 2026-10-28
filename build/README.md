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

- the 1000 Genomes FASTA the CRAMs were compressed against
  ([GRCh38_full_analysis_set_plus_decoy_hla.fa](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/technical/reference/GRCh38_reference_genome/)),
  with its `.fai`, under `references/1000genomes/`;
- Illumina's hg38 pangenome hash table, unpacked to
  `references/dragen/hg38-alt_masked.cnv.graph.hla.methyl_cg.rna-12-r6.0-1/`;
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

`slice/` holds a 1000 Genomes trio and two regions of 2 Mb around the placed sites of the schema's test fixture, which
is enough to exercise every step in minutes.

## Memory

DRAGEN Software Mode refuses to start with less than 120 GB of memory unless `--min-memory` lowers the gate. Memory use
is set mostly by the reference's hash table, which is loaded whole whatever the size of the input, so a regional run
needs less than a whole genome but not proportionally less. The DRAGEN processes ask for 60 GB on an 8-vCPU highmem VM
and lower the gate to match; this is to be measured on the first runs.

## Checks

The pre-commit hook `nextflow-lint` runs `nextflow lint -format` over this folder, in the official Nextflow image, so it
needs Docker but no local Nextflow. `nextflow run main.nf -stub-run -profile stub ...` with the same parameters runs the
wiring between processes locally, with placeholder outputs instead of DRAGEN. CI does both.
