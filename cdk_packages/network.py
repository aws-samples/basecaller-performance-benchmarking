#!/usr/bin/env python
# -*- coding: utf-8 -*-

from aws_cdk import (
    aws_ec2 as ec2,
    aws_ssm as ssm,
)
from constructs import Construct


class Network(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

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
