#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_ssm as ssm,
)
from aws_cdk.aws_s3_assets import Asset
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)


class Downloader(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # EC2 instance role
        self.ec2_instance_role = iam.Role(
            self, 'EC2 instance role',
            assumed_by=iam.ServicePrincipal('ec2.amazonaws.com'),
            description='Role for EC2 instance',
            role_name='downloader-ec2-instance-role',
        )

        # add standard management policy
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'))

        # add policy to run the CloudWatch agent on EC2 instances
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('CloudWatchAgentServerPolicy'))

        # grant the CloudWatch agent permission to set log retention policies
        self.ec2_instance_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=['logs:PutRetentionPolicy'],
                resources=[f'arn:aws:logs:{region}:{account}:log-group:/aws/PerfBench/downloader:log-stream:'],
            )
        )

        # store CloudWatch agent configuration in SSM Parameter Store
        ssm.StringParameter(
            self, 'SSM parameter CloudWatch agent configuration for downloader',
            parameter_name='/ONT-performance-benchmark/downloader-cloudwatch-agent-config',
            string_value=open(os.path.join(dirname, 'assets', 'cloudwatch_agent_config_downloader.json')).read(),
        ).grant_read(self.ec2_instance_role)

        # add permission to delete own CloudFormation stack
        self.ec2_instance_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=['cloudformation:DeleteStack'],
                resources=[cdk.Stack.of(self).stack_id],
            )
        )

        # store Python script for creating the test data sets in S3 bucket
        create_test_data_sets_script = Asset(
            self, 'create test data Python script',
            path=os.path.join(dirname, 'assets', 'create_test_data_sets.py')
        )
        create_test_data_sets_script.grant_read(self.ec2_instance_role)
        ssm.StringParameter(
            self, 'SSM parameter POD5 create test data script',
            parameter_name='/ONT-performance-benchmark/pod5-create-test-data-script',
            string_value=create_test_data_sets_script.s3_object_url
        ).grant_read(self.ec2_instance_role)

        # Instance that downloads the FAST5 files from ONT and converts them to POD5 format
        self.downloader_instance = ec2.Instance(
            self, 'downloader',
            instance_type=ec2.InstanceType('c6g.4xlarge'),  # Arm-based AWS Graviton2 processors
            machine_image=ec2.MachineImage.generic_linux({
                'us-west-2': 'ami-03f6bd8c9c6230968'  # Canonical, Ubuntu, 22.04 LTS, arm64 jammy image
                # build on 2023-03-03
            }),
            vpc=params.network.vpc,
            require_imdsv2=True,
            role=self.ec2_instance_role,
        )
        # FSX filesystem needs to be ready in order to run the POD5 conversion.
        self.downloader_instance.node.add_dependency(params.fsx_lustre.cfn_fsx_file_system)
        params.data.bucket.grant_read_write(self.ec2_instance_role)

        # Instance startup script (UserData)
        self.downloader_instance.user_data.add_commands(
            open(os.path.join(os.path.dirname(__file__), 'assets', 'download_files.sh')).read()
        )

        params.data.ssm_parameter_data_s3_bucket.grant_read(self.ec2_instance_role)

        params.status_parameters.download_status.grant_write(self.ec2_instance_role)
        params.status_parameters.pod5_converter_status.grant_write(self.ec2_instance_role)
        ssm.StringParameter(
            self, 'SSM parameter downloader stack name',
            parameter_name='/ONT-performance-benchmark/downloader-stack-name',
            string_value=cdk.Stack.of(self).stack_name
        ).grant_write(self.ec2_instance_role)

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=self.ec2_instance_role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using recommended AWS managed policies for AWS Systems Manager: '
                              'https://aws.amazon.com/blogs/mt/applying-managed-instance-policy-best-practices/.',
                    'appliesTo': ['Policy::arn:<AWS::Partition>:iam::aws:policy/AmazonSSMManagedInstanceCore'],
                },
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using recommended AWS managed policies for CloudWatch agent: '
                              'https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/create-iam-roles-for-cloudwatch-agent.html.',
                    'appliesTo': ['Policy::arn:<AWS::Partition>:iam::aws:policy/CloudWatchAgentServerPolicy'],
                },
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Default read and write permissions generated by using CDK function grant_read_write().',
                    'appliesTo': [
                        f'Action::s3:Abort*',
                        f'Action::s3:DeleteObject*',
                        f'Action::s3:GetBucket*',
                        f'Action::s3:GetObject*',
                        f'Action::s3:List*',
                        f'Resource::<{self.get_logical_id(params.data.bucket.node.default_child)}.Arn>/*',
                        f'Resource::arn:aws:s3:::{create_test_data_sets_script.bucket.bucket_name}/*',
                    ]
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            construct=self.downloader_instance,
            suppressions=[
                {
                    'id': 'AwsSolutions-EC28',
                    'reason': 'Detailed monitoring for EC2 instance/AutoScaling not required. This is an ephemeral'
                              'EC2 instance only used for automating the the download of the test data set.',
                },
                {
                    'id': 'AwsSolutions-EC29',
                    'reason': 'ASG and has Termination Protection are not required. This is an ephemeral'
                              'EC2 instance only used for automating the the download of the test data set.',
                },
            ],
            apply_to_children=True,
        )
