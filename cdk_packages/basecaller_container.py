#!/usr/bin/env python
# -*- coding: utf-8 -*-


import datetime
import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_events as events,
    aws_events_targets as targets,
    aws_imagebuilder as imagebuilder,
    aws_ecr as ecr,
)
from aws_cdk.aws_s3_assets import Asset
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class BasecallerContainer(Construct):

    def __init__(self, scope: Construct, construct_id: str, params=None):
        super().__init__(scope, construct_id)

        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        repository = ecr.Repository(
            self, 'ONT basecaller repository',
            repository_name='basecaller',
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_images=True,
        )

        aws_cli = imagebuilder.CfnComponent(
            self, 'AWS CLI for container',
            name='AWS CLI for container',
            description='AWS CLI for container',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_aws_cli.yaml')).read(),
        )

        basecaller = imagebuilder.CfnComponent(
            self, 'ONT basecaller',
            name='ONT basecaller',
            description='ONT basecaller',
            platform='Linux',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            data=open(os.path.join(dirname, 'assets', 'component_basecaller.yaml')).read(),
        )

        basecaller_script = Asset(
            self, 'basecaller run script',
            path=os.path.join(dirname, 'assets', 'basecaller.sh')
        )
        basecaller_script.grant_read(params.image_builder.ec2_instance_role)

        self.recipe_container = imagebuilder.CfnContainerRecipe(
            self, 'ONT basecaller container',
            name='ONT basecaller container',
            description='ONT basecaller container',
            container_type='DOCKER',
            platform_override='Linux',
            parent_image=f'{account}.dkr.ecr.{region}.amazonaws.com/nvidia/cuda:12.3.0-runtime-ubuntu20.04',
            version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
            dockerfile_template_data=open(os.path.join(dirname, 'assets', 'dockerfile_basecaller.yaml')).read(),
            instance_configuration=imagebuilder.CfnContainerRecipe.InstanceConfigurationProperty(
                image='ami-05f5eb8122c493ef0',  # TODO: update
                block_device_mappings=[imagebuilder.CfnContainerRecipe.InstanceBlockDeviceMappingProperty(
                    device_name="/dev/sda1",
                    ebs=imagebuilder.CfnContainerRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                        delete_on_termination=True,
                        volume_size=70,
                        volume_type="gp3"
                    ),
                )],
            ),
            components=[
                imagebuilder.CfnContainerRecipe.ComponentConfigurationProperty(
                    component_arn=aws_cli.attr_arn,
                ),
                imagebuilder.CfnContainerRecipe.ComponentConfigurationProperty(
                    component_arn=basecaller.attr_arn,
                    parameters=[imagebuilder.CfnContainerRecipe.ComponentParameterProperty(
                        name='S3PathBasecallerRunScript',
                        value=[basecaller_script.s3_object_url]
                    )]
                ),
            ],
            target_repository=imagebuilder.CfnContainerRecipe.TargetContainerRepositoryProperty(
                repository_name=repository.repository_name,
                service='ECR'
            ),
        )

        # ---------- distributions --------------------

        self.container_dist_cfg = imagebuilder.CfnDistributionConfiguration(
            self, 'ONT container distribution',
            name='ONT container distribution',
            description='ONT container distribution',
            distributions=[imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                region=region,
                container_distribution_configuration={
                    'Description': 'ONT basecaller',
                    'ContainerTags': ['latest'],
                    'TargetRepository': {
                        'RepositoryName': repository.repository_name,
                        'Service': 'ECR'
                    }
                },
            )],
        )

        # ---------- pipeline --------------------

        self.container_pipeline = imagebuilder.CfnImagePipeline(
            self, 'ONT basecaller container pipeline',
            name='ONT basecaller container pipeline',
            description='ONT basecaller container pipeline',
            infrastructure_configuration_arn=params.image_builder.infra_cfg.attr_arn,
            distribution_configuration_arn=self.container_dist_cfg.attr_arn,
            container_recipe_arn=self.recipe_container.attr_arn,
            status='ENABLED',
        )
