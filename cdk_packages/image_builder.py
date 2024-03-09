#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Useful resource:
Build and Deploy Docker Images to AWS using EC2 Image Builder
https://aws.amazon.com/blogs/devops/build-and-deploy-docker-images-to-aws-using-ec2-image-builder/
"""

import os.path

import aws_cdk as cdk
import boto3
import pandas as pd
from aws_cdk import (
    aws_iam as iam,
    aws_ssm as ssm,
    aws_imagebuilder as imagebuilder,
)
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class ImageBuilder(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        # ---------- infrastructure configuration --------------------

        # EC2 instance role
        self.ec2_instance_role = iam.Role(
            self, "EC2 Image Builder instance role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="EC2 Image Builder instance role",
        )
        self.ec2_instance_profile = iam.CfnInstanceProfile(
            self, "EC2 Image Builder instance_profile",
            roles=[self.ec2_instance_role.role_name],
            instance_profile_name='ec2_image_builder_instance_profile',
        )

        # add standard management policies
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'))
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('EC2InstanceProfileForImageBuilderECRContainerBuilds'))
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('EC2InstanceProfileForImageBuilder'))

        # store CloudWatch agent configuration in SSM Parameter Store
        ssm.StringParameter(
            self, 'SSM parameter CloudWatch agent configuration for AWS Batch container instances',
            parameter_name='/ONT-performance-benchmark/aws-batch-container-instances-cloudwatch-agent-config',
            string_value=open(os.path.join(dirname, 'assets', 'cloudwatch_agent_config_batch_compute.json')).read(),
        ).grant_read(self.ec2_instance_role)

        self.infra_cfg = imagebuilder.CfnInfrastructureConfiguration(
            self, 'ONT image infrastructure',
            instance_profile_name=self.ec2_instance_profile.instance_profile_name,
            name='ONT image infrastructure',
            description='ONT image infrastructure',
            terminate_instance_on_failure=True,
            instance_metadata_options=imagebuilder.CfnInfrastructureConfiguration.InstanceMetadataOptionsProperty(
                http_put_response_hop_limit=4,
                http_tokens='required',
            ),
            tags={
                'Patch Group': 'temporary'
            },
        )
        self.infra_cfg.node.add_dependency(self.ec2_instance_profile)

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=self.ec2_instance_role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using the AWS managed policies listed in the EC2 Image Builder documentation at '
                              'https://docs.aws.amazon.com/imagebuilder/latest/userguide/image-builder-setting-up.html.',
                    'appliesTo': [
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/AmazonSSMManagedInstanceCore',
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/EC2InstanceProfileForImageBuilderECRContainerBuilds',
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/EC2InstanceProfileForImageBuilder',
                    ],
                },
            ],
            apply_to_children=True,
        )


def get_ami_id_from_name(ami_name):
    """
    Search and select the id of one AMI which match a search string for the AMI name. Purpose
    is to find the same (or close to same) AMI when deploying the solution in different AWS
    regions. This functions helps to make the CDK deployment region independent.
    However, needs to be used with caution. AMIs in different regions might have differences
    that cause issues.

    :param ami_name: a search string to find AMIs of interest. For
                     example 'Deep Learning AMI GPU CUDA*(Ubuntu 20.04)*'. Note that wildcards
                     can be used.
    :return: ID of an AMI to be used.
    """
    images = ec2_client.describe_images(
        Owners=['amazon'],
        Filters=[
            {
                'Name': 'name',
                'Values': [ami_name]
            },
        ],
    )
    data = [
        [image['CreationDate'], image['ImageId'], image['Name'], image['Description']] for image in images['Images']
    ]
    columns = ['CreationDate', 'ImageId', 'Name', 'Description']
    df = pd.DataFrame(data, columns=columns)
    pass
