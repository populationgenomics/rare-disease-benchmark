"""The network the pipeline's Batch VMs attach to.

A custom-mode network with no firewall rules: GCP's implied rules then deny all inbound traffic and allow all outbound
traffic. The VMs need outbound access, because DRAGEN checks its licence with Illumina's server on every run and the
VMs have external addresses for it; nothing needs to reach them. The `default` network would instead admit SSH and RDP
from anywhere.
"""

from __future__ import annotations

import pulumi
import pulumi_gcp as gcp

_SUBNET_RANGE = '10.0.0.0/20'


class Network(pulumi.ComponentResource):
    """The pipeline's VPC and its one subnetwork.

    Attributes:
        network: The VPC, without firewall rules.
        subnetwork: The subnetwork in the deployment's region that Batch VMs get their addresses from.
    """

    def __init__(self, *, project: str, region: str, opts: pulumi.ResourceOptions | None = None) -> None:
        super().__init__('rare-disease-benchmark:infra:Network', 'network', None, opts)
        self.network = gcp.compute.Network(
            'pipeline',
            project=project,
            name='pipeline',
            auto_create_subnetworks=False,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.subnetwork = gcp.compute.Subnetwork(
            'pipeline',
            project=project,
            name='pipeline',
            region=region,
            network=self.network.id,
            ip_cidr_range=_SUBNET_RANGE,
            # Lets a VM reach Google APIs without its external address, should the VMs ever drop it.
            private_ip_google_access=True,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.register_outputs({})
