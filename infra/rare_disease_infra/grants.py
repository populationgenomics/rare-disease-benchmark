"""Every IAM grant the program makes, as a named capability.

Each class is one ability, and its docstring says what the holder can do with it. IAM bindings are made here and
nowhere else (tests/test_grants.py checks), so this file is the complete answer to who can do what in a deployment.
"""

from __future__ import annotations

from collections.abc import Mapping

import pulumi
import pulumi_gcp as gcp

_TYPE = 'rare-disease-benchmark:grants:'


def _role_name(role: str) -> str:
    return role.removeprefix('roles/').replace('.', '-')


class RunsBatchTasks(pulumi.ComponentResource):
    """Lets a VM's service account run Batch tasks: report task state to the Batch service and write task logs."""

    def __init__(self, name: str, *, project: str, member: pulumi.Input[str]) -> None:
        super().__init__(f'{_TYPE}RunsBatchTasks', name)
        for role in ('roles/batch.agentReporter', 'roles/logging.logWriter'):
            gcp.projects.IAMMember(
                f'{name}-{_role_name(role)}',
                project=project,
                role=role,
                member=member,
                opts=pulumi.ResourceOptions(parent=self),
            )
        self.register_outputs({})


class UsesBuckets(pulumi.ComponentResource):
    """Lets the holder list, read, write and delete objects in the given buckets, but not change the buckets."""

    def __init__(self, name: str, *, buckets: Mapping[str, gcp.storage.Bucket], member: pulumi.Input[str]) -> None:
        super().__init__(f'{_TYPE}UsesBuckets', name)
        for label, bucket in buckets.items():
            gcp.storage.BucketIAMMember(
                f'{name}-{label}',
                bucket=bucket.name,
                role='roles/storage.objectUser',
                member=member,
                opts=pulumi.ResourceOptions(parent=self),
            )
        self.register_outputs({})


class PullsImages(pulumi.ComponentResource):
    """Lets the holder pull images from the registry."""

    def __init__(self, name: str, *, registry: gcp.artifactregistry.Repository, member: pulumi.Input[str]) -> None:
        super().__init__(f'{_TYPE}PullsImages', name)
        gcp.artifactregistry.RepositoryIamMember(
            f'{name}-reader',
            project=registry.project,
            location=registry.location,
            repository=registry.name,
            role='roles/artifactregistry.reader',
            member=member,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.register_outputs({})


class PushesImages(pulumi.ComponentResource):
    """Lets the holder push images to the registry, and pull and overwrite them."""

    def __init__(self, name: str, *, registry: gcp.artifactregistry.Repository, member: pulumi.Input[str]) -> None:
        super().__init__(f'{_TYPE}PushesImages', name)
        gcp.artifactregistry.RepositoryIamMember(
            f'{name}-writer',
            project=registry.project,
            location=registry.location,
            repository=registry.name,
            role='roles/artifactregistry.writer',
            member=member,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.register_outputs({})


class ReadsSecret(pulumi.ComponentResource):
    """Lets the holder read the value of one secret."""

    def __init__(self, name: str, *, secret: gcp.secretmanager.Secret, member: pulumi.Input[str]) -> None:
        super().__init__(f'{_TYPE}ReadsSecret', name)
        gcp.secretmanager.SecretIamMember(
            f'{name}-accessor',
            project=secret.project,
            secret_id=secret.secret_id,
            role='roles/secretmanager.secretAccessor',
            member=member,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.register_outputs({})


class LaunchesPipelineRuns(pulumi.ComponentResource):
    """Lets the holder start Batch jobs whose VMs run as the task account, and follow them.

    Acting as the task account means a launcher can do whatever that account can, through a job it submits: read the
    DRAGEN key among it. Launchers are therefore trusted with the key.
    """

    def __init__(
        self,
        name: str,
        *,
        project: str,
        task_account: gcp.serviceaccount.Account,
        member: pulumi.Input[str],
    ) -> None:
        super().__init__(f'{_TYPE}LaunchesPipelineRuns', name)
        for role in ('roles/batch.jobsEditor', 'roles/logging.viewer'):
            gcp.projects.IAMMember(
                f'{name}-{_role_name(role)}',
                project=project,
                role=role,
                member=member,
                opts=pulumi.ResourceOptions(parent=self),
            )
        gcp.serviceaccount.IAMMember(
            f'{name}-act-as-tasks',
            service_account_id=task_account.name,
            role='roles/iam.serviceAccountUser',
            member=member,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.register_outputs({})
