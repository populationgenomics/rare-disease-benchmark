// DRAGEN 4.6 in Software Mode. Each task fetches the licence key itself (see containers/dragen/gcp-secret) into the
// VM's local /tmp: the key never passes through the pipeline's configuration, and never lands in the work directory,
// which on Google Batch is the bucket.

// DRAGEN refuses to start below --min-memory GB; the default gate (120) is sized for whole genomes. Leave headroom for
// the OS below the VM's memory.
def minMemoryGb(task) {
    return (task.memory.toGiga() * 0.85) as Integer
}

// A DRAGEN command: the arguments every run needs, then the run's own.
def dragenCommand(task, ref_dir, prefix, args) {
    def common = [
        '--sw-mode',
        '--api-key-file /tmp/dragen-api-key',
        "--num-threads ${task.cpus}",
        "--min-threads ${task.cpus}",
        "--min-memory ${minMemoryGb(task)}",
        "--ref-dir ${ref_dir}",
        '--intermediate-results-dir /tmp/dragen',
        '--output-directory .',
        "--output-file-prefix ${prefix}",
    ]
    return (['dragen'] + common + args).join(' \\\n    ')
}

def fetchKey(api_key_secret) {
    return "mkdir -p /tmp/dragen\n(umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)"
}

// One member's mapping and calling: everything but the licence and what the caller does with the run. Shared by the run
// itself and its metering preview, so that the preview prices exactly the command that runs.
def germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed, whole_genome) {
    // DRAGEN discards the CRAM's alignments and duplicate flags and maps the reads afresh, keeping their read groups;
    // --cram-reference decodes the CRAM, which was compressed against a different FASTA (DRAGEN warns that it is not
    // used for the output CRAM, which it always compresses against the hash table's reference). The sex comes from the
    // pedigree, which DRAGEN's ploidy estimator cannot infer from a slice.
    def args = [
        "--cram-input ${cram}",
        "--cram-reference ${cram_reference}",
        '--pair-by-name true',
        "--sample-sex ${sex}",
        '--enable-map-align true',
        '--enable-map-align-output true',
        '--output-format CRAM',
        '--enable-duplicate-marking true',
        '--enable-variant-caller true',
        '--vc-emit-ref-confidence GVCF',
    ]
    // Illumina's germline WGS recipe for 4.6, so that a background carries everything a laboratory's genome does.
    // Left out: annotation, which needs the Nirvana database and which a system under test does not receive, and
    // allele-specific copy number, which needs a population SNP VCF. A slice gets small variants only: the copy number
    // caller normalises against the whole genome's coverage.
    if (whole_genome) {
        args = args + [
            '--enable-sv true',
            '--enable-cnv true',
            '--enable-hla true',
            '--enable-targeted true',
            '--enable-star-allele true',
            '--enable-pgx true',
            '--repeat-genotype-enable true',
            '--enable-mrjd true',
        ]
    }
    // A target BED restricts small variant calling and its coverage reports to its regions.
    if (target_bed) {
        args = args + ["--vc-target-bed ${target_bed}"]
    }
    return dragenCommand(task, ref_dir, sample, args)
}

process DRAGEN_GERMLINE {
    tag "${sample}"
    label 'dragen'

    input:
    tuple val(sample), val(sex), path(cram), path(crai)
    tuple path(cram_reference), path(cram_reference_fai)
    path ref_dir
    // An empty list for none.
    path target_bed
    val whole_genome
    val api_key_secret

    output:
    // The named files fail the task when missing; '*' holds everything DRAGEN wrote, which the workflow sorts into roles.
    tuple val(sample), path("${sample}.cram"), path("${sample}.cram.crai"), path("${sample}.hard-filtered.gvcf.gz"), path("${sample}.hard-filtered.gvcf.gz.tbi"), path('*')

    script:
    """
    ${fetchKey(api_key_secret)}
    ${germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed, whole_genome)}
    """

    stub:
    def callers = whole_genome ? "${sample}.sv.vcf.gz ${sample}.cnv.vcf.gz ${sample}.tn.tsv.gz ${sample}.repeats.vcf.gz" : ''
    """
    touch ${sample}.cram ${sample}.cram.crai ${sample}.hard-filtered.gvcf.gz ${sample}.hard-filtered.gvcf.gz.tbi
    touch ${sample}-replay.json ${sample}.mapping_metrics.csv dragen_run_stub.log ${callers}
    """
}

