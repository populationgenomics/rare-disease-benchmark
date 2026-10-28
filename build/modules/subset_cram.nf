// Cuts a member's CRAM down to the regions and names its sample after the sample sheet, keeping the read groups.
// Reads whose mate lies outside the regions come along unpaired.
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
    tuple val(sample), path("${sample}.subset.cram"), path("${sample}.subset.cram.crai")

    script:
    // DRAGEN names each output sample after the reads' SM tag, so the read groups take the sample sheet's id, whatever
    // the source calls the sample. A source whose read groups name several samples is refused rather than merged.
    """
    samtools view -C -M -L ${regions} -T ${reference} -X ${cram} ${crai} -o subset.cram
    samtools head subset.cram > source.sam
    names=\$(grep '^@RG' source.sam | grep -o 'SM:[^[:space:]]*' | sort -u)
    if [ "\$(printf '%s\\n' "\${names}" | grep -c .)" -ne 1 ]; then
        echo "read groups of ${cram} name other than one sample: \${names}" >&2
        exit 1
    fi
    awk 'BEGIN { FS = OFS = "\\t" } /^@RG/ { for (i = 2; i <= NF; i++) if (\$i ~ /^SM:/) \$i = "SM:${sample}" } { print }' \\
        source.sam > named.sam
    samtools reheader named.sam subset.cram > ${sample}.subset.cram
    samtools index ${sample}.subset.cram
    rm subset.cram source.sam named.sam
    """

    stub:
    """
    touch ${sample}.subset.cram ${sample}.subset.cram.crai
    """
}
