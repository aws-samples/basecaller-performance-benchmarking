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
        LOGGER.info(f'EC2 Spot Instance interruption notice received. Event details = {json.dumps(event)}')
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
