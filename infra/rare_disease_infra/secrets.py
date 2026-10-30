"""The DRAGEN licence key in Secret Manager.

DRAGEN Software Mode is licensed with an Illumina API key, which has no keyless alternative. Its value is encrypted
stack config (`config.require_secret`); the program provisions it into Secret Manager, where each DRAGEN task reads
it at run time (`build/containers/dragen/gcp-secret`).
"""

from __future__ import annotations

import pulumi
import pulumi_gcp as gcp


def dragen_api_key(
    *,
    project: str,
    region: str,
    api_key: pulumi.Input[str],
    opts: pulumi.ResourceOptions | None = None,
) -> gcp.secretmanager.Secret:
    """Provision the DRAGEN API key; its latest version carries `api_key`."""
    secret = gcp.secretmanager.Secret(
        'dragen-api-key',
        project=project,
        secret_id='dragen-api-key',  # noqa: S106 (the secret's name, not its value)
        replication=gcp.secretmanager.SecretReplicationArgs(
            user_managed=gcp.secretmanager.SecretReplicationUserManagedArgs(
                replicas=[gcp.secretmanager.SecretReplicationUserManagedReplicaArgs(location=region)],
            ),
        ),
        opts=opts,
    )
    # Rotating the key means updating the encrypted config value, which replaces this version; tasks read `latest`.
    gcp.secretmanager.SecretVersion(
        'dragen-api-key-current',
        secret=secret.id,
        secret_data=api_key,
        opts=pulumi.ResourceOptions(parent=secret),
    )
    return secret
