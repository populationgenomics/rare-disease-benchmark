"""The project's buckets, one per storage policy.

The work bucket holds Nextflow's work directories, which are only needed while a run can be resumed, so objects
expire. The data bucket holds what outlives a run: the reference files, prepared backgrounds and published outputs.
The vendor bucket holds proprietary software that is fetched by hand, such as Illumina's DRAGEN installer, apart from
the data so that what builds images can read it without reading the data. All are private; access is IAM only
(`grants`).
"""

from __future__ import annotations

import pulumi
import pulumi_gcp as gcp

# Long enough to resume or inspect a failed run, short enough that abandoned work directories don't accumulate.
WORK_RETENTION_DAYS = 30


def work_bucket(*, project: str, region: str, opts: pulumi.ResourceOptions | None = None) -> gcp.storage.Bucket:
    return gcp.storage.Bucket(
        'work',
        project=project,
        name=f'{project}-work',
        location=region,
        uniform_bucket_level_access=True,
        public_access_prevention='enforced',
        lifecycle_rules=[
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(type='Delete'),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(age=WORK_RETENTION_DAYS),
            )
        ],
        # Expired work directories are gone for good; a soft-delete window would only keep paying for them.
        soft_delete_policy=gcp.storage.BucketSoftDeletePolicyArgs(retention_duration_seconds=0),
        opts=opts,
    )


def data_bucket(*, project: str, region: str, opts: pulumi.ResourceOptions | None = None) -> gcp.storage.Bucket:
    # Everything here can be fetched again or rebuilt by the pipeline, so the GCS-default soft delete covers an
    # accidental deletion and no versioning is kept. `pulumi destroy` refuses a non-empty bucket.
    return gcp.storage.Bucket(
        'data',
        project=project,
        name=f'{project}-data',
        location=region,
        uniform_bucket_level_access=True,
        public_access_prevention='enforced',
        opts=opts,
    )


def vendor_bucket(*, project: str, region: str, opts: pulumi.ResourceOptions | None = None) -> gcp.storage.Bucket:
    # An installer can only be fetched again through the vendor's login, so an overwritten or deleted one stays
    # recoverable as a noncurrent version.
    return gcp.storage.Bucket(
        'vendor',
        project=project,
        name=f'{project}-vendor',
        location=region,
        uniform_bucket_level_access=True,
        public_access_prevention='enforced',
        versioning=gcp.storage.BucketVersioningArgs(enabled=True),
        opts=opts,
    )
