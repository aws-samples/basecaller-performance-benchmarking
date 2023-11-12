#!/usr/bin/env python
# -*- coding: utf-8 -*-


import os.path
import re

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class ImageBuildStarter(cdk.NestedStack):

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # ---------- Lambda function start image builds --------------------

        lambda_role = iam.Role(
            self, 'Lambda role',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            description='Role for Lambda function to start image builds.'
        )

        # Lamda function to start image build.
        self.start_image_build = lambda_.Function(
            self, 'Start image builds in EC2 Image Builder',
            description='Start image builds in EC2 Image Builder',
            role=lambda_role,
            code=lambda_.Code.from_asset(os.path.join(dirname, 'assets', 'lambda_functions', 'start_image_build')),
            handler='start_image_build.lambda_handler',
            timeout=cdk.Duration.minutes(5),
            runtime=lambda_.Runtime.PYTHON_3_9,
            log_retention=logs.RetentionDays.THREE_MONTHS,
        )

        # Permissions to create CloudWatch Log entries
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'logs:CreateLogGroup',
                    'logs:CreateLogStream',
                    'logs:PutLogEvents',
                ],
                resources=[
                    f'arn:aws:logs:{region}:{account}:*'
                ]
            )
        )

        # Give Lambda the permission to start image pipelines.
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'cloudformation:DescribeStacks',
                ],
                resources=[
                    f'arn:aws:cloudformation:{region}:{account}:stack/PerfBench-*']
            )
        )
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'imagebuilder:StartImagePipelineExecution',
                ],
                resources=[
                    f'arn:aws:imagebuilder:{region}:{account}:image-pipeline/ont-base-ami-pipeline',
                    f'arn:aws:imagebuilder:{region}:{account}:image-pipeline/ont-basecaller-container-pipeline',
                ]
            )
        )
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'imagebuilder:ListImages',
                    'imagebuilder:ListImageBuildVersions',
                    'imagebuilder:DeleteImage',
                ],
                resources=[
                    f'arn:aws:imagebuilder:{region}:{account}:image/*'
                ],
            )
        )

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs reasonably narrowed down.',
                    'appliesTo': [
                        f'Resource::arn:aws:logs:{region}:{account}:*',
                        f'Resource::arn:aws:cloudformation:{region}:{account}:stack/PerfBench-*',
                        f'Resource::arn:aws:imagebuilder:{region}:{account}:image/*',
                    ]
                }
            ],
            True,
        )

        log_retention_id = [
            obj.node.id for obj in self.node.find_all()
            if re.match('LogRetention[a-z0-9]+$', obj.node.id)][0]

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f'/{self.nested_stack_parent.stack_name}/{construct_id}'
                 f'/{log_retention_id}/ServiceRole/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'Log retention handler lambda uses the AWSLambdaBasicExecutionRole AWS Managed Policy '
                              'to ensure the Function has the proper permissions to execute and create logs.',
                    'appliesTo': [
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
                    ],
                },
            ],
        )
        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f'/{self.nested_stack_parent.stack_name}/{construct_id}'
                 f'/{log_retention_id}/ServiceRole/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Log retention handler lambda uses AWS managed policy with wildcards.',
                    'appliesTo': ['Resource::*'],
                },
            ],
        )
