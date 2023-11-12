#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

import aws_cdk as cdk
import boto3
from aws_cdk import aws_batch as batch
from constructs import Construct

dirname = os.path.dirname(__file__)
ec2_client = boto3.client('ec2')


class BatchJobQueues(cdk.NestedStack):
    """
    Create AWS Batch job queues.
    """

    def __init__(self, scope: Construct, construct_id: str, params=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        previous = None

        for compute_environment in params.batch_compute_env.compute_environments:
            # Create job queue
            job_queue_name = f'{compute_environment.compute_environment_name}'
            job_queue = batch.CfnJobQueue(
                self, job_queue_name,
                compute_environment_order=[batch.CfnJobQueue.ComputeEnvironmentOrderProperty(
                    compute_environment=compute_environment.compute_environment_name,
                    order=1
                )],
                priority=1,
                job_queue_name=job_queue_name,
            )
            job_queue.node.add_dependency(compute_environment)  # dependency required

            # deploy job queues in sequence to avoid error message
            #   "Too Many Requests (Service: Batch, Status Code: 429 ..."
            if previous:
                job_queue.node.add_dependency(previous)
                previous = job_queue
