#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generate ONT basecaller jobs for AWS Batch.
"""

import boto3

from basecaller_batch.basecaller_batch import BasecallerBatch, create_batch_jobs

ssm_client = boto3.client('ssm')

# aws_batch_env.terminate_all_jobs()  # <-- run this command to delete all running batch jobs

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


def main():
    if not environment_is_ready():
        print(f'The benchmark environment is not ready. Please try again later.')
        return
    else:
        print('The benchmark environment is ready.')

    aws_batch_env = BasecallerBatch()

    compute = [
        {'instance_type': 'g5.48xlarge', 'provisioning_model': 'EC2'},
        {'instance_type': 'p3.16xlarge', 'provisioning_model': 'EC2'},
    ]

    # test p5.48xlarge spot
    compute = [
        # {'instance_type': 'p5.48xlarge', 'provisioning_model': 'SPOT'},
        {'instance_type': 'g5.48xlarge', 'provisioning_model': 'SPOT'},
    ]

    # create guppy jobs
    # create_batch_jobs(compute, aws_batch_env, cmd=gupppy_no_modified_bases, tags='guppy, no modified bases')
    # create_batch_jobs(compute, aws_batch_env, cmd=gupppy_modified_bases_5mCG, tags='guppy, modified bases 5mCG')
    # create_batch_jobs(compute, aws_batch_env, cmd=gupppy_modified_bases_5mCG_5hmCG, tags='guppy, modified bases 5mCG & 5hmCG')

    # create dorado jobs
    create_batch_jobs(compute, aws_batch_env, cmd=dorado_no_modified_bases, tags='dorado, no modified bases')
    # create_batch_jobs(compute, aws_batch_env, cmd=dorado_modified_bases_5mCG, tags='dorado, modified bases 5mCG')
    # create_batch_jobs(compute, aws_batch_env, cmd=dorado_modified_bases_5mCG_5hmCG, tags='dorado, modified bases 5mCG & 5hmCG')


if __name__ == '__main__':
    main()
