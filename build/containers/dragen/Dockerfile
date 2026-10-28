# DRAGEN 4.6 Software Mode for the pipeline's DRAGEN processes. The installer is Illumina's: it is never committed, and
# the image is pushed only to a private registry. It comes in as a named build context, so it need not sit in this
# tree:
#
#   docker build --platform linux/amd64 \
#       --build-context installer=<directory holding dragen-softwaremode-<version>.el9.x86_64.bin> \
#       -t <private registry>/dragen:<version> build/containers/dragen

# RHEL 9-compatible, which DRAGEN 4.6 supports alongside RHEL 8 and which is maintained for longer.
FROM almalinux:9.8-20261002@sha256:9819dc675b67b595c2b59e42be7763fca1a8bb217fa5944e04daa22e9a64db16

RUN dnf install -q -y jq && dnf clean all

RUN --mount=type=bind,from=installer,target=/installer \
    sh /installer/dragen-softwaremode-*.el9.x86_64.bin --nox11 --noprogress --target /opt/dragen

COPY gcp-secret /usr/local/bin/gcp-secret

ENV PATH="/opt/dragen/bin:${PATH}"
