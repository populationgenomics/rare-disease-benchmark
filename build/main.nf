// Prepares a background family over a set of regions: cuts each member's public CRAM down to the regions, maps and
// calls each member with DRAGEN, and genotypes the family jointly in pedigree mode.

include { SUBSET_CRAM } from './modules/subset_cram'
include { DRAGEN_GERMLINE ; DRAGEN_GERMLINE_METERING_PREVIEW ; DRAGEN_PEDIGREE } from './modules/dragen'

params {
    // The background's name; the family id in the PED file and the prefix of the joint outputs.
    background: String
    // CSV with header sample,sex,father,mother,cram,crai. sex is male or female; father and mother name another row's
    // sample, or are empty for a founder.
    family: Path
    // BED file of the regions to fetch.
    regions: Path
    // The FASTA the CRAMs were compressed against, with its .fai beside it.
    cram_reference: Path
    // DRAGEN reference directory (hash table).
    dragen_reference: Path
    // Secret Manager secret version holding the DRAGEN API key: projects/<project>/secrets/<secret>/versions/<version>.
    dragen_api_key_secret: String
    // The DRAGEN image, in the deployment's private registry.
    dragen_container: String
    // Where the outputs are published; nextflow.config reads it, since a Seqera launch can only set it through params.
    output_dir: String?
    // Instead of analysing, ask Illumina how each member's DRAGEN run would be billed, at no charge.
    dragen_metering_preview: Boolean = false
    // Pass the regions to DRAGEN as its target BED, restricting small variant calling to them.
    dragen_target_regions: Boolean = false
    // Set by the analysis-runner on every launch; undeclared, it would fail the run.
    arGuid: String?
}

workflow {

    main:
    members = channel.fromPath(params.family).splitCsv(header: true).map { row -> checkMember(row) }

    cram_reference = tuple(
        params.cram_reference,
        params.cram_reference.resolveSibling("${params.cram_reference.name}.fai"),
    )

    crams = SUBSET_CRAM(
        members.map { m -> tuple(m.sample, m.cram, m.crai) },
        params.regions,
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
            params.dragen_api_key_secret,
        )
        samples = channel.empty()
        family = channel.empty()
    }
    else {
        samples = DRAGEN_GERMLINE(
            members_to_call,
            cram_reference,
            params.dragen_reference,
            target_bed,
            params.dragen_api_key_secret,
        ).map { sample, cram, crai, gvcf, tbi, all -> outputRecord(sample, [cram: cram, cram_index: crai, gvcf: gvcf, gvcf_index: tbi], all) }
        ped = members
            .map { m -> [params.background, m.sample, m.father ?: '0', m.mother ?: '0', m.sex == 'male' ? '1' : '2', '0'].join('\t') }
            .collectFile(name: "${params.background}.ped", newLine: true, sort: true)
        gvcfs = samples
            .toSortedList { a, b -> a.id <=> b.id }
            .map { records -> records.collectMany { r -> [r.gvcf, r.gvcf_index] } }
        previews = channel.empty()
        family = DRAGEN_PEDIGREE(params.background, gvcfs, ped, params.dragen_reference, params.dragen_api_key_secret)
            .combine(ped)
            .map { vcf, tbi, all, pedigree -> outputRecord(params.background, [vcf: vcf, vcf_index: tbi, pedigree: pedigree], all) }
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

// A record of one target's outputs: its id, the files a consumer looks for by role, and every other file the step
// wrote (metrics, logs), so that all of them are published.
def outputRecord(id, named, all) {
    def namedFiles = named.values() as Set
    return [id: id] + named + [other: all.findAll { f -> !(f in namedFiles) }.sort { f -> f.name }]
}

def checkMember(row) {
    if (!(row.sex in ['male', 'female'])) {
        error("sample ${row.sample}: sex must be male or female, got '${row.sex}'")
    }
    return row
}
