#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os.path
import tempfile

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_batch as batch,
    aws_ssm as ssm,
)
from aws_cdk.aws_s3_assets import Asset
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class BatchComputeEnv(cdk.NestedStack):
    """
    Create AWS Batch compute environment.
    """

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # EC2 instance role for AWS Batch container instances.
        self.ec2_instance_role = iam.Role(
            self, "AWS Batch EC2 container instance role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Role for EC2 instance created by AWS Batch",
        )
        ec2_instance_profile = iam.CfnInstanceProfile(
            self, "AWS Batch EC2 container instance profile",
            roles=[self.ec2_instance_role.role_name],
        )

        # Add standard management policies.
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'))
        self.ec2_instance_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AmazonEC2ContainerServiceforEC2Role'))

        # Allow the batch job to retrieve batch job descriptions and batch container instance
        # descriptions. This is used by a script within the job container to get information
        # about the environment on which a batch job is running.
        self.ec2_instance_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'batch:DescribeJobs',
                    'ecs:DescribeContainerInstances',
                    'ec2:DescribeInstances',
                ],
                resources=['*'],
            )
        )

        # Allow access to S3 bucket with test data.
        params.data.bucket.grant_read_write(self.ec2_instance_role)

        # Allow to publish metrics to CloudWatch. Required to log CPU, GPU and memory metrics
        self.ec2_instance_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=['cloudwatch:PutMetricData'],
                resources=[f'arn:aws:cloudwatch:{region}:{account}:*'],
            )
        )

        # Allow outbound communication
        sg_outbound = ec2.SecurityGroup(
            self, 'SG outbound communication',
            vpc=params.network.vpc,
            description='SG outbound communication',
            allow_all_outbound=True
        )

        # Security groups for FSx for Lustre. Rules are based on
        # https://docs.aws.amazon.com/fsx/latest/LustreGuide/limit-access-security-groups.html
        sg_fsx_lustre_clients = ec2.SecurityGroup(
            self, 'SG FSx for Lustre clients',
            vpc=params.network.vpc,
            description='FSx for Lustre clients',
            allow_all_outbound=False
        )
        # Inbound rules for FSx for Lustre clients.
        sg_fsx_lustre_clients.add_ingress_rule(
            ec2.Peer.ipv4(params.network.vpc.vpc_cidr_block),
            ec2.Port.tcp_range(988, 1023), 'Allows Lustre traffic'
        )
        # Outbound rules for FSx for Lustre clients.
        sg_fsx_lustre_clients.add_egress_rule(
            ec2.Peer.ipv4(params.network.vpc.vpc_cidr_block),
            ec2.Port.tcp_range(988, 1023), 'Allows Lustre traffic'
        )

        # Create one compute environment for each instance type that supports x86_64 architecture
        # and has an NVIDIA GPU.
        self.compute_environments = []
        self.instance_types = get_instance_types()
        for instance_type in self.instance_types.keys():
            compute_environment = batch.CfnComputeEnvironment(
                self, instance_type.replace('.', '-'),
                type='MANAGED',
                state='ENABLED',
                compute_environment_name=instance_type.replace('.', '-'),
                compute_resources=batch.CfnComputeEnvironment.ComputeResourcesProperty(
                    type='EC2',
                    instance_types=[instance_type],
                    allocation_strategy='BEST_FIT_PROGRESSIVE',
                    minv_cpus=0,
                    maxv_cpus=4000,
                    subnets=params.network.subnets.subnet_ids,
                    security_group_ids=[
                        sg_outbound.security_group_id,
                        sg_fsx_lustre_clients.security_group_id,
                    ],
                    instance_role=ec2_instance_profile.attr_arn,
                    launch_template=batch.CfnComputeEnvironment.LaunchTemplateSpecificationProperty(
                        launch_template_id=params.base_ami.launch_template.launch_template_id,
                        version='$Default'
                    ),
                )
            )
            self.compute_environments.append(compute_environment)

        # Publish the list of compute environment names in Parameter Store. Other
        # tools can get the list of compute environments dedicated for the performance
        # benchmarks (e.g. scripts to automate batch jobs creation) from Parameter Store.
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as temp:
            json.dump(self.instance_types, temp)
            temp.flush()  # force the data to be written to the temp file
            file_asset = Asset(
                self, 'compute environments instance types',
                path=temp.name
            )
        file_asset.grant_read(params.compute_env_update.update_compute_environments)
        ssm.StringParameter(
            self, 'SSM parameter AWS Batch compute environments',
            parameter_name='/ONT-performance-benchmark/aws-batch-compute-environments',
            string_value=file_asset.s3_object_url,
        ).grant_read(params.compute_env_update.update_compute_environments)
        ssm.StringParameter(
            self, 'AWS Batch launch template',
            parameter_name='/ONT-performance-benchmark/aws-batch-launch-template',
            string_value=params.base_ami.launch_template.launch_template_id
        ).grant_read(params.compute_env_update.update_compute_environments)

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=self.ec2_instance_role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using recommended AWS managed policies for AWS Systems Manager: '
                              'https://aws.amazon.com/blogs/mt/applying-managed-instance-policy-best-practices/ and '
                              'AWS managed role for ECS containers: '
                              'https://docs.aws.amazon.com/batch/latest/userguide/instance_IAM_role.html',
                    'appliesTo': [
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/AmazonSSMManagedInstanceCore',
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role',
                    ],
                },
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs narrowed down to the minimum. Wildcards required.',
                    'appliesTo': [
                        f'Resource::arn:aws:batch:{region}:{account}:job/*',
                        f'Resource::arn:aws:ecs:{region}:{account}:container-instance/*',
                        f'Resource::arn:aws:cloudwatch:{region}:{account}:*',
                    ]
                },
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'The following actions do not support resource-level permissions and require to specify '
                              'all resources ("*") in the Resource element of the policy statement:'
                              '    ec2:DescribeInstances'
                              '    batch:DescribeJobs'
                              '    ecs:DescribeContainerInstances'
                              'See also:'
                              '    https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonec2.html'
                              '    https://docs.aws.amazon.com/batch/latest/userguide/batch-supported-iam-actions-resources.html'
                              '    https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security_iam_service-with-iam.html#ecs-supported-iam-actions-resources',
                    'appliesTo': ['Resource::*'],
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
                    ]
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            construct=sg_fsx_lustre_clients,
            suppressions=[
                {
                    'id': 'CdkNagValidationFailure',
                    'reason': 'Outbound and inbound address ranges are limited to IP range of AWS Batch '
                              'compute instances.\n\n'
                              'Supressing warning that is caused by a parameter referencing an intrinsic function. '
                              'Rule AwsSolutions-EC23 could not be validated as the parameter resolved to to a '
                              'non-primitive value. This is expected behaviour of cdk-nag.'
                },
            ],
            apply_to_children=True,
        )


