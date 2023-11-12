#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging.handlers
import sys
import traceback

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')
ib_client = boto3.client('imagebuilder')
cf_resource = boto3.resource('cloudformation')


def lambda_handler(event=None, context=None):
    """
    Function is triggered by EventBridge when EC2 instance is in stopped state.
    """
    try:
        start_image_builds(event, context)
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


def start_image_builds(event, context):
    cf_stack = cf_resource.Stack(event['detail']['stack-id'])
    outputs = {output['OutputKey']: output['OutputValue'] for output in cf_stack.outputs}
    if 'EC2ImageBuilderPipelineARN' in outputs.keys():
        LOGGER.info(f'starting EC2 Image Builder pipeline {outputs["EC2ImageBuilderPipelineARN"]}.')
        resp = ib_client.start_image_pipeline_execution(
            imagePipelineArn=outputs["EC2ImageBuilderPipelineARN"],
        )
        LOGGER.info(f'response HTTP status code: {resp["ResponseMetadata"]["HTTPStatusCode"]}')

    # Delete previous AMI versions
    images = ib_client.list_images(
        owner='Self',
        filters=[{'name': 'name', 'values': ['ONT base image']}],
        byName=False,
    )
    for image in images['imageVersionList']:
        image_build_versions = ib_client.list_image_build_versions(
            imageVersionArn=image['arn'],
            filters=[{'name': 'name', 'values': ['ONT base image']}],
        )
        for image_build_version in image_build_versions['imageSummaryList']:
            LOGGER.info(f'deleting previous image build version "{image_build_version["name"]} '
                        f'{image_build_version["version"]}".')
            resp = ib_client.delete_image(
                imageBuildVersionArn=image_build_version['arn']
            )
            LOGGER.info(f'response HTTP status code: {resp["ResponseMetadata"]["HTTPStatusCode"]}')
