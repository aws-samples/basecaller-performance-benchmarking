#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class Data(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        # S3 bucket to hold the FAST5 files downloaded from Oxford Nanopore Technologies (ONT)
        self.bucket = s3.Bucket(
            self, "Data S3 bucket",
            server_access_logs_prefix='access_logs/',
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            auto_delete_objects=False
        )

        self.ssm_parameter_data_s3_bucket = ssm.StringParameter(
            self, 'SSM parameter data S3 bucket',
            parameter_name='/ONT-performance-benchmark/data-s3-bucket',
            string_value=self.bucket.bucket_name
        )
