#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Library for batching test data.

"""

import json
import re
from string import Template

import boto3
import numpy as np
import pandas as pd

PARAMETER_S3_BUCKET = '/ONT-performance-benchmark/data-s3-bucket'
FAST5_TEST_DATA_KEY_PREFIX = 'fast5-all-files/'
POD5_TEST_DATA_KEY_PREFIX = 'pod5-all-files/'
FAST5_FILE_LISTS_KEY_PREFIX = 'fast5-file-lists/'
POD5_FILE_LISTS_KEY_PREFIX = 'pod5-file-lists/'
POD5_FILE_LISTS_MANIFEST = 'pod5-subsets/manifest.json'

ssm_client = boto3.client('ssm')
s3_client = boto3.client('s3')


def chunk_file_list(list_to_chunk, num_chunks=1):
    chunks = np.array_split(list_to_chunk, num_chunks)
    return chunks


def save_chunk_files(batch, template, s3_bucket, key_prefix):
    template = Template(template)
    file_list = []
    for idx, batch in enumerate(batch):
        file_name = template.substitute(idx=idx)
        s3_client.put_object(
            Body='\n'.join(batch['file'].to_list()),
            Bucket=s3_bucket,
            Key=key_prefix + file_name
        )
        file_list.append(file_name)
    return file_list


def create_list_files(sample_data_sets, files, num_chunks_list, s3_bucket, key_prefix):
    for data_set_name in sample_data_sets:
        for num_chunks in num_chunks_list:
            sample_data_sets[data_set_name].update({
                num_chunks: save_chunk_files(
                    chunk_file_list(
                        files[:sample_data_sets[data_set_name]['num_files']],
                        num_chunks=num_chunks
                    ),
                    f'{data_set_name}_{num_chunks}_${{idx}}.lst',
                    s3_bucket,
                    key_prefix)
            })


class TestData:

    def __init__(self):
        self.s3_bucket = ssm_client.get_parameter(Name=PARAMETER_S3_BUCKET)['Parameter']['Value']
        self.fast5_all_files = self.get_file_list(r'_(?P<file_no>[0-9]+)\.fast5', FAST5_TEST_DATA_KEY_PREFIX)
        self.pod5_all_files = self.get_file_list(r'_(?P<file_no>[0-9]+)\.pod5', POD5_TEST_DATA_KEY_PREFIX)
        self.fast5_sample_data_sets = {
            'wgs_full_set': {
                'num_files': None
            },
            'wgs_subset_8_files': {
                'num_files': 8
            },
            'wgs_subset_16_files': {
                'num_files': 16
            },
            'wgs_subset_64_files': {
                'num_files': 64
            },
            'wgs_subset_128_files': {
                'num_files': 128
            },
        }
        self.pod5_sample_data_sets = {
            'wgs_full_set': {
                'num_files': None
            },
            'wgs_subset_8_files': {
                'num_files': 8
            },
            'wgs_subset_16_files': {
                'num_files': 16
            },
            'wgs_subset_64_files': {
                'num_files': 64
            },
            'wgs_subset_128_files': {
                'num_files': 128
            },
        }
        self.pod5_sample_data_subsets = {}
        self.num_chunks = [1, 2, 4, 8]

    def get_file_list(self, pattern, key_prefix):
        files = [
            (e['Key'].split('/')[-1],
             int(re.search(pattern, e['Key'].split('/')[-1])['file_no']),
             e['Size'])
            for p in s3_client.get_paginator('list_objects_v2').paginate(
                Bucket=self.s3_bucket,
                Prefix=key_prefix
            )
            for e in p['Contents'] if re.search(pattern, e['Key'].split('/')[-1])
        ]
        files_df = pd.DataFrame(files, columns=['file', 'no', 'size'])
        files_df.set_index('no', inplace=True)
        files_df.sort_index(inplace=True)
        return files_df

    def create_fast5_list_files(self):
        create_list_files(
            self.fast5_sample_data_sets,
            self.fast5_all_files,
            self.num_chunks,
            self.s3_bucket,
            FAST5_FILE_LISTS_KEY_PREFIX
        )

    def create_pod5_list_files(self):
        create_list_files(
            self.pod5_sample_data_sets,
            self.pod5_all_files,
            self.num_chunks,
            self.s3_bucket,
            POD5_FILE_LISTS_KEY_PREFIX
        )

    def load_pod5_subsets(self):
        data = s3_client.get_object(Bucket=self.s3_bucket, Key=POD5_FILE_LISTS_MANIFEST)
        contents = data['Body'].read().decode('utf-8')
        self.pod5_sample_data_subsets = json.loads(contents)
        # convert numerical string keys to integer
        for key in self.pod5_sample_data_subsets.keys():
            self.pod5_sample_data_subsets[key] = {
                chunk: self.pod5_sample_data_subsets[key][str(chunk)] for chunk in self.num_chunks
            }
