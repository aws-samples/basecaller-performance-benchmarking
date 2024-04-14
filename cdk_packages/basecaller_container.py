#!/usr/bin/env python
# -*- coding: utf-8 -*-


import datetime
import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import (
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

        basecaller_containers = [
            {
                'id': 'guppy_latest_dorado_v0_5_3',
                'repository_name': 'basecaller_guppy_latest_dorado0.5.3',
                'dorado_url': 'https://cdn.oxfordnanoportal.com/software/analysis/dorado-0.5.3-linux-x64.tar.gz',
            },
            {
                'id': 'guppy_latest_dorado_v0_3_0',
                'repository_name': 'basecaller_guppy_latest_dorado0.3.0',
                'dorado_url': 'https://cdn.oxfordnanoportal.com/software/analysis/dorado-0.3.0-linux-x64.tar.gz',
            },
        ]

        self.pipeline_arns = []

        for basecaller_container in basecaller_containers:
            repository = ecr.Repository(
                self, f'Repository {basecaller_container["id"]}',
                repository_name=basecaller_container['repository_name'],
                removal_policy=cdk.RemovalPolicy.DESTROY,
                auto_delete_images=True,
            )

            self.recipe_container = imagebuilder.CfnContainerRecipe(
                self, f'Container {basecaller_container["id"]}',
                name=f'Container {basecaller_container["id"]}',
                description='ONT basecaller container',
                container_type='DOCKER',
                platform_override='Linux',
                parent_image=f'{account}.dkr.ecr.{region}.amazonaws.com/nvidia/cuda:12.3.0-runtime-ubuntu20.04',
                version=datetime.datetime.now().strftime('%Y.%m%d.%H%M%S'),
                dockerfile_template_data=open(os.path.join(dirname, 'assets', 'dockerfile_basecaller.yaml')).read(),
                instance_configuration=imagebuilder.CfnContainerRecipe.InstanceConfigurationProperty(
                    image='ami-0c95e55075f3c7f51',
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
                        parameters=[
                            imagebuilder.CfnContainerRecipe.ComponentParameterProperty(
                                name='S3PathBasecallerRunScript',
                                value=[basecaller_script.s3_object_url]
                            ),
                            imagebuilder.CfnContainerRecipe.ComponentParameterProperty(
                                name='DoradoURL',
                                value=[basecaller_container['dorado_url']]
                            ),
                        ]
                    ),
                ],
                target_repository=imagebuilder.CfnContainerRecipe.TargetContainerRepositoryProperty(
                    repository_name=repository.repository_name,
                    service='ECR'
                ),
            )

            self.container_dist_cfg = imagebuilder.CfnDistributionConfiguration(
                self, f'Distribution {basecaller_container["id"]}',
                name=f'Distribution {basecaller_container["id"]}',
                description='ONT container distribution',
                distributions=[imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                    region=region,
                    container_distribution_configuration={
                        'Description': f'Basecaller {basecaller_container["id"]}',
                        'ContainerTags': ['latest'],
                        'TargetRepository': {
                            'RepositoryName': repository.repository_name,
                            'Service': 'ECR'
                        }
                    },
                )],
            )

            self.container_pipeline = imagebuilder.CfnImagePipeline(
                self, f'Pipeline {basecaller_container["id"]}',
                name=f'Pipeline {basecaller_container["id"]}',
                description='ONT basecaller container pipeline',
                infrastructure_configuration_arn=params.image_builder.infra_cfg.attr_arn,
                distribution_configuration_arn=self.container_dist_cfg.attr_arn,
                container_recipe_arn=self.recipe_container.attr_arn,
                status='ENABLED',
            )

            self.pipeline_arns.append(self.container_pipeline.attr_arn)
