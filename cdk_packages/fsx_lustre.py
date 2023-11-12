#!/usr/bin/env python
# -*- coding: utf-8 -*-

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ssm as ssm,
    aws_fsx as fsx,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class FSxLustre(cdk.NestedStack):

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Security groups for FSx for Lustre. Rules are based on
        # https://docs.aws.amazon.com/fsx/latest/LustreGuide/limit-access-security-groups.html
        sg_fsx_lustre_servers = ec2.SecurityGroup(
            self, 'SG FSx for Lustre file servers',
            vpc=params.network.vpc,
            description='FSx for Lustre file servers',
            allow_all_outbound=False
        )

        # Inbound rules for FSx for Lustre file servers.
        sg_fsx_lustre_servers.add_ingress_rule(
            ec2.Peer.ipv4(params.network.vpc.vpc_cidr_block),
            ec2.Port.tcp_range(988, 1023), 'Allows Lustre traffic'
        )

        # Outbound rules for FSx for Lustre file servers.
        sg_fsx_lustre_servers.add_egress_rule(
            ec2.Peer.ipv4(params.network.vpc.vpc_cidr_block),
            ec2.Port.tcp_range(988, 1023), 'Allows Lustre traffic'
        )

        self.cfn_fsx_file_system = fsx.CfnFileSystem(
            self, 'FSx Lustre',
            file_system_type='LUSTRE',
            subnet_ids=[params.network.subnets.subnet_ids[0]],
            lustre_configuration=fsx.CfnFileSystem.LustreConfigurationProperty(
                deployment_type='PERSISTENT_2',
                per_unit_storage_throughput=125,
            ),
            security_group_ids=[sg_fsx_lustre_servers.security_group_id],
            storage_capacity=2400,
            storage_type='SSD',
        )

        fsx.CfnDataRepositoryAssociation(
            self, 'Data repository association',
            data_repository_path=params.data.bucket.s3_url_for_object(),
            file_system_id=self.cfn_fsx_file_system.ref,
            file_system_path='/',
            batch_import_meta_data_on_create=True,
            s3=fsx.CfnDataRepositoryAssociation.S3Property(
                auto_export_policy=fsx.CfnDataRepositoryAssociation.AutoExportPolicyProperty(
                    events=['NEW', 'CHANGED', 'DELETED']
                ),
                auto_import_policy=fsx.CfnDataRepositoryAssociation.AutoImportPolicyProperty(
                    events=['NEW', 'CHANGED', 'DELETED']
                )
            ),
        )

        # Store the DNS and mount name in Parameter Store
        ssm.StringParameter(
            self, 'SSM parameter FSx for Lustre',
            parameter_name='/ONT-performance-benchmark/fsx-lustre-dns-mount-name',
            string_value=f'{self.cfn_fsx_file_system.attr_dns_name}@tcp:/'
                         f'{self.cfn_fsx_file_system.attr_lustre_mount_name}'
        )

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=sg_fsx_lustre_servers,
            suppressions=[
                {
                    'id': 'CdkNagValidationFailure',
                    'reason': 'Suppression warning caused by a parameter referencing an intrinsic function. However, '
                              'inbound address range is limited to IP range of AWS Batch compute instances.',
                },
            ],
            apply_to_children=True,
        )
