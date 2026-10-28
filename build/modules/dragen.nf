// DRAGEN 4.6 in Software Mode. Each task fetches the licence key itself (see containers/dragen/gcp-secret) into the
// VM's local /tmp: the key never passes through the pipeline's configuration, and never lands in the work directory,
// which on Google Batch is the bucket.

// DRAGEN refuses to start below --min-memory GB; the default gate (120) is sized for whole genomes. Leave headroom for
// the OS below the VM's memory.
def minMemoryGb(task) {
    return (task.memory.toGiga() * 0.85) as Integer
}

// One member's mapping and calling: everything but the licence and what the caller does with the run. Shared by the run
// itself and its metering preview, so that the preview prices exactly the command that runs. A target BED, when given,
// restricts small variant calling and its coverage reports to its regions; without one, the whole genome is called.
def germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed) {
    // DRAGEN discards the CRAM's alignments and duplicate flags and maps the reads afresh, keeping their read groups;
    // --cram-reference decodes the CRAM, which was compressed against a different FASTA (DRAGEN warns that it is not
    // used for the output CRAM, which it always compresses against the hash table's reference). The sex comes from the
    // pedigree: on a few megabases of reads DRAGEN's ploidy estimator has too little coverage to infer it.
    def args = [
        '--sw-mode',
        '--api-key-file /tmp/dragen-api-key',
        "--num-threads ${task.cpus}",
        "--min-threads ${task.cpus}",
        "--min-memory ${minMemoryGb(task)}",
        "--ref-dir ${ref_dir}",
        '--intermediate-results-dir /tmp/dragen',
        '--output-directory .',
        "--output-file-prefix ${sample}",
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
    if (target_bed) {
        args = args + ["--vc-target-bed ${target_bed}"]
    }
    return (['dragen'] + args).join(' \\\n    ')
}

process DRAGEN_GERMLINE {
    tag "${sample}"
    label 'dragen'

    input:
    tuple val(sample), val(sex), path(cram), path(crai)
    tuple path(cram_reference), path(cram_reference_fai)
    path ref_dir
    path target_bed // an empty list for none
    val api_key_secret

    output:
    // The named files fail the task when missing; '*' holds everything DRAGEN wrote: metrics, logs, the usage record.
    tuple val(sample), path("${sample}.cram"), path("${sample}.cram.crai"), path("${sample}.hard-filtered.gvcf.gz"), path("${sample}.hard-filtered.gvcf.gz.tbi"), path('*')

    script:
    """
    mkdir -p /tmp/dragen
    (umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)
    ${germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed)}
    """

    stub:
    """
    touch ${sample}.cram ${sample}.cram.crai ${sample}.hard-filtered.gvcf.gz ${sample}.hard-filtered.gvcf.gz.tbi
    touch ${sample}.mapping_metrics.csv dragen_run_stub.log
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
    path target_bed // an empty list for none
    val api_key_secret

    output:
    path "${sample}.metering-preview.txt"

    script:
    """
    mkdir -p /tmp/dragen
    (umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)
    ${germlineCommand(task, sample, sex, cram, cram_reference, ref_dir, target_bed)} \
        --metering-preview 2>&1 | tee ${sample}.metering-preview.txt
    """

    stub:
    """
    echo 'Tier: stub' > ${sample}.metering-preview.txt
    """
}

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
    def variants = gvcfs.findAll { gvcf -> gvcf.name.endsWith('.gvcf.gz') }.collect { gvcf -> "--variant ${gvcf}" }.join(' ')
    """
    mkdir -p /tmp/dragen
    (umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)
    dragen \\
        --sw-mode \\
        --api-key-file /tmp/dragen-api-key \\
        --num-threads ${task.cpus} \\
        --min-threads ${task.cpus} \\
        --min-memory ${minMemoryGb(task)} \\
        --ref-dir ${ref_dir} \\
        --intermediate-results-dir /tmp/dragen \\
        --output-directory . \\
        --output-file-prefix ${family} \\
        --enable-joint-genotyping true \\
        --pedigree-file ${ped} \\
        ${variants}
    """

    stub:
    """
    touch ${family}.hard-filtered.vcf.gz ${family}.hard-filtered.vcf.gz.tbi ${family}.vc_metrics.csv dragen_run_stub.log
    """
}
