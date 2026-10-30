// Prepares a background family: names each member's sample after the sample sheet, maps and calls each member with
// DRAGEN, and calls the family jointly in pedigree mode. Without regions, the members' whole genomes go through every
// DRAGEN caller; given regions, the run is a slice for testing, cut down to them and called for small variants only.

include { PREPARE_CRAM } from './modules/prepare_cram'
include { DRAGEN_GERMLINE ; DRAGEN_GERMLINE_METERING_PREVIEW ; DRAGEN_PEDIGREE ; DRAGEN_JOINT_CNV ; DRAGEN_JOINT_SV ; DRAGEN_UPD } from './modules/dragen'

params {
    // The background's name; the family id in the PED file and the prefix of the joint outputs.
    background: String
    // CSV with header sample,sex,father,mother,cram,crai. sex is male or female; father and mother name another row's
    // sample, or are empty for a founder.
    family: Path
    // BED file of the regions a slice is cut down to. Without it, whole genomes.
    regions: Path?
    // The FASTA the CRAMs were compressed against, with its .fai beside it.
    cram_reference: Path
    // DRAGEN reference directory (hash table).
    dragen_reference: Path
    // Secret Manager secret version holding the DRAGEN API key: projects/<project>/secrets/<secret>/versions/<version>.
    dragen_api_key_secret: String
    // The DRAGEN image, in the deployment's private registry.
    dragen_container: String
    // Where the outputs are published; nextflow.config reads it, so a launch sets it without a config of its own.
    output_dir: String?
    // Instead of analysing, ask Illumina how each member's DRAGEN run would be billed, at no charge.
    dragen_metering_preview: Boolean = false
    // Pass a slice's regions to DRAGEN as its target BED, restricting small variant calling to them.
    dragen_target_regions: Boolean = false
    // Set by the analysis-runner on every launch; undeclared, it would fail the run.
    arGuid: String?
}

