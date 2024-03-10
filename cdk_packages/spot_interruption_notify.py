#!/usr/bin/env python
# -*- coding: utf-8 -*-


import os.path
import re
import json

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


class SpotInterruptionNotify(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # ---------- Lambda function --------------------

        # Lamda function to start image build.
        lambda_fn = lambda_.Function(
            self, 'Spot interruption notify',
            description='Function to capture EC2 Spot Instance interruption notifications.',
            code=lambda_.Code.from_asset(os.path.join(dirname, 'assets', 'lambda_functions', 'spot_interruption_notify')),
            handler='spot_interruption_notify.lambda_handler',
            timeout=cdk.Duration.minutes(5),
            runtime=lambda_.Runtime.PYTHON_3_12,
            log_retention=logs.RetentionDays.THREE_MONTHS,
        )

        # Permissions to create CloudWatch Log entries
        lambda_fn.role.add_to_policy(
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

        # ---------- EventBridge rules --------------------

        events_rule = events.Rule(
            self, 'Spot instance interruption notice event',
            description='Spot instance interruption notice event',
            event_pattern=events.EventPattern(
                source=['aws.ec2'],
                detail_type=['EC2 Spot Instance Interruption Warning'],
            )
        )
        events_rule.add_target(targets.LambdaFunction(lambda_fn))

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=lambda_fn.role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Resource ARNs reasonably narrowed down.',
                    'appliesTo': [
                        f'Resource::arn:aws:logs:{region}:{account}:*',
                    ]
                }
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions_by_path(
            cdk.Stack.of(self),
            path=f'/{lambda_fn.node.path}/ServiceRole/Resource',
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
