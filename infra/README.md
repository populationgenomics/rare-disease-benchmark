# infra

Cloud infrastructure for running the build pipeline (`build/`) on Google Cloud Batch: a Pulumi program in Python, one
stack per deployment, each in its own GCP project. The same program serves every deployment; what differs lives in
`Pulumi.<stack>.yaml`, which is committed, with its secrets encrypted by the deployment's Cloud KMS key.

## What it creates

| Module                           | What                                                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rare_disease_infra/baseline.py` | The enabled APIs, and the private Artifact Registry repository the DRAGEN image is pushed to.                                                     |
| `rare_disease_infra/storage.py`  | The work bucket (Nextflow work directories, deleted after 30 days) and the data bucket (references, prepared backgrounds, outputs). Both private. |
| `rare_disease_infra/network.py`  | A VPC without firewall rules, so nothing can reach the VMs, and its subnetwork. VMs reach out to Illumina's licence server.                       |
| `rare_disease_infra/secrets.py`  | The DRAGEN API key in Secret Manager, from encrypted stack config.                                                                                |
| `rare_disease_infra/grants.py`   | Every IAM grant, as a named capability whose docstring says what the holder can do.                                                               |
| `__main__.py`                    | Reads the stack config, composes the above, creates the task VMs' service account and exports what the Nextflow config needs.                     |
| `nextflow_site_config.py`        | Renders the build pipeline's Nextflow config for a stack from its outputs.                                                                        |
| `bootstrap/bootstrap.sh`         | One-time setup of what Pulumi itself needs: the state bucket and the KMS key.                                                                     |

The task VMs run as `pipeline-tasks@<project>`, which can report to Batch, write logs, pull images, use both buckets and
read the DRAGEN key. The groups in `pipelineLaunchers` can start Batch jobs as that account, follow their logs, use the
buckets and push images. Acting as the task account gives a launcher everything it can read, so launchers are trusted
with the DRAGEN key.

## A new deployment

1. Run `PROJECT=<project> REGION=<region> bootstrap/bootstrap.sh` with Owner on the project.
1. From `infra/`, after `uv sync --group infra` in the repository root:
   ```sh
   export PULUMI_BACKEND_URL=gs://<project>-pulumi-state
   pulumi stack init <stack> --secrets-provider gcpkms://projects/<project>/locations/<region>/keyRings/pulumi/cryptoKeys/pulumi
   pulumi config set --stack <stack> gcp:project <project>
   pulumi config set --stack <stack> gcp:region <region>
   pulumi config set --stack <stack> --path 'pipelineLaunchers[0]' group:<address>
   pulumi config set --stack <stack> --secret dragenApiKey < <file holding the key>
   pulumi up --stack <stack>
   ```
   `PULUMI_BACKEND_URL` selects the state bucket for these commands only; `pulumi login` would switch the backend for
   every Pulumi project on the machine.
1. Build the DRAGEN image (`build/containers/dragen/Dockerfile`) and push it under the `imagePrefix` output.
1. Copy the DRAGEN hash table and the 1000 Genomes FASTA into the data bucket (`build/README.md`).
1. Generate the pipeline's Nextflow config from the stack's outputs:
   `uv run --group infra python infra/nextflow_site_config.py --stack <stack> --dragen-image-tag <tag>`, which writes
   `build/<stack>.site.config` (ignored by git).

`pipelineLaunchers` names groups only: the stack config is public, and the program rejects any other kind of member.

## Deployments

| Stack | Project                      | Region               |
| ----- | ---------------------------- | -------------------- |
| `cpg` | `cpg-rare-disease-benchmark` | australia-southeast1 |

## Tests

`uv run pytest infra/tests` runs the program under Pulumi's mocks, with an invented config and no cloud access, and
checks invariants of what it would create (and every committed `Pulumi.<stack>.yaml` against the program's rules on
config): every IAM binding belongs to a capability in `grants.py`, no basic role or public member is granted, only the
task account reads the DRAGEN key, the buckets are private and the network has no firewall rules.
