#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cdk_packages.assets.lambda_functions.compute_env_update.compute_env_update as compute_env_update


def test_get_aws_batch_compute_environments():
    ret = compute_env_update.get_aws_batch_compute_environments()
    assert len(ret) > 0
    assert 'g5-2xlarge' in ret
    assert 'g4dn-2xlarge' in ret


def test_lambda_handler():
    event = {
        'detail': {
            'requestParameters': {
                'CreateLaunchTemplateVersionRequest': {
                    'LaunchTemplateId': compute_env_update.lt
                }
            }
        }
    }
    ret = compute_env_update.lambda_handler(event)
    assert ret['body'] == 'Ok'
    assert ret['statusCode'] == 200