def get_instance_types():
    """
    Get instance types with filter.
    """

    instance_types = {}
    describe_args = {}
    while True:
        results = ec2_client.describe_instance_types(**describe_args)
        for result in filter_results(results):
            instance_types[result['InstanceType']] = {
                'ProcessorInfo': result['ProcessorInfo'],
                'VCpuInfo': result['VCpuInfo'],
                'MemoryInfo': result['MemoryInfo'],
                'GpuInfo': result['GpuInfo'],
            }
        if 'NextToken' not in results:
            break
        describe_args['NextToken'] = results['NextToken']

        # Remove p5.48xlarge instance type. As of 2023-07-28 this instance type cannot yet be used as AWS Batch
        # compute environment instance type.
        if 'p5.48xlarge' in instance_types:
            instance_types.pop('p5.48xlarge')

    return instance_types


def filter_results(results):
    """
    Filter for x86_64 architecture and NVIDIA GPUs.
    """
    gpu_instances = [
        instance_type
        for instance_type in results['InstanceTypes']
        if 'GpuInfo' in instance_type
    ]
    NVIDIA_gpu_instances = [
        instance_type
        for instance_type in gpu_instances
        for gpu in instance_type['GpuInfo']['Gpus']
        if gpu['Manufacturer'] == 'NVIDIA'
    ]
    x86_64_NVIDIA_gpu_instances = [
        {
            'InstanceType': instance_type['InstanceType'],
            'ProcessorInfo': instance_type['ProcessorInfo'],
            'VCpuInfo': instance_type['VCpuInfo'],
            'MemoryInfo': instance_type['MemoryInfo'],
            'GpuInfo': instance_type['GpuInfo'],
        }
        for instance_type in NVIDIA_gpu_instances
        if 'x86_64' in instance_type['ProcessorInfo']['SupportedArchitectures']
    ]
    return x86_64_NVIDIA_gpu_instances
