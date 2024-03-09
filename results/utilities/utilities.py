#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

Collection of helper and utility functions for collecting and analysing the benchmarking results.

"""

import glob
import json

import boto3
import pandas as pd
from dynamo_pandas import get_df

client_ssm = boto3.client('ssm')
client_s3 = boto3.client('s3')
client_dynamodb = boto3.client('dynamodb')


def get_data(ssm_parameter_name: str):
    # load all results from DynamoDB table
    try:
        results_table = client_ssm.get_parameter(Name=ssm_parameter_name)['Parameter']['Value']
        df = get_df(table=results_table)
    except (
            client_ssm.exceptions.ParameterNotFound,
            client_dynamodb.exceptions.ResourceNotFoundException,
    ) as e:
        pass
    else:
        # save results to file, we do this to preserve results in case the DynamoDB is deleted
        df.to_hdf(f'results_table_{results_table}.h5', key='df', mode='w')
    # Load and join all saved result tables. This merges all results from different DynamoDB tables in case
    # environments gets repeatedly deployed and the name of the DynamoDB tables changes with each deployment.
    dir_path = 'results_table_*.h5'
    h5_files = glob.glob(dir_path)
    # merge data from h5 files
    df = pd.DataFrame()
    for h5_file in h5_files:
        df = pd.concat(
            [
                df,
                pd.read_hdf(h5_file, 'df'),
            ],
            ignore_index=True
        )
    return df


def get_instance_specs(ssm_parameter_name: str):
    """
    Load instance specs from S3 bucket and SSM parameter store.
    The SSM parameter store contains the S3 path to the instance specs file.
    The S3 bucket contains the instance specs file.
    The instance specs file contains the instance specs.

    Args:
        ssm_parameter_name: path to parameter in SSM Parameter Store.

    Returns:
        instance_specs: instance specs as dict

    """
    try:
        print('Loading instance specifications from S3 ...')
        instance_specs_file_uri = client_ssm.get_parameter(Name=ssm_parameter_name)['Parameter']['Value']
        file_obj = client_s3.get_object(
            Bucket=instance_specs_file_uri.split('/')[2],
            Key=instance_specs_file_uri.split('/')[3]
        )
        instance_specs = json.loads(file_obj['Body'].read().decode('utf-8'))
    except (
            client_ssm.exceptions.ParameterNotFound,
            client_s3.exceptions.NoSuchKey,
    ) as e:
        instance_specs = load_instance_specs_from_file()
    else:
        save_instance_specs_to_file(instance_specs)
    return instance_specs


def save_instance_specs_to_file(instance_specs):
    """
    Save instance specs to file.
    The instance specs file contains the instance specs.

    """
    with open('instance_specs.json', 'w') as f:
        json.dump(instance_specs, f)


def load_instance_specs_from_file():
    """
    Load instance specs from file.
    The instance specs file contains the instance specs.

    Returns:
        instance_specs: instance specs as dict

    """
    print('Instance specifications not found in S3.')
    print('Loading instance specifications from file ...')
    with open('instance_specs.json', 'r') as f:
        instance_specs = json.load(f)
    return instance_specs


def transform_samples_per_s(df: pd.DataFrame):
    df['samples_per_s'] = df['samples_per_s'].astype('float64')
    df = df.drop(df[df['samples_per_s'] < 1].index)
    return df


def transform_compute_environment(df: pd.DataFrame):
    df['compute_environment'] = df['compute_environment'].apply(lambda instance_type: instance_type.replace('-', '.'))
    return df


def add_basecaller_label(df: pd.DataFrame):
    df[['basecaller']] = pd.DataFrame(
        df.apply(lambda row: create_basecaller_label(row), axis=1).tolist(), index=df.index)
    return df


def add_data_set_id(df: pd.Series):
    df[['data_set_id']] = pd.DataFrame(
        df.apply(lambda row: create_data_set_id(row), axis=1).tolist(), index=df.index)
    return df


def add_display_label(df: pd.Series, instance_specs: dict):
    df[['display_label']] = pd.DataFrame(
        df.apply(lambda row: create_y_label(row, instance_specs), axis=1).tolist(), index=df.index)
    return df


def add_gpu_count(df: pd.Series, instance_specs: dict):
    df.loc[:, 'num_gpus'] = df.apply(
        lambda row: instance_specs[row.compute_environment]['GpuInfo']['Gpus'][0]['Count'],
        axis=1
    )
    return df


def calculate_runtimes(df: pd.DataFrame):
    df['container_start_time'] = pd.to_datetime(df['container_start_time'])
    df['container_end_time'] = pd.to_datetime(df['container_end_time'])
    df['container_run_time'] = df['container_end_time'] - df['container_start_time']
    df['container_run_time_h'] = df['container_run_time'].apply(lambda delta: delta.total_seconds() / 3600)
    return df


def add_run_times(df: pd.DataFrame):
    """
    Add the estimated run times for 1 gigabase and 1 whole human genome at 30x coverage.

    IMPORTANT: The runtime estimations are only accurate if the test runs were conducted
    with the first 128 FAST5 files of the CliveOME 5mC dataset, flowcell ONLA29134. This
    data set is downloaded as part of cdk_packages\assets\download_files.sh. For
    information about the data set please see: https://labs.epi2me.io/cliveome_5mc_cfdna_celldna/.

    The number of gigabases was established by running the command below against the output
    of the dorado basecaller:

    gzip -cd /fsx/out/e2273a88-5f0a-4751-b819-0c0efc6c28a1/pass/fastq_runid_*.fastq.gz | paste - - - - | cut -f 2 | tr -d '\n' | wc -c

    """

    num_bases = 18330576791  # number of bases in the first 128 FAST5 files
    num_gigabases = num_bases / 1000000000
    num_gigabases_whg_GRCh38_p14 = 3298912062 / 1000000000  # source: https://www.ncbi.nlm.nih.gov/grc/human/data
    num_gigabases_whg_30x_coverage = num_gigabases_whg_GRCh38_p14 * 30

    temp1 = df.copy()
    temp2 = df.copy()

    temp1[['runtime_type', 'runtime_h']] = df.apply(
        lambda row: ('per gigabase', row.container_run_time_h / num_gigabases),
        axis=1, result_type='expand'
    )
    temp2[['runtime_type', 'runtime_h']] = df.apply(
        lambda row: ('per WHG 30x', row.container_run_time_h * (num_gigabases_whg_30x_coverage / num_gigabases)),
        axis=1, result_type='expand'
    )

    df = pd.concat([temp1, temp2], ignore_index=True)

    return df


def check_consistency(df: pd.DataFrame, instance_specs: dict):
    """
    Do consistency check.
    """
    # Find the completed test runs with failed batch jobs.
    df['status_succeeded'] = df[(df['status'] == 'succeeded')]['status']
    df['status_failed'] = df[(df['status'] == 'failed')]['status']
    df = df[(df['status'] == 'succeeded') | (df['status'] == 'failed')] \
        .groupby(['compute_environment', 'data_set_id', 'tags', 'num_gpus']) \
        .agg({'status_succeeded': 'count', 'status_failed': 'count'}) \
        .reset_index()
    df['status_count'] = df['status_succeeded'] + df['status_failed']
    df = df[(df['status_count'] == df['num_gpus']) & (df['status_failed'] > 0)]
    if not df.empty:
        print('The following test runs have failed:')
        for _, row in df.iterrows():
            print(f'Instance type: {row.compute_environment}, '
                  f'tags: "{row.tags}", '
                  f'no. failed jobs: {row.status_failed}, '
                  f'no. succeeded jobs: {row.status_succeeded}')


def aggregate_samples_per_s_runtime(df: pd.DataFrame):
    df = df[df['status'] == 'succeeded'] \
        .groupby(['modified_bases', 'compute_environment', 'num_gpus', 'data_set_id', 'basecaller']) \
        .agg({'samples_per_s': 'sum', 'container_run_time_h': 'mean'}) \
        .reset_index()
    return df


def create_y_label(row: pd.Series, instance_specs: dict):
    instance_type = row.compute_environment.replace("-", ".")
    gpu_count = instance_specs[instance_type]['GpuInfo']['Gpus'][0]['Count']
    gpu_name = instance_specs[instance_type]['GpuInfo']['Gpus'][0]['Name']
    gpu_manufacturer = instance_specs[instance_type]['GpuInfo']['Gpus'][0]['Manufacturer']
    gpu_mem_in_gib = instance_specs[instance_type]['GpuInfo']['Gpus'][0]['MemoryInfo']['SizeInMiB'] // 1024
    vcpus = instance_specs[instance_type]['VCpuInfo']['DefaultVCpus']
    memory_in_gib = instance_specs[instance_type]['MemoryInfo']['SizeInMiB'] // 1024
    label_text = f'<b>{instance_type}  </b><br>' \
                 f'<i>{gpu_count} x {gpu_name} {gpu_manufacturer} GPUs w/ {gpu_mem_in_gib} GiB </i><br>' \
                 f'<i>{vcpus} vCPUs, {memory_in_gib} GiB RAM </i>'
    return label_text


def create_basecaller_label(row: pd.Series):
    if 'basecaller' not in row.keys():
        basecaller = f'{row.basecaller_name} v{row.basecaller_version}'
    else:
        basecaller = row.basecaller
    return basecaller


def create_data_set_id(row: pd.Series):
    data_set_id = row.data_set_id
    if row.isna().data_set_id:
        data_set_id = row.ec2_instance_id
    return data_set_id


def add_cost(df: pd.DataFrame, aws_pricing: dict):
    """
    Add cost information to the dataframe.
    """
    cost = pd.DataFrame()
    for region in aws_pricing['instances'].keys():
        temp = df.copy()
        temp[['cost_region', 'cost_per_hour']] = df.apply(
            lambda row: (
                region,
                aws_pricing['instances'][region][row['compute_environment']]['cost_per_hour']
                if aws_pricing['instances'][region][row['compute_environment']]['cost_per_hour'] else None
            ), axis=1, result_type='expand'
        )
        temp['cost_per_gigabase'] = temp[temp['runtime_type'] == 'per gigabase'].apply(
            lambda row: (
                row['cost_per_hour'] * row['runtime_h'] if row['cost_per_hour'] else None
            ), axis=1, result_type='expand'
        )
        temp['cost_per_whg_30x'] = temp[temp['runtime_type'] == 'per WHG 30x'].apply(
            lambda row: (
                row['cost_per_hour'] * row['runtime_h'] if row['cost_per_hour'] else None
            ), axis=1, result_type='expand'
        )
        cost = pd.concat([cost, temp], ignore_index=True)
    return cost


def get_cost_per_hour(row: pd.Series, region: str, aws_pricing: dict):
    cost = aws_pricing['instances'][region][row['compute_environment']]['cost_per_hour'] \
        if aws_pricing['instances'][region][row['compute_environment']]['cost_per_hour'] else None
    return cost


def consolidate(s: pd.Series):
    temp_s = s.reset_index().iloc[:, -1]
    value = temp_s.loc[temp_s.first_valid_index()] if temp_s.first_valid_index() != None else None
    return value
