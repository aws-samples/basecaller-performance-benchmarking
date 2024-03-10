#!/usr/bin/env python
# -*- coding: utf-8 -*-


import json
import os.path
import re

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_events as events,
    aws_events_targets as targets,
    aws_ssm as ssm,
)
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class ImageBuildStarter(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # ---------- Lambda function start image builds --------------------

        # Lamda function to start image build.
        self.start_image_build = lambda_.Function(
            self, 'Start image builds in EC2 Image Builder',
            description='Start image builds in EC2 Image Builder',
            code=lambda_.Code.from_asset(os.path.join(dirname, 'assets', 'lambda_functions', 'start_image_build')),
            handler='start_image_build.lambda_handler',
            timeout=cdk.Duration.minutes(5),
            runtime=lambda_.Runtime.PYTHON_3_12,
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
                    f'arn:aws:cloudformation:{region}:{account}:stack/{cdk.Stack.of(self).stack_name}*']
            )
        )
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'imagebuilder:ListImages',
                    'imagebuilder:ListImageBuildVersions',
                    'imagebuilder:DeleteImage',
                    'imagebuilder:StartImagePipelineExecution',
                ],
                resources=[
                    f'arn:aws:imagebuilder:{region}:{account}:image/*',
                ],
            )
        )
        self.start_image_build.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'imagebuilder:ListImages',
                    'imagebuilder:ListImageBuildVersions',
                    'imagebuilder:DeleteImage',
                    'imagebuilder:StartImagePipelineExecution',
                ],
                resources=params.base_ami.pipeline_arns + params.basecaller_container.pipeline_arns,
            )
        )

        # ---------- Image build pipelines --------------------

        ssm.StringParameter(
            self, 'SSM parameter image build pipelines',
            parameter_name='/ONT-performance-benchmark/image-build-pipelines',
            string_value=json.dumps({
                'pipelines': params.base_ami.pipeline_arns + params.basecaller_container.pipeline_arns
            }
            )
        ).grant_read(self.start_image_build.role)

        # ---------- EventBridge rules --------------------

        start_image_builds_rule = events.Rule(
            self, 'Trigger Lambda to start image builds',
            description='When CloudFormation stack has been created or updated, '
                        'trigger Lambda to start image builds',
            event_pattern=events.EventPattern(
                source=['aws.cloudformation'],
                detail_type=['CloudFormation Stack Status Change'],
                detail={
                    'stack-id': [cdk.Stack.of(self).stack_id],
                    'status-details': {
                        'status': ['CREATE_COMPLETE', 'UPDATE_COMPLETE']
                    }
                }
            )
        )
        start_image_builds_rule.add_target(targets.LambdaFunction(self.start_image_build))

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=self.start_image_build.role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs reasonably narrowed down.',
                    'appliesTo': [
                        f'Resource::arn:aws:logs:{region}:{account}:*',
                        f'Resource::arn:aws:cloudformation:{region}:{account}:stack/{cdk.Stack.of(self).stack_name}*',
                        f'Resource::arn:aws:imagebuilder:{region}:{account}:image/*',
                    ]
                }
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            construct=self.start_image_build.role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs reasonably narrowed down.',
                    'appliesTo': params.base_ami.pipeline_arns + params.basecaller_container.pipeline_arns
                }
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions_by_path(
            cdk.Stack.of(self),
            path=f'/{self.node.path}/{self.start_image_build.node.default_child.description}/ServiceRole/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using the standard Lambda execution role: '
                              'https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html',
                    'appliesTo': [
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
                    ],
                },
            ],
        )

        log_retention_id = [
            obj.node.id for obj in cdk.Stack.of(self).node.find_all()
            if re.match('LogRetention[a-z0-9]+$', obj.node.id)][0]
        NagSuppressions.add_resource_suppressions_by_path(
            cdk.Stack.of(self),
            path=f'/{cdk.Stack.of(self).stack_name}/{log_retention_id}/ServiceRole/Resource',
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
            cdk.Stack.of(self),
            path=f'/{cdk.Stack.of(self).stack_name}/{log_retention_id}/ServiceRole/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Log retention handler lambda uses AWS managed policy with wildcards.',
                    'appliesTo': ['Resource::*'],
                },
            ],
        )
