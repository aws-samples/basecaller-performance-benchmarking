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


class StatusParameters(Construct):
    """
    A set of SSM parameters that are used to track the status of the data download and POD5 conversion.
    """

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        self.download_status = ssm.StringParameter(
            self, 'SSM parameter data download status',
            parameter_name='/ONT-performance-benchmark/download-status',
            string_value='not started'
        )
        self.pod5_converter_status = ssm.StringParameter(
            self, 'SSM parameter POD5 conversion status',
            parameter_name='/ONT-performance-benchmark/pod5-converter-status',
            string_value='not started'
        )
