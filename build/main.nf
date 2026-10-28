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
    // Instead of analysing, ask Illumina how each member's DRAGEN run would be billed, at no charge.
    dragen_metering_preview: Boolean = false
    // Pass the regions to DRAGEN as its target BED, restricting small variant calling to them.
    dragen_target_regions: Boolean = false
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
        called = DRAGEN_GERMLINE(
            members_to_call,
            cram_reference,
            params.dragen_reference,
            target_bed,
            params.dragen_api_key_secret,
        )
        ped = members
            .map { m -> [params.background, m.sample, m.father ?: '0', m.mother ?: '0', m.sex == 'male' ? '1' : '2', '0'].join('\t') }
            .collectFile(name: "${params.background}.ped", newLine: true, sort: true)
        gvcfs = called.gvcf
            .toSortedList { a, b -> a[0] <=> b[0] }
            .map { rows -> rows.collectMany { row -> [row[1], row[2]] } }
        previews = channel.empty()
        samples = called.all
        family = DRAGEN_PEDIGREE(params.background, gvcfs, ped, params.dragen_reference, params.dragen_api_key_secret)
    }

    publish:
    samples = samples
    family = family
    metering_previews = previews
}

output {
    samples {
        path 'samples'
    }
    family {
        path 'family'
    }
    metering_previews {
        path 'metering-preview'
    }
}

def checkMember(row) {
    if (!(row.sex in ['male', 'female'])) {
        error("sample ${row.sample}: sex must be male or female, got '${row.sex}'")
    }
    return row
}
