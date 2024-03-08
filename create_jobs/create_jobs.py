#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generate ONT basecaller jobs for AWS Batch.
"""

import uuid
from string import Template

import boto3

from basecaller_batch.basecaller_batch import BasecallerBatch
from test_data.test_data import TestData

ssm_client = boto3.client('ssm')

# aws_batch_env.terminate_all_jobs()

gupppy_no_modified_bases = \
    'guppy_basecaller ' \
    '--compress_fastq ' \
    '--input_path ${file_list}/ ' \
    '--save_path /fsx/out/ ' \
    '--config dna_r10.4.1_e8.2_400bps_hac.cfg ' \
    '--bam_out ' \
    '--index ' \
    '--device cuda:all:100% ' \
    '--records_per_fastq 0 ' \
    '--progress_stats_frequency 600 ' \
    '--recursive ' \
    '--num_base_mod_threads ${num_base_mod_threads} ' \
    '--num_callers 16 ' \
    '--gpu_runners_per_device 8 ' \
    '--chunks_per_runner 2048'

gupppy_modified_bases_5mCG = \
    'guppy_basecaller ' \
    '--compress_fastq ' \
    '--input_path ${file_list}/ ' \
    '--save_path /fsx/out/ ' \
    '--config dna_r10.4.1_e8.2_400bps_modbases_5mc_cg_hac.cfg ' \
    '--bam_out ' \
    '--index ' \
    '--device cuda:all:100% ' \
    '--records_per_fastq 0 ' \
    '--progress_stats_frequency 600 ' \
    '--recursive ' \
    '--num_base_mod_threads ${num_base_mod_threads} ' \
    '--num_callers 16 ' \
    '--gpu_runners_per_device 8 ' \
    '--chunks_per_runner 2048'

gupppy_modified_bases_5mCG_5hmCG = \
    'guppy_basecaller ' \
    '--compress_fastq ' \
    '--input_path ${file_list}/ ' \
    '--save_path /fsx/out/ ' \
    '--config dna_r10.4_e8.1_modbases_5hmc_5mc_cg_hac.cfg ' \
    '--bam_out ' \
    '--index ' \
    '--device cuda:all:100% ' \
    '--records_per_fastq 0 ' \
    '--progress_stats_frequency 600 ' \
    '--recursive ' \
    '--num_base_mod_threads ${num_base_mod_threads} ' \
    '--num_callers 16 ' \
    '--gpu_runners_per_device 8 ' \
    '--chunks_per_runner 2048'

dorado_no_modified_bases = \
    'dorado basecaller ' \
    '/usr/local/dorado/models/dna_r10.4.1_e8.2_400bps_hac@v3.5.2 ' \
    '${file_list}/ ' \
    '--verbose | ' \
    'samtools view --threads 8 -O BAM -o /fsx/out/&job_id&/calls.bam'

dorado_modified_bases_5mCG = \
    'dorado basecaller ' \
    '/usr/local/dorado/models/dna_r10.4.1_e8.2_400bps_hac@v3.5.2 ' \
    '${file_list}/ ' \
    '--verbose ' \
    '--modified-bases 5mCG | ' \
    'samtools view --threads 8 -O BAM -o /fsx/out/&job_id&/calls.bam'

dorado_modified_bases_5mCG_5hmCG = \
    'dorado basecaller ' \
    '/usr/local/dorado/models/dna_r10.4.1_e8.2_400bps_hac@v4.0.0 ' \
    '${file_list}/ ' \
    '--verbose ' \
    '--modified-bases 5mCG_5hmCG | ' \
    'samtools view --threads 8 -O BAM -o /fsx/out/&job_id&/calls.bam'


def environment_is_ready():
    print('Checking benchmark environment readiness ...')
    download_status = ssm_client.get_parameter(
        Name='/ONT-performance-benchmark/download-status'
    )['Parameter']['Value']
    pod5_converter_status = ssm_client.get_parameter(
        Name='/ONT-performance-benchmark/pod5-converter-status'
    )['Parameter']['Value']
    print(f'Status downloading data set = {download_status}')
    print(f'Status converting data from FAST5 to POD5 format = {pod5_converter_status}')
    return download_status == 'completed' and pod5_converter_status == 'completed'


def create_jobs(instance_types: list, aws_batch_env: BasecallerBatch, cmd: str = '', tags: str = ''):
    test_data = TestData()
    test_data.load_pod5_subsets()
    params_templ = Template(cmd)
    for instance_type in instance_types:  # aws_batch_env.validated_instances:
        max_vcpus = aws_batch_env.instance_types[instance_type]['VCpuInfo']['DefaultVCpus']
        max_gpus = sum([gpu['Count'] for gpu in aws_batch_env.instance_types[instance_type]['GpuInfo']['Gpus']])
        max_memory = int(
            aws_batch_env.instance_types[instance_type]['MemoryInfo']['SizeInMiB'] * 0.9
        )
        file_lists = test_data.pod5_sample_data_subsets['wgs_subset_128_files'][max_gpus]  # 1 job per GPU
        data_set_id = str(uuid.uuid4())  # unique identifier that allows to track which
        # AWS batch jobs belong to the same data set
        print('Generating AWS Batch jobs ...')
        for file_list in file_lists:
            params = params_templ.substitute(
                file_list=file_list,
                num_base_mod_threads=max_vcpus // max_gpus if (max_vcpus // max_gpus) <= 48 else 48
            )
            job_id = aws_batch_env.submit_basecaller_job(
                instance_type=instance_type,
                basecaller_params=params,
                gpus=1,
                vcpus=max_vcpus // max_gpus,
                memory=max_memory // max_gpus,
                tags=[tags],
                data_set_id=data_set_id,
            )
            print(f'instance type: {instance_type}, tags: {tags}, file list: {file_list}, job ID: {job_id}')
        print('Done. Check the status of the jobs in the AWS Batch console.')


def main():
    if not environment_is_ready():
        print(f'The benchmark environment is not ready. Please try again later.')
        return
    else:
        print('The benchmark environment is ready.')

    aws_batch_env = BasecallerBatch()

    instance_types = ['g5.48xlarge', 'p3.16xlarge']

    # test p5.48xlarge spot
    instance_types = ['p5.48xlarge-spot']
    aws_batch_env.instance_types['p5.48xlarge-spot'] = aws_batch_env.instance_types['p5.48xlarge']


    # create guppy jobs
    # create_jobs(instance_types, aws_batch_env, cmd=gupppy_no_modified_bases, tags='guppy, no modified bases')
    # create_jobs(instance_types, aws_batch_env, cmd=gupppy_modified_bases_5mCG, tags='guppy, modified bases 5mCG')
    # create_jobs(instance_types, aws_batch_env, cmd=gupppy_modified_bases_5mCG_5hmCG, tags='guppy, modified bases 5mCG & 5hmCG')

    # create dorado jobs
    create_jobs(instance_types, aws_batch_env, cmd=dorado_no_modified_bases, tags='dorado, no modified bases')
    # create_jobs(instance_types, aws_batch_env, cmd=dorado_modified_bases_5mCG, tags='dorado, modified bases 5mCG')
    # create_jobs(instance_types, aws_batch_env, cmd=dorado_modified_bases_5mCG_5hmCG, tags='dorado, modified bases 5mCG & 5hmCG')


if __name__ == '__main__':
    main()
