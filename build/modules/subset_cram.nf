// Cuts a member's CRAM down to the regions, keeping its read groups. Reads whose mate lies outside the regions come
// along unpaired.
process SUBSET_CRAM {
    tag "${sample}"
    container 'quay.io/biocontainers/samtools:1.24--h9dcdb79_1@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'
    cpus 2
    memory 4.GB

    input:
    tuple val(sample), val(cram), val(crai)
    path regions
    tuple path(reference), path(reference_fai)

    output:
    tuple val(sample), path("${sample}.cram"), path("${sample}.cram.crai")

    script:
    // DRAGEN names each output sample after the reads' SM tag, so every read group must carry the sample sheet's name
    // for the PED file to match.
    """
    samtools view -C -M -L ${regions} -T ${reference} -X ${cram} ${crai} -o ${sample}.cram --write-index
    names=\$(samtools head ${sample}.cram | grep '^@RG' | grep -o 'SM:[^[:space:]]*' | sort -u | tr '\\n' ' ')
    if [ "\${names}" != "SM:${sample} " ]; then
        echo "read groups of ${cram} name \${names}instead of ${sample}" >&2
        exit 1
    fi
    """

    stub:
    """
    touch ${sample}.cram ${sample}.cram.crai
    """
}
