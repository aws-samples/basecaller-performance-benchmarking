#!/usr/bin/env python3

import aws_cdk as cdk
import boto3
import cdk_nag
from aws_cdk import Aspects

from cdk_packages.perfbench import PerfBench
from cdk_packages.downloader import Downloader


class Params:
    """
    A class to hold all parameters exchanged across stacks in one place.
    """


"""
Set the environment explicitly. This is necessary to get subnets in all availability zones.
See also: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.Stack.html#availabilityzones
"If the stack is environment-agnostic (either account and/or region are tokens), this property 
will return an array with 2 tokens that will resolve at deploy-time to the first two availability
zones returned from CloudFormation's Fn::GetAZs intrinsic function."
"""
environment = cdk.Environment(
    account=boto3.client('sts').get_caller_identity().get('Account'),
    region=boto3.session.Session().region_name)
environment_eu_west_1 = cdk.Environment(
    account=boto3.client('sts').get_caller_identity().get('Account'),
    region='eu_west_1')

# ensure we are in the right region
if environment.region != 'us-west-2':
    raise ValueError(
        f'This CDK application needs to be deployed in the AWS region us-west-2. '
        f'You are attempting a deployment into region {environment.region}.'
    )

# ensure the ECR repository for the NVIDIA CUDA container exist
ecr_client = boto3.client('ecr')
ecr_repositories = ecr_client.describe_repositories()['repositories']
ecr_repository_names = [repository['repositoryName'] for repository in ecr_repositories]
if 'nvidia/cuda' not in ecr_repository_names:
    raise ValueError(
        'The ECR repository "nvidia/cuda" does not exist. '
        'This repository needs to be created manually. Please ensure you follow the instructions in the README.md.'
    )

# ensure the NVIDIA CUDA image exists in ECR repository
ecr_images = ecr_client.describe_images(repositoryName='nvidia/cuda')
if len(ecr_images['imageDetails']) < 1:
    raise ValueError(
        'The ECR repository "nvidia/cuda" does not contain any container images. '
        'The NVIDIA CUDA image needs to be pushed manually. Please ensure you follow the instructions in the README.md.'
    )

params = Params()
app = cdk.App()

# cdk-nag: Check for compliance with CDK best practices
#   https://github.com/cdklabs/cdk-nag
# Uncomment the following line to run the cdk-nag checks
Aspects.of(app).add(cdk_nag.AwsSolutionsChecks(verbose=True))

params.perfbench = PerfBench(
    app, 'ONT-PerfBench',
    description='ONT performance benchmark environment',
    env=environment
)
params.downloader = Downloader(
    app, 'PerfBench-Downloader', params=params.perfbench.params,
    description='EC2 instance for automated download of performance test data set.',
    env=environment
)

app = app.synth()