workflow {

    main:
    def whole_genome = !params.regions
    if (whole_genome && params.dragen_target_regions) {
        error('--dragen_target_regions needs --regions')
    }

    members = channel.fromPath(params.family).splitCsv(header: true).map { row -> checkMember(row) }

    cram_reference = tuple(
        params.cram_reference,
        params.cram_reference.resolveSibling("${params.cram_reference.name}.fai"),
    )

    crams = PREPARE_CRAM(
        members.map { m -> tuple(m.sample, m.cram, m.crai) },
        params.regions ?: [],
        cram_reference,
    )
    members_to_call = members
        .map { m -> tuple(m.sample, m.sex) }
        .join(crams, failOnMismatch: true, failOnDuplicate: true)

    target_bed = params.dragen_target_regions ? params.regions : []

    if (params.dragen_metering_preview) {
        previews = DRAGEN_GERMLINE_METERING_PREVIEW(
            members_to_call,
            cram_reference,
            params.dragen_reference,
            target_bed,
            whole_genome,
            params.dragen_api_key_secret,
        )
        samples = channel.empty()
        family = channel.empty()
    }
    else {
        previews = channel.empty()
        samples = DRAGEN_GERMLINE(
            members_to_call,
            cram_reference,
            params.dragen_reference,
            target_bed,
            whole_genome,
            params.dragen_api_key_secret,
        ).map { sample, cram, crai, gvcf, tbi, all ->
            def named = [cram: cram, cram_index: crai, gvcf: gvcf, gvcf_index: tbi, dragen_replay: outputFile(all, "${sample}-replay.json")]
            if (whole_genome) {
                named = named + [
                    sv_vcf: outputFile(all, "${sample}.sv.vcf.gz"),
                    cnv_vcf: outputFile(all, "${sample}.cnv.vcf.gz"),
                    cnv_counts: outputFile(all, "${sample}.tn.tsv.gz"),
                ]
            }
            outputRecord(sample, named, all)
        }

        ped = members
            .map { m -> [params.background, m.sample, m.father ?: '0', m.mother ?: '0', m.sex == 'male' ? '1' : '2', '0'].join('\t') }
            .collectFile(name: "${params.background}.ped", newLine: true, sort: true)
        // The callers' output depends on the order of their inputs, so they take the members sorted by sample.
        sorted_samples = samples.toSortedList { a, b -> a.id <=> b.id }

        joint = DRAGEN_PEDIGREE(
            params.background,
            sorted_samples.map { records -> records.collectMany { r -> [r.gvcf, r.gvcf_index] } },
            ped,
            params.dragen_reference,
            params.dragen_api_key_secret,
        )
        // The family record gathers the joint steps' files; each step contributes its named files and everything it wrote.
        parts = joint
            .map { vcf, tbi, all ->
                [named: [vcf: vcf, vcf_index: tbi, dragen_replay: outputFile(all, "${params.background}-replay.json")], all: all]
            }
            .mix(ped.map { p -> [named: [pedigree: p], all: []] })

        if (whole_genome) {
            cnv = DRAGEN_JOINT_CNV(
                params.background,
                sorted_samples.map { records -> records.collect { r -> r.cnv_counts } },
                ped,
                params.dragen_reference,
                params.dragen_api_key_secret,
            ).map { all -> [named: [cnv_vcf: outputFile(all, "${params.background}-cnv.cnv.vcf.gz")], all: all] }
            sv = DRAGEN_JOINT_SV(
                params.background,
                sorted_samples.map { records -> records.collectMany { r -> [r.cram, r.cram_index] } },
                ped,
                params.dragen_reference,
                params.dragen_api_key_secret,
            ).map { all -> [named: [sv_vcf: outputFile(all, "${params.background}-sv.sv.vcf.gz")], all: all] }
            parts = parts.mix(cnv, sv)

            // The UPD caller takes exactly one trio: one child and its two parents.
            trio_child = members
                .toList()
                .map { ms -> ms.size() == 3 ? ms.findAll { m -> m.father && m.mother } : [] }
                .filter { children -> children.size() == 1 }
                .map { children -> children[0].sample }
            child_cnv = trio_child
                .combine(samples)
                .filter { child, r -> r.id == child }
                .map { _child, r -> r.cnv_vcf }
            upd = DRAGEN_UPD(
                params.background,
                joint.map { vcf, tbi, _all -> tuple(vcf, tbi) },
                child_cnv,
                ped,
                params.dragen_reference,
                params.dragen_api_key_secret,
            ).map { all -> [named: [upd_vcf: outputFile(all, "${params.background}-upd.upd.vcf.gz")], all: all] }
            parts = parts.mix(upd)
        }

        family = parts
            .toList()
            .flatMap { ps -> [outputRecord(params.background, ps.collectEntries { p -> p.named }, ps.collectMany { p -> p.all })] }
    }

    publish:
    samples = samples
    family = family
    metering_previews = previews
}

// One folder per background and pipeline version, so a rerun with another version, or of another preparation pass,
// sits beside the earlier ones. Each index lists its records with the paths their files were published to: what an
// adapter for a sample registry reads.
output {
    samples {
        path { r -> "backgrounds/${params.background}/${workflow.manifest.version}/samples/${r.id}/" }
        index {
            path "backgrounds/${params.background}/${workflow.manifest.version}/samples.json"
        }
    }
    family {
        path { _r -> "backgrounds/${params.background}/${workflow.manifest.version}/family/" }
        index {
            path "backgrounds/${params.background}/${workflow.manifest.version}/family.json"
        }
    }
    metering_previews {
        path "backgrounds/${params.background}/${workflow.manifest.version}/metering-preview"
    }
}

// A record of one target's outputs: its id, the files a consumer looks for by role, and every other file the steps
// wrote (metrics, logs, the other callers' outputs), so that all of them are published.
def outputRecord(id, named, all) {
    def namedFiles = named.values() as Set
    return [id: id] + named + [other: all.findAll { f -> !(f in namedFiles) }.sort { f -> f.name }]
}

// A file a DRAGEN step wrote, looked up by name once the task has finished: a missing one fails the run here, where
// -resume can pick it up again, rather than failing the task and discarding the analysis it paid for.
def outputFile(files, name) {
    def file = files.find { f -> f.name == name }
    if (!file) {
        error("DRAGEN wrote no ${name}")
    }
    return file
}

def checkMember(row) {
    if (!(row.sex in ['male', 'female'])) {
        error("sample ${row.sample}: sex must be male or female, got '${row.sex}'")
    }
    return row
}
