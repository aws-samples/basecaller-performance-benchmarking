#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Library for running the basecaller of Oxford Nanopore Technologies in an AWS Batch
environment.

"""

import json

import boto3

ssm_client = boto3.client('ssm')
s3_client = boto3.client('s3')
batch_client = boto3.client('batch')
aws_region_name = boto3.session.Session().region_name
account_id = boto3.client('sts').get_caller_identity().get('Account')

# Path to a JSON file with all instance types deployed in AWS Batch
# compute environments. This file is generated dynamically during deployment
# of the performance benchmark environment.
SSM_PARAMETER_STORE_PATH = '/ONT-performance-benchmark/aws-batch-compute-environments'

BASECALLER_DOCKER_IMAGE = f'{account_id}.dkr.ecr.{aws_region_name}.amazonaws.com/basecaller:latest'


class BasecallerBatch:

    def __init__(self):
        self.instance_types = None
        self.validated_instances = [
            'g4dn.metal', 'g4dn.xlarge', 'g4dn.2xlarge', 'g4dn.4xlarge', 'g4dn.8xlarge', 'g4dn.12xlarge',
            'g4dn.16xlarge',
            'g5.xlarge', 'g5.2xlarge', 'g5.4xlarge', 'g5.8xlarge', 'g5.12xlarge', 'g5.16xlarge', 'g5.24xlarge',
            'g5.48xlarge',
            'p3.2xlarge', 'p3.8xlarge', 'p3.16xlarge', 'p3dn.24xlarge',
            'p4d.24xlarge',
        ]
        self.job_definitions = {}
        self.get_aws_batch_compute_environments()
        self.get_existing_job_definitions()
        self.create_missing_job_definitions()

    def get_aws_batch_compute_environments(self):
        """
        Read list of AWS Batch compute environments. The list is stored as JSON file
        on S3. The list is generated during the CDK deployment of the AWS Batch environment.
        """
        param = ssm_client.get_parameter(Name=SSM_PARAMETER_STORE_PATH)
        file_obj = s3_client.get_object(
            Bucket=param['Parameter']['Value'].split('/')[2],
            Key=param['Parameter']['Value'].split('/')[3]
        )
        self.instance_types = json.loads(file_obj['Body'].read().decode('utf-8'))

    def get_existing_job_definitions(self):
        """
        Get all existing AWS Batch job definitions that match to compute environments.
        """
        job_definitions = batch_client.describe_job_definitions(status='ACTIVE')
        self.job_definitions = {
            job_definition['jobDefinitionName'].replace('-', '.'): job_definition
            for job_definition in job_definitions['jobDefinitions']
            if job_definition['jobDefinitionName'].replace('-', '.') in self.instance_types.keys()
        }

    def create_missing_job_definitions(self):
        """
        Ensure that for each AWS Batch compute environment there is a job definition.
        """
        missing = self.get_missing_job_definition_names()
        job_definitions_to_create = {
            job_definition_name: self.instance_types[job_definition_name]
            for job_definition_name in missing
        }
        self.create_job_definitions(instance_types=job_definitions_to_create)

    def get_missing_job_definition_names(self):
        deployed = set(self.job_definitions.keys())
        required = set(self.instance_types.keys())
        missing = required.difference(deployed)
        return missing

    def create_job_definitions(self, instance_types=None):
        instance_types = self.instance_types if instance_types is None else instance_types
        for instance_type in instance_types:
            vcpus = instance_types[instance_type]['VCpuInfo']['DefaultVCpus']
            gpus = sum([gpu['Count'] for gpu in instance_types[instance_type]['GpuInfo']['Gpus']])
            memory = int(
                instance_types[instance_type]['MemoryInfo']['SizeInMiB'] * 0.9)  # reserve max. 90% of memory for tasks
            job_definition = batch_client.register_job_definition(
                jobDefinitionName=instance_type.replace(".", "-"),
                type='container',
                parameters={
                    'tags': ''
                },
                containerProperties={
                    'image': BASECALLER_DOCKER_IMAGE,
                    'resourceRequirements': [
                        {'type': 'VCPU', 'value': str(vcpus)},
                        {'type': 'GPU', 'value': str(gpus)},
                        {'type': 'MEMORY', 'value': str(memory)},
                    ],
                    'volumes': [
                        {
                            'host': {'sourcePath': '/fsx'},
                            'name': 'FSx-for-Lustre'
                        },
                        {
                            'host': {'sourcePath': '/usr/local/bin'},
                            'name': 'usr_local_bin'
                        },
                    ],
                    'mountPoints': [
                        {
                            'containerPath': '/fsx',
                            'sourceVolume': 'FSx-for-Lustre'
                        },
                        {
                            'containerPath': '/host/bin',
                            'sourceVolume': 'usr_local_bin'
                        },
                    ],
                }
            )
            self.job_definitions[instance_type] = job_definition

    def deregister_all_job_definitions(self):
        """
        Deregister all job definitions. Call this function if there are issues with the job definitions.
        Job definitions are re-created when an object is instanced from class BasecallerBatch.
        """
        for instance_type in self.instance_types.keys():
            job_definitions = batch_client.describe_job_definitions(
                jobDefinitionName=instance_type.replace(".", "-"),
                status='ACTIVE'
            )
            for job_definition in job_definitions['jobDefinitions']:
                batch_client.deregister_job_definition(jobDefinition=job_definition['jobDefinitionArn'])

    def submit_basecaller_job(self, instance_type='', job_queue=None, basecaller_params='', **kwargs):
        if not job_queue:
            job_queue = f'{instance_type.replace(".", "-")}'
        container_overrides = self.make_container_overrides(basecaller_params, **kwargs)
        job = batch_client.submit_job(
            jobName=instance_type.replace('.', '-'),
            jobQueue=job_queue,
            jobDefinition=self.job_definitions[instance_type]['jobDefinitionArn'],
            containerOverrides=container_overrides,
            retryStrategy={'attempts': 10}
        )
        return job['jobId']

    def terminate_all_jobs(self):
        for instance_type in self.instance_types:
            job_queue = f'{instance_type.replace(".", "-")}'
            for job_status in ['SUBMITTED', 'PENDING', 'RUNNABLE', 'STARTING', 'RUNNING']:
                jobs = batch_client.list_jobs(
                    jobQueue=job_queue,
                    jobStatus=job_status,
                )
                for job in jobs['jobSummaryList']:
                    print(f'terminating job: {job["jobId"]}')
                    batch_client.terminate_job(jobId=job['jobId'], reason='Cancelled by basecaller perf-bench')

    def make_container_overrides(self, basecaller_params='', **kwargs):
        env_vars = [
            {'name': 'REGION', 'value': aws_region_name},
        ]
        container_overrides = {'command': [basecaller_params]}
        if len(kwargs.keys()) > 0:
            container_overrides['resourceRequirements'] = []
            if 'vcpus' in kwargs.keys():
                container_overrides['resourceRequirements'].append(
                    {'type': 'VCPU', 'value': str(kwargs['vcpus'])}
                )
            if 'gpus' in kwargs.keys():
                container_overrides['resourceRequirements'].append(
                    {'type': 'GPU', 'value': str(kwargs['gpus'])}
                )
            if 'memory' in kwargs.keys():
                container_overrides['resourceRequirements'].append(
                    {'type': 'MEMORY', 'value': str(kwargs['memory'])}
                )
            if 'tags' in kwargs.keys():
                env_vars.append({'name': 'TAGS', 'value': ','.join(kwargs['tags'])})
            if 'data_set_id' in kwargs.keys():
                env_vars.append({'name': 'DATA_SET_ID', 'value': kwargs['data_set_id']})
        container_overrides['environment'] = env_vars
        return container_overrides
