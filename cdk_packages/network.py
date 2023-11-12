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

        # Configure default security group according to "CIS AWS Foundations Benchmark controls",
        # section "4.3 – Ensure the default security group of every VPC restricts all traffic".
        # See https://docs.aws.amazon.com/securityhub/latest/userguide/securityhub-cis-controls.html#securityhub-cis-controls-4.3

        cfn_vpc: ec2.CfnVPC = self.vpc.node.default_child

        ingress_parameters = {
            'GroupId': cfn_vpc.attr_default_security_group,
            'IpPermissions': [
                {
                    'IpProtocol': '-1',
                    'UserIdGroupPairs': [
                        {
                            'GroupId': cfn_vpc.attr_default_security_group,
                        },
                    ],
                },
            ],
        }

        cr.AwsCustomResource(
            self, 'RestrictSecurityGroupIngress',
            function_name='RestrictSecurityGroupIngress',
            on_create=cr.AwsSdkCall(
                service='EC2',
                action='revokeSecurityGroupIngress',
                parameters=ingress_parameters,
                physical_resource_id=cr.PhysicalResourceId.of(
                    f'restrict-ingress-${self.vpc.vpc_id}-{cfn_vpc.attr_default_security_group}'
                )
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements(statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=['ec2:revokeSecurityGroupIngress'],
                    resources=[
                        f'arn:aws:ec2:{region}:{account}:security-group/{cfn_vpc.attr_default_security_group}']
                )]),
            install_latest_aws_sdk=True,
        )

        egress_parameters = {
            'GroupId': cfn_vpc.attr_default_security_group,
            'IpPermissions': [
                {
                    'IpProtocol': '-1',
                    'IpRanges': [
                        {
                            'CidrIp': '0.0.0.0/0',
                        },
                    ],
                },
            ],
        }

        cr.AwsCustomResource(
            self, 'RestrictSecurityGroupEgress',
            function_name='RestrictSecurityGroupEgress',
            on_create=cr.AwsSdkCall(
                service='EC2',
                action='revokeSecurityGroupEgress',
                parameters=egress_parameters,
                physical_resource_id=cr.PhysicalResourceId.of(
                    f'restrict-egress-${self.vpc.vpc_id}-{cfn_vpc.attr_default_security_group}'
                )
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements(statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=['ec2:revokeSecurityGroupEgress'],
                    resources=[
                        f'arn:aws:ec2:{region}:{account}:security-group/{cfn_vpc.attr_default_security_group}']
                )]),
            install_latest_aws_sdk=True,
        )

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path='/PerfBench/Network/AWS679f53fac002430cb0da5b7982bd2287/ServiceRole/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'We are using the AWS managed policies that are part of the custom resources '
                              'for AWS APIs: '
                              'https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/README.html#custom-resources-for-aws-apis.',
                    'appliesTo': [
                        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
                    ],
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path='/PerfBench/Network/AWS679f53fac002430cb0da5b7982bd2287/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-L1',
                    'reason': 'Lambda function is part of the custom resources for AWS APIs. This solution is '
                              'managed by AWS: '
                              'https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/README.html#custom-resources-for-aws-apis.',
                },
            ],
            apply_to_children=True,
        )
