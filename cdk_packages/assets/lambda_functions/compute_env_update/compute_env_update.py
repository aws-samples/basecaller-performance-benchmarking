#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging.handlers
import sys
import traceback

import boto3

# Path to a JSON file with all AWS Batch compute environments.
# This file is generated dynamically during CDK deployment
# of the performance benchmark environment.
BATCH_INSTANCE_TYPES = '/ONT-performance-benchmark/aws-batch-instance-types'
BATCH_LAUNCH_TEMPLATE = '/ONT-performance-benchmark/aws-batch-launch-template'

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')
batch_client = boto3.client('batch')
ec2_client = boto3.client('ec2')

param = ssm_client.get_parameter(Name=BATCH_INSTANCE_TYPES)
lt = ssm_client.get_parameter(Name=BATCH_LAUNCH_TEMPLATE)['Parameter']['Value']


def lambda_handler(event=None, context=None):
    try:
        update_compute_environments(event, context)
        return {
            'statusCode': 200,
            'body': 'Ok',
        }
    except Exception:
        # log any exception, required for troubleshooting
        exception_type, exception_value, exception_traceback = sys.exc_info()
        traceback_string = traceback.format_exception(
            exception_type, exception_value, exception_traceback)
        err_msg = json.dumps({
            "errorType": exception_type.__name__,
            "errorMessage": str(exception_value),
            "stackTrace": traceback_string
        })
        LOGGER.error(err_msg)
        return {
            'statusCode': 500,
            'body': 'Error. Check CloudWatch Logs.',
        }


def update_compute_environments(event, context):
    lt_id = get_launch_template_id(event)
    if lt == lt_id:
        compute_environments = get_aws_batch_compute_environments()
        LOGGER.info(f'Current configuration of launch template "{lt}":')
        lt_config = ec2_client.describe_launch_template_versions(LaunchTemplateId=lt)
        LOGGER.info(json.dumps(lt_config['LaunchTemplateVersions'], default=str))
        for compute_environment in compute_environments:
            update_compute_environment(compute_environment)


def get_launch_template_id(event):
    lt_id = event['detail']['requestParameters']['CreateLaunchTemplateVersionRequest']['LaunchTemplateId'] \
        if 'CreateLaunchTemplateVersionRequest' in event['detail']['requestParameters'].keys() \
        else None
    return lt_id


def get_aws_batch_compute_environments():
    """
    Read list of AWS Batch compute environments. The list is stored as JSON file
    on S3. The list is generated during the deployment of the AWS Batch environment.
    """
    file_obj = s3_client.get_object(
        Bucket=param['Parameter']['Value'].split('/')[2],
        Key=param['Parameter']['Value'].split('/')[3]
    )
    instance_types = json.loads(file_obj['Body'].read().decode('utf-8'))
    compute_environments = []
    for instance_type in instance_types:
        if 'EC2' in instance_types[instance_type]['ProvisioningModel'].keys():
            compute_environments.append(instance_types[instance_type]['ProvisioningModel']['EC2'])
        if 'SPOT' in instance_types[instance_type]['ProvisioningModel'].keys():
            compute_environments.append(instance_types[instance_type]['ProvisioningModel']['SPOT'])
    return compute_environments


def update_compute_environment(env_name):
    LOGGER.info(f'Updating AWS Batch compute environment "{env_name}".')
    resp = batch_client.update_compute_environment(
        computeEnvironment=env_name,
        computeResources={
            'launchTemplate': {
                'launchTemplateId': lt,
                'version': '$Latest'
            },
        },
    )
    LOGGER.info(f'response HTTP status code: {resp["ResponseMetadata"]["HTTPStatusCode"]}')
