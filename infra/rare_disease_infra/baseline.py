"""The enabled GCP services and the private image registry.

Everything else in a deployment depends on the services being enabled first, so they live in one component the other
resources can wait on.
"""

from __future__ import annotations

import pulumi
import pulumi_gcp as gcp

# The APIs the program's resources and the pipeline's tasks use. The bootstrap enables the few the program cannot
# turn on for itself (serviceusage, cloudresourcemanager) and those its own resources need (storage, cloudkms).
_REQUIRED_SERVICES = (
    'artifactregistry.googleapis.com',
    'batch.googleapis.com',
    'compute.googleapis.com',
    'iam.googleapis.com',
    'logging.googleapis.com',
    'secretmanager.googleapis.com',
    'storage.googleapis.com',
)


class Baseline(pulumi.ComponentResource):
    """Enabled services and the Docker registry the pipeline's images are pulled from.

    Attributes:
        services: The enabled services; a resource that calls one of these APIs depends on them.
        registry: The private Artifact Registry repository, which holds the DRAGEN image among others.
        image_prefix: The host and path images in `registry` are named under.
    """

    def __init__(self, *, project: str, region: str, opts: pulumi.ResourceOptions | None = None) -> None:
        super().__init__('rare-disease-benchmark:infra:Baseline', 'baseline', None, opts)
        # Left enabled when the program is destroyed (the provider's default since 10.0): other tooling may use them.
        self.services = [
            gcp.projects.Service(
                f'service-{service.split(".", 1)[0]}',
                project=project,
                service=service,
                opts=pulumi.ResourceOptions(parent=self),
            )
            for service in _REQUIRED_SERVICES
        ]
        self.registry = gcp.artifactregistry.Repository(
            'images',
            project=project,
            location=region,
            repository_id='images',
            format='DOCKER',
            description='Images the build pipeline runs, including the DRAGEN image, which must never be public.',
            opts=pulumi.ResourceOptions(parent=self, depends_on=self.services),
        )
        self.image_prefix = pulumi.Output.concat(region, '-docker.pkg.dev/', project, '/', self.registry.repository_id)
        self.register_outputs({'image_prefix': self.image_prefix})