// Asks Illumina how the run of DRAGEN_GERMLINE with the same inputs would be billed: DRAGEN prints the application, the
// tier and the features that put it there, then exits without analysing anything or consuming a licence.
process DRAGEN_GERMLINE_METERING_PREVIEW {
    tag "${sample}"
    label 'dragen'

    input:
    tuple val(sample), val(sex), path(cram), path(crai)
    tuple path(cram_reference), path(cram_reference_fai)
    path ref_dir
    // An empty list for none.
    path target_bed
    val whole_genome
    val api_key_secret

    output:
    path "${sample}.metering-preview.txt"

    script:
    """
    ${fetchKey(api_key_secret)}
    ${germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed, whole_genome)} \\
        --metering-preview 2>&1 | tee ${sample}.metering-preview.txt
    """

    stub:
    """
    echo 'Tier: stub' > ${sample}.metering-preview.txt
    """
}

// Small variants, genotyped jointly from the members' gVCFs in pedigree mode, which adds de novo calls.
process DRAGEN_PEDIGREE {
    tag "${family}"
    label 'dragen'

    input:
    val family
    path gvcfs
    path ped
    path ref_dir
    val api_key_secret

    output:
    tuple path("${family}.hard-filtered.vcf.gz"), path("${family}.hard-filtered.vcf.gz.tbi"), path('*')

    script:
    // The caller's output depends on the order of its inputs, so the workflow passes the gVCFs sorted by sample.
    def variants = gvcfs.findAll { gvcf -> gvcf.name.endsWith('.gvcf.gz') }.collect { gvcf -> "--variant ${gvcf}" }
    def args = ['--enable-joint-genotyping true', "--pedigree-file ${ped}"] + variants
    """
    ${fetchKey(api_key_secret)}
    ${dragenCommand(task, ref_dir, family, args)}
    """

    stub:
    """
    touch ${family}.hard-filtered.vcf.gz ${family}.hard-filtered.vcf.gz.tbi ${family}-replay.json ${family}.vc_metrics.csv
    """
}

// Copy number, segmented jointly from the members' normalised counts, with de novo events in the child.
process DRAGEN_JOINT_CNV {
    tag "${family}"
    label 'dragen'

    input:
    val family
    path counts
    path ped
    path ref_dir
    val api_key_secret

    output:
    path '*'

    script:
    def args = ['--enable-cnv true', "--pedigree-file ${ped}"] + counts.collect { c -> "--cnv-input ${c}" }
    """
    ${fetchKey(api_key_secret)}
    ${dragenCommand(task, ref_dir, "${family}-cnv", args)}
    """

    stub:
    """
    touch ${family}-cnv.cnv.vcf.gz ${family}-cnv-replay.json
    """
}

// Structural variants, called jointly from the members' DRAGEN CRAMs, with de novo scores in the child.
process DRAGEN_JOINT_SV {
    tag "${family}"
    label 'dragen'

    input:
    val family
    path crams
    path ped
    path ref_dir
    val api_key_secret

    output:
    path '*'

    script:
    // The CRAMs were written by DRAGEN against the hash table's reference, so they decode without --cram-reference.
    def inputs = crams.findAll { c -> c.name.endsWith('.cram') }.collect { c -> "--cram-input ${c}" }
    def args = ['--enable-map-align false', '--enable-sv true', '--sv-denovo-scoring true', "--pedigree-file ${ped}"] + inputs
    """
    ${fetchKey(api_key_secret)}
    ${dragenCommand(task, ref_dir, "${family}-sv", args)}
    """

    stub:
    """
    touch ${family}-sv.sv.vcf.gz ${family}-sv-replay.json
    """
}

// Uniparental disomy in the child of a trio, from the joint small variant calls, with the child's copy number masking
// aneuploid regions.
process DRAGEN_UPD {
    tag "${family}"
    label 'dragen'

    input:
    val family
    tuple path(vcf), path(vcf_index)
    path child_cnv
    path ped
    path ref_dir
    val api_key_secret

    output:
    path '*'

    script:
    def args = ['--enable-upd-caller true', "--pedigree-file ${ped}", "--variant ${vcf}", "--upd-proband-cnv ${child_cnv}"]
    """
    ${fetchKey(api_key_secret)}
    ${dragenCommand(task, ref_dir, "${family}-upd", args)}
    """

    stub:
    """
    touch ${family}-upd.upd.vcf.gz ${family}-upd-replay.json
    """
}
