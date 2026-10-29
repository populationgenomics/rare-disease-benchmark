# build

The Nextflow pipeline that prepares background families and, in later steps, builds cases into them. For now it does the
first step of preparing a background: it names each member's sample after the sample sheet, has DRAGEN 4.6 in Software
Mode map each member's whole genome afresh and run every caller, and calls the family jointly in pedigree mode. Phasing,
added variants and the case build follow; [docs/build.md](../docs/build.md) maps the whole design onto the pipeline.

Given `--regions`, a run prepares a slice instead: it cuts each CRAM down to the regions and calls small variants only.
Slices are for tests, and have the shape of a case build's run over windows.

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

generate the deployment's params and site config with
`uv run --group infra python infra/pipeline_config.py --stack <stack> --dragen-image-tag <tag>`. A run takes the
deployment's params plus its own: the background's name, its family sheet and its regions.

**From Seqera.** Seqera supplies the executor, project, region, service account and work directory, and selects no
profile, so a run takes a single params file holding both sets of params, with the family sheet and regions as `gs://`
or `https://` paths. Launch `build/main.nf` as the main script, with Nextflow's v2 syntax parser, which Seqera Platform
only uses when the launch asks for it. `deployments/cpg/` shows one deployment's launch.

**From a workstation**, which also needs the site config:

```sh
cd build
nextflow run main.nf -profile google -c <stack>.site.config -params-file <stack>.params.yaml \
    --background <name> \
    --family slice/family.csv
```

Adding `--regions slice/regions.bed` makes it a slice.

Adding `--dragen_metering_preview true` asks Illumina how each member's DRAGEN run would be billed instead of running
it: DRAGEN prints the application, the tier and the features that put the run there, then exits without analysing
anything or charging. The reports land in `metering-preview/` under the output directory. Run it before a new kind of
run costs anything.

Adding `--dragen_target_regions true` to a slice passes its regions to DRAGEN as its target BED (`--vc-target-bed`),
restricting small variant calling to them. Illumina then bills the run by the number of genes the regions touch rather
than by coverage.

`slice/` holds a 1000 Genomes trio and two regions of 2 Mb around the placed sites of the schema's test fixture, which
is enough to exercise every step in minutes.

## Outputs

Everything a run publishes sits under `<output_dir>/backgrounds/<background>/<version>/`, where the version is the
pipeline's (`manifest.version` in `nextflow.config`), so a run with another version sits beside the earlier ones:

```
samples/<sample>/   <sample>.cram (+ .crai), <sample>.hard-filtered.gvcf.gz (+ .tbi), every other caller's output,
                    DRAGEN's settings, metrics and logs
family/             <background>.hard-filtered.vcf.gz (+ .tbi), the PED file, the joint copy number, structural variant
                    and UPD calls, DRAGEN's settings, metrics and logs
samples.json        one record per sample: id, cram, cram_index, gvcf, gvcf_index, dragen_replay, other; for a whole
                    genome also sv_vcf, cnv_vcf and cnv_counts
family.json         one record for the family: id, vcf, vcf_index, pedigree, dragen_replay, other; for a whole genome
                    also cnv_vcf, sv_vcf and, for a trio, upd_vcf
```

`dragen_replay` is DRAGEN's record of every setting a run used, which a case build reuses so that its window runs score
reads as the background's runs did. Files the manifest names are looked up once their DRAGEN step has finished, so a
file missing under its expected name fails the run without discarding the step: `-resume` picks it up again.

The two JSON files are the pipeline's manifest: each record names a target and the paths its files were published to. A
deployment that keeps a sample registry reads them to register the outputs; the pipeline itself knows no registry.
Samples are named after the sample sheet's ids, inside the files too: the reads' read groups take the sheet's id, so the
source's own sample names do not carry through.

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
