#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_imagebuilder as imagebuilder,
)
from aws_cdk.aws_s3_assets import Asset
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class BaseAMI(cdk.NestedStack):

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        ecs_agent = imagebuilder.CfnComponent(
            self, 'ECS container agent',
            name='ECS container agent',
            description='ECS container agent',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_ecs_container_agent.yaml')).read(),
        )

        cw_agent = imagebuilder.CfnComponent(
            self, 'CloudWatch agent',
            name='CloudWatch agent',
            description='CloudWatch agent',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_cloudwatch_agent_config.yaml')).read(),
        )

        fsx_lustre_client = imagebuilder.CfnComponent(
            self, 'FSx for Lustre client',
            name='FSx for Lustre client',
            description='FSx for Lustre client',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_fsx_for_lustre_client.yaml')).read(),
        )

        aws_cli = imagebuilder.CfnComponent(
            self, 'AWS CLI for AMI',
            name='AWS CLI for AMI',
            description='AWS CLI for AMI',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_aws_cli.yaml')).read(),
        )

        mount_fsx_script = Asset(
            self, 'mount fsx script',
            path=os.path.join(dirname, 'assets', 'mount_fsx.sh')
        )
        mount_fsx_script.grant_read(params.image_builder.ec2_instance_role)

        self.recipe_ont_base_image = imagebuilder.CfnImageRecipe(
            self, 'ONT base AMI',
            name='ONT base AMI',
            description='ONT base AMI',
            parent_image='ami-06b81ce928c07a34f',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            components=[
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=aws_cli.attr_arn,
                ),
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=ecs_agent.attr_arn,
                ),
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=cw_agent.attr_arn,
                ),
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=fsx_lustre_client.attr_arn,
                    parameters=[imagebuilder.CfnImageRecipe.ComponentParameterProperty(
                        name='MountFSxScript',
                        value=[mount_fsx_script.s3_object_url]
                    )]
                ),
            ],
            additional_instance_configuration=imagebuilder.CfnImageRecipe.AdditionalInstanceConfigurationProperty(
                systems_manager_agent=imagebuilder.CfnImageRecipe.SystemsManagerAgentProperty(
                    uninstall_after_build=False
                ),
            ),
            block_device_mappings=[imagebuilder.CfnImageRecipe.InstanceBlockDeviceMappingProperty(
                device_name="/dev/sda1",
                ebs=imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                    delete_on_termination=True,
                    volume_size=70,
                    volume_type="gp3"
                ),
            )],
        )

        # ---------- launch template --------------------

        # Define launch template for AWS Batch compute environment. We use a launch template as
        # this can be updated via EC2 Image Builder.
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            open(os.path.join(dirname, 'assets', 'launch_template_user_data.sh')).read()
        )
        self.launch_template = ec2.LaunchTemplate(
            self, "AWS Batch launch template",
            user_data=user_data,
        )

        # ---------- distribution --------------------

        self.ami_dist_cfg = imagebuilder.CfnDistributionConfiguration(
            self, 'ONT base AMI distribution',
            name='ONT base AMI distribution',
            description='ONT base AMI distribution',
            distributions=[imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                region=region,
                ami_distribution_configuration={
                    'Description': 'ONT Performance Benchmark AMI',
                    'AmiTags': {'type': 'ONT Performance Benchmark AMI'},
                },
                launch_template_configurations=[
                    imagebuilder.CfnDistributionConfiguration.LaunchTemplateConfigurationProperty(
                        account_id=account,
                        launch_template_id=self.launch_template.launch_template_id,
                        set_default_version=True,
                    )],
            )],
        )

        # ---------- pipeline --------------------

        ami_pipeline = imagebuilder.CfnImagePipeline(
            self, 'ONT base AMI pipeline',
            name='ONT base AMI pipeline',
            description='ONT base AMI pipeline',
            infrastructure_configuration_arn=params.image_builder.infra_cfg.attr_arn,
            distribution_configuration_arn=self.ami_dist_cfg.attr_arn,
            image_recipe_arn=self.recipe_ont_base_image.attr_arn,
            status='ENABLED',
        )
        cdk.CfnOutput(self, "EC2ImageBuilderPipelineARN", value=ami_pipeline.attr_arn)

        # ---------- EventBridge rules --------------------

        start_image_builds_rule = events.Rule(
            self, 'Trigger Lambda to start AMI build',
            description='When CloudFormation stack for base AMI has been created or updated, '
                        'trigger Lambda to start AMI build',
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
        start_image_builds_rule.add_target(targets.LambdaFunction(params.image_build_starter.start_image_build))

        # ----------------------------------------------------------------
        #       cdk_nag suppressions
        # ----------------------------------------------------------------

        NagSuppressions.add_resource_suppressions(
            construct=params.image_builder.ec2_instance_role,
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'We use the CDK provided functions [.grant_read()] to grant access to the CDK assets '
                              'bucket. See also https://docs.aws.amazon.com/cdk/v2/guide/permissions.html, '
                              'section "Grants".',
                    'appliesTo': [
                        'Action::s3:GetBucket*',
                        'Action::s3:GetObject*',
                        'Action::s3:List*',
                        f'Resource::arn:aws:s3:::{mount_fsx_script.s3_bucket_name}/*',
                    ],
                },
            ],
            apply_to_children=True,
        )
