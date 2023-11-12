#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path
import re

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_lambda as lambda_,
    aws_events as events,
    aws_events_targets as targets,
    aws_logs as logs,
    aws_iam as iam,
)
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class ComputeEnvUpdate(cdk.NestedStack):
    """
    Lambda function to update AWS Batch compute environments.
    """

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # ---------- Lambda function --------------------

        self.update_compute_environments = lambda_.Function(
            self, 'Update launch template for AWS Batch',
            description='Update launch template for AWS Batch',
            code=lambda_.Code.from_asset(os.path.join(
                dirname, 'assets', 'lambda_functions', 'compute_env_update')
            ),
            handler='compute_env_update.lambda_handler',
            timeout=cdk.Duration.minutes(5),
            runtime=lambda_.Runtime.PYTHON_3_9,
            log_retention=logs.RetentionDays.THREE_MONTHS,
        )

        # Give Lambda required permissions
        self.update_compute_environments.role.add_to_policy(
            iam.PolicyStatement(
                # Update the AMI in AWS Batch compute environments
                effect=iam.Effect.ALLOW,
                actions=[
                    'batch:UpdateComputeEnvironment',
                ],
                resources=[f'arn:aws:batch:{region}:{account}:compute-environment/*'],
            )
        )
        self.update_compute_environments.role.add_to_policy(
            iam.PolicyStatement(
                # Get list of AMI images
                effect=iam.Effect.ALLOW,
                actions=[
                    'ec2:DescribeImages',
                    'ec2:DescribeLaunchTemplateVersions'
                ],
                resources=['*'],
            )
        )

        # ---------- EventBridge rules --------------------

        # EventBridge rule that triggers when AMI image moves to state "available".
        # Lambda function will update the AWS Batch compute environments to
        # trigger an update of the AWS Batch compute environments. See also
        # https://docs.aws.amazon.com/batch/latest/userguide/updating-compute-environments.html.
        events.Rule(
            self, 'Update compute environments when new launch template version created',
            event_pattern=events.EventPattern(
                source=['aws.ec2'],
                detail={
                    'eventSource': ['ec2.amazonaws.com'],
                    'eventName': ['CreateLaunchTemplateVersion'],
                    'requestParameters': {
                        'CreateLaunchTemplateVersionRequest': {
                            'LaunchTemplateId': [params.base_ami.launch_template.launch_template_id]
                        }
                    }
                }
            )
        ).add_target(targets.LambdaFunction(self.update_compute_environments))

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f'/{self.nested_stack_parent.stack_name}/{construct_id}'
                 f'/{self.update_compute_environments.node.default_child.description}/ServiceRole/Resource',
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

        NagSuppressions.add_resource_suppressions(
            construct=self.update_compute_environments.role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs narrowed down to the minimum. Wildcards required.',
                    'appliesTo': [
                        f'Resource::arn:aws:batch:{region}:{account}:compute-environment/*',
                        f'Resource::arn:aws:batch:{region}:{account}:*',
                        'Action::s3:GetBucket*',
                        'Action::s3:GetObject*',
                        'Action::s3:List*',
                        f'Resource::arn:aws:s3:::{self.update_compute_environments.node.default_child.code.s3_bucket}/*',
                    ],
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            construct=self.update_compute_environments.role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Action ec2:DescribeLaunchTemplateVersions cannot be narrowed down to resource. '
                              'Wildcard required.',
                    'appliesTo': [
                        'Resource::*',
                    ],
                },
            ],
            apply_to_children=True,
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
                    'reason': 'Log retention handler lambda uses the AWSLambdaBasicExecutionRole AWS Managed Policy.',
                    'appliesTo': ['Resource::*'],
                },

            ],
        )

