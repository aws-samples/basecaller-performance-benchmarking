#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_ssm as ssm,
    aws_dynamodb as dynamodb,
)
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class Report(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        # Set up the table to collect measurement results.
        table = dynamodb.Table(
            self, "Table",
            partition_key=dynamodb.Attribute(name="job_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            table_class=dynamodb.TableClass.STANDARD_INFREQUENT_ACCESS,
        )
        table.grant_read_write_data(params.batch_compute_env.ec2_instance_role)

        # Store table ID in Parameter Store.
        ssm_parameter = ssm.StringParameter(
            self, 'SSM parameter reports table',
            parameter_name='/ONT-performance-benchmark/reports-table-name',
            string_value=table.table_name,
        )
        ssm_parameter.grant_read(params.batch_compute_env.ec2_instance_role)

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=table,
            suppressions=[
                {
                    'id': 'AwsSolutions-DDB3',
                    'reason': 'No Point-in-time Recovery enabled for DynamoDB table as the data can be recreated by '
                              're-running tests. Data is also copied into reports immediately after test run. Table '
                              'only needed as temporary storage.',
                },
            ],
            apply_to_children=True,
        )
