#!/usr/bin/env python
# -*- coding: utf-8 -*-

import aws_cdk as cdk
from constructs import Construct

from .base_ami import BaseAMI
from .basecaller_container import BasecallerContainer
from .batch_compute_env import BatchComputeEnv
from .batch_job_queues import BatchJobQueues
from .compute_env_update import ComputeEnvUpdate
from .data import Data
from .fsx_lustre import FSxLustre
from .image_builder import ImageBuilder
from .image_builds_starter import ImageBuildStarter
from .network import Network
from .report import Report
from .status_parameters import StatusParameters


class Params:
    """
    A class to hold all parameters exchanged across CDK constructs in one place.
    """


class PerfBench(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.params = Params()

        self.params.network = Network(self, 'Network', params=self.params)
        self.params.data = Data(self, 'Data', params=self.params)
        self.params.image_builder = ImageBuilder(self, 'ImageBuilder', params=self.params)
        self.params.base_ami = BaseAMI(self, 'BaseAMI', params=self.params)
        self.params.basecaller_container = BasecallerContainer(self, 'BasecallerContainer', params=self.params)
        self.params.image_build_starter = ImageBuildStarter(self, 'ImageBuildStarter', params=self.params)
        self.params.compute_env_update = ComputeEnvUpdate(self, 'ComputeEnvUpdate', params=self.params)
        self.params.fsx_lustre = FSxLustre(self, 'FSXLustre', params=self.params)
        self.params.batch_compute_env = BatchComputeEnv(self, 'BatchComputeEnv', params=self.params)
        self.params.batch_job_queues = BatchJobQueues(self, 'BatchJobQueues', params=self.params)
        self.params.report = Report(self, 'Report', params=self.params)
        self.params.status_parameters = StatusParameters(self, 'StatusParameters', params=self.params)

        # cdk.CfnOutput(self, "ONTBaseAMIPipelineARN",
        #               value=self.params.base_ami.ami_pipeline.attr_arn)
        # cdk.CfnOutput(self, "ONTBasecallerContainerPipelineARN",
        #               value=self.params.basecaller_container.container_pipeline.attr_arn)
