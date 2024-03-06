#!/usr/bin/env python
# -*- coding: utf-8 -*-

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ssm as ssm,
    custom_resources as cr,
    aws_iam as iam,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class Network(cdk.NestedStack):

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        self.vpc = ec2.Vpc(
            self, 'VPC',
            max_azs=99,  # use all AZs, default is 3
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC),
            ]
        )
        self.subnets = self.vpc.select_subnets()

        self.vpc.add_flow_log(
            'FlowLogCloudWatch',
            traffic_type=ec2.FlowLogTrafficType.REJECT,
            max_aggregation_interval=ec2.FlowLogMaxAggregationInterval.TEN_MINUTES
        )

        ssm.StringParameter(
            self, 'SSM parameter VPC ID',
            parameter_name='/ONT-performance-benchmark/vpc-id',
            string_value=self.vpc.vpc_id
        )
