// Names a member's sample after the sample sheet, keeping the read groups. Given regions, it first cuts the CRAM down to
// them, and reads whose mate lies outside the regions come along unpaired; without, it keeps the whole genome.
process PREPARE_CRAM {
    tag "${sample}"
    container 'quay.io/biocontainers/samtools:1.24--h9dcdb79_1@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'
    cpus 2
    memory 4.GB
    // A whole genome's CRAM, about 18 GB at 30x, lands on disk once as the renamed copy.
    disk 100.GB

    input:
    tuple val(sample), val(cram), val(crai)
    // An empty list for the whole genome.
    path regions
    tuple path(reference), path(reference_fai)

    output:
    tuple val(sample), path("${sample}.source.cram"), path("${sample}.source.cram.crai")

    script:
    // DRAGEN names each output sample after the reads' SM tag, so the read groups take the sample sheet's id, whatever
    // the source calls the sample. A source whose read groups name several samples is refused rather than merged.
    // Only the header changes, so a whole genome is copied container by container rather than decoded.
    def source = regions ? 'subset.cram' : cram
    def subset = regions ? "samtools view -C -M -L ${regions} -T ${reference} -X ${cram} ${crai} -o subset.cram" : ''
    """
    ${subset}
    samtools head ${source} > source.sam
    names=\$(grep '^@RG' source.sam | grep -o 'SM:[^[:space:]]*' | sort -u)
    if [ "\$(printf '%s\\n' "\${names}" | grep -c .)" -ne 1 ]; then
        echo "read groups of ${cram} name other than one sample: \${names}" >&2
        exit 1
    fi
    awk 'BEGIN { FS = OFS = "\\t" } /^@RG/ { for (i = 2; i <= NF; i++) if (\$i ~ /^SM:/) \$i = "SM:${sample}" } { print }' \\
        source.sam > named.sam
    samtools reheader named.sam ${source} > ${sample}.source.cram
    samtools index ${sample}.source.cram
    rm -f subset.cram source.sam named.sam
    """

    stub:
    """
    touch ${sample}.source.cram ${sample}.source.cram.crai
    """
}
