// DRAGEN 4.6 in Software Mode. Each task fetches the licence key itself (see containers/dragen/gcp-secret) into the
// VM's local /tmp: the key never passes through the pipeline's configuration, and never lands in the work directory,
// which on Google Batch is the bucket.

// DRAGEN refuses to start below --min-memory GB; the default gate (120) is sized for whole genomes. Leave headroom for
// the OS below the VM's memory.
def minMemoryGb(task) {
    return (task.memory.toGiga() * 0.85) as Integer
}

process DRAGEN_GERMLINE {
    tag "${sample}"
    label 'dragen'

    input:
    tuple val(sample), val(sex), path(cram), path(crai)
    tuple path(cram_reference), path(cram_reference_fai)
    path ref_dir
    val api_key_secret

    output:
    tuple val(sample), path("${sample}/${sample}.hard-filtered.gvcf.gz"), path("${sample}/${sample}.hard-filtered.gvcf.gz.tbi"), emit: gvcf
    tuple val(sample), path("${sample}/${sample}.cram"), path("${sample}/${sample}.cram.crai"), emit: cram
    path "${sample}", emit: all

    script:
    // DRAGEN discards the CRAM's alignments and duplicate flags and maps the reads afresh, keeping their read groups;
    // --cram-reference decodes the CRAM, which was compressed against a different FASTA. The sex comes from the
    // pedigree: on a few megabases of reads DRAGEN's ploidy estimator has too little coverage to infer it.
    """
    mkdir -p ${sample} /tmp/dragen
    (umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)
    dragen \\
        --sw-mode \\
        --api-key-file /tmp/dragen-api-key \\
        --num-threads ${task.cpus} \\
        --min-threads ${task.cpus} \\
        --min-memory ${minMemoryGb(task)} \\
        --ref-dir ${ref_dir} \\
        --intermediate-results-dir /tmp/dragen \\
        --output-directory ${sample} \\
        --output-file-prefix ${sample} \\
        --cram-input ${cram} \\
        --cram-reference ${cram_reference} \\
        --pair-by-name true \\
        --sample-sex ${sex} \\
        --enable-map-align true \\
        --enable-map-align-output true \\
        --output-format CRAM \\
        --enable-duplicate-marking true \\
        --enable-variant-caller true \\
        --vc-emit-ref-confidence GVCF
    """

    stub:
    """
    mkdir -p ${sample}
    touch ${sample}/${sample}.hard-filtered.gvcf.gz ${sample}/${sample}.hard-filtered.gvcf.gz.tbi ${sample}/${sample}.cram ${sample}/${sample}.cram.crai
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
    path "${family}"

    script:
    // The caller's output depends on the order of its inputs, so the workflow passes the gVCFs sorted by sample.
    def variants = gvcfs.findAll { gvcf -> gvcf.name.endsWith('.gvcf.gz') }.collect { gvcf -> "--variant ${gvcf}" }.join(' ')
    """
    mkdir -p ${family} /tmp/dragen
    (umask 077 && gcp-secret ${api_key_secret} > /tmp/dragen-api-key)
    dragen \\
        --sw-mode \\
        --api-key-file /tmp/dragen-api-key \\
        --num-threads ${task.cpus} \\
        --min-threads ${task.cpus} \\
        --min-memory ${minMemoryGb(task)} \\
        --ref-dir ${ref_dir} \\
        --intermediate-results-dir /tmp/dragen \\
        --output-directory ${family} \\
        --output-file-prefix ${family} \\
        --enable-joint-genotyping true \\
        --pedigree-file ${ped} \\
        ${variants}
    """

    stub:
    """
    mkdir -p ${family}
    touch ${family}/${family}.hard-filtered.vcf.gz
    """
}
