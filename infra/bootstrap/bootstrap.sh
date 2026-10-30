#!/usr/bin/env bash
#
# One-time setup of a deployment, run locally by someone with Owner on the project. Creates only what Pulumi needs
# before it can run: the bucket its state lives in, and the Cloud KMS key its secrets provider encrypts stack config
# with. Everything else is the Pulumi program. Re-running is safe.
#
# Usage: PROJECT=<project> REGION=<region> infra/bootstrap/bootstrap.sh

set -euo pipefail

PROJECT="${PROJECT:?set PROJECT to the GCP project to deploy into}"
REGION="${REGION:?set REGION to the region to deploy into, such as australia-southeast1}"
STATE_BUCKET="${PROJECT}-pulumi-state"
KEYRING='pulumi'
KEY='pulumi'

echo "Bootstrapping ${PROJECT} in ${REGION}"

# The APIs bootstrap uses, and the two the program cannot enable for itself.
gcloud services enable --project="${PROJECT}" \
  cloudkms.googleapis.com storage.googleapis.com serviceusage.googleapis.com cloudresourcemanager.googleapis.com

# State bucket: private and versioned, so an earlier state can be recovered.
if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" --project="${PROJECT}" --location="${REGION}" \
    --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning

# The key the gcpkms secrets provider wraps the stack's data key with.
gcloud kms keyrings describe "${KEYRING}" --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1 \
  || gcloud kms keyrings create "${KEYRING}" --project="${PROJECT}" --location="${REGION}"
gcloud kms keys describe "${KEY}" --project="${PROJECT}" --location="${REGION}" --keyring="${KEYRING}" >/dev/null 2>&1 \
  || gcloud kms keys create "${KEY}" --project="${PROJECT}" --location="${REGION}" --keyring="${KEYRING}" \
    --purpose=encryption

cat <<EOF

Done. Next, from infra/:

  export PULUMI_BACKEND_URL=gs://${STATE_BUCKET}
  pulumi stack init <stack> \\
    --secrets-provider gcpkms://projects/${PROJECT}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KEY}

Anyone who runs pulumi against this stack needs roles/cloudkms.cryptoKeyEncrypterDecrypter on that key.
EOF
