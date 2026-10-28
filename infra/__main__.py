"""Cloud infrastructure for running the build pipeline on Google Cloud Batch.

Reads the stack's config and composes the parts. Every deployment runs this same program; its differences live in
`Pulumi.<stack>.yaml`. The outputs are the values the pipeline's Nextflow config needs. See README.md.
"""

from __future__ import annotations

import re

import pulumi
import pulumi_gcp as gcp

from rare_disease_infra import baseline, grants, members, network, secrets, storage

config = pulumi.Config()
gcp_config = pulumi.Config('gcp')

project = gcp_config.require('project')
region = gcp_config.require('region')
# IAM members ('group:...') who launch pipeline runs and push its images. Launchers act as the task account, so they
# are trusted with everything it can read, the DRAGEN key included.
launchers: list[str] = config.require_object('pipelineLaunchers')
members.check_launchers(launchers)
dragen_api_key = config.require_secret('dragenApiKey')

base = baseline.Baseline(project=project, region=region)
after_services = pulumi.ResourceOptions(depends_on=base.services)

buckets = {
    'work': storage.work_bucket(project=project, region=region, opts=after_services),
    'data': storage.data_bucket(project=project, region=region, opts=after_services),
}
# Read by the image build only; nobody else is granted on it (an owner uploads the installer).
vendor = storage.vendor_bucket(project=project, region=region, opts=after_services)
pipeline_network = network.Network(project=project, region=region, opts=after_services)
dragen_key = secrets.dragen_api_key(project=project, region=region, api_key=dragen_api_key, opts=after_services)

# The identity every task VM runs as.
task_account = gcp.serviceaccount.Account(
    'pipeline-tasks',
    project=project,
    account_id='pipeline-tasks',
    display_name='Build pipeline tasks on Google Cloud Batch',
    opts=after_services,
)
grants.RunsBatchTasks('tasks-run', project=project, member=task_account.member)
grants.UsesBuckets('tasks-buckets', buckets=buckets, member=task_account.member)
grants.PullsImages('tasks-images', registry=base.registry, member=task_account.member)
grants.ReadsSecret('tasks-dragen-key', secret=dragen_key, member=task_account.member)

for launcher in launchers:
    label = re.sub(r'[^a-z0-9]+', '-', launcher.lower())
    grants.LaunchesPipelineRuns(f'{label}-launch', project=project, task_account=task_account, member=launcher)
    grants.UsesBuckets(f'{label}-buckets', buckets=buckets, member=launcher)
    grants.PushesImages(f'{label}-images', registry=base.registry, member=launcher)

# What the build pipeline's Nextflow config needs; nextflow_site_config.py renders it from these.
pulumi.export('project', project)
pulumi.export('region', region)
pulumi.export('workDir', buckets['work'].name.apply(lambda name: f'gs://{name}/work'))
pulumi.export('outputDir', buckets['data'].name.apply(lambda name: f'gs://{name}/results'))
pulumi.export('dataBucket', buckets['data'].name.apply(lambda name: f'gs://{name}'))
pulumi.export('vendorBucket', vendor.name.apply(lambda name: f'gs://{name}'))
pulumi.export('network', pipeline_network.network.id)
pulumi.export('subnetwork', pipeline_network.subnetwork.id)
pulumi.export('serviceAccountEmail', task_account.email)
pulumi.export('imagePrefix', base.image_prefix)
pulumi.export('dragenApiKeySecret', dragen_key.id.apply(lambda secret_id: f'{secret_id}/versions/latest'))
