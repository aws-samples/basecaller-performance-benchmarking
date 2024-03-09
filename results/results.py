#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Generate result files (diagrams, Excel cost tables, etc.).
"""

import pandas as pd
import plotly.express as px

import aws_pricing.aws_pricing as aws_pricing
import utilities.utilities as utils

print('Loading instance specifications ...')
instance_specs = utils.get_instance_specs('/ONT-performance-benchmark/aws-batch-instance-types')
print('Getting pricing for EC2 instance types ...')
instance_cost = aws_pricing.get_pricing(list(instance_specs.keys()))


def main():
    print('Loading data from DynamoDB ...')
    results = utils.get_data('/ONT-performance-benchmark/reports-table-name')
    if results.empty:
        print('No results found. Make sure to run the benchmark jobs first. Exiting ...')
        return
    print('Filtering results ...')
    results = filter_results(results)
    print('Processing results ...')
    results = utils.transform_samples_per_s(results)
    results = utils.transform_compute_environment(results)
    results = utils.add_basecaller_label(results)
    results = utils.add_data_set_id(results)
    results = utils.add_gpu_count(results, instance_specs)
    results = utils.calculate_runtimes(results)
    utils.check_consistency(results, instance_specs)
    results = utils.aggregate_samples_per_s_runtime(results)
    results = utils.add_display_label(results, instance_specs)
    results = utils.add_run_times(results)
    results = utils.add_cost(results, instance_cost)

    # select all data
    results_publication = results.copy()

    print('Generating chart "Basecaller performance in samples/s" ...')
    generate_chart_performance_samples_per_sec(results_publication)
    print('Generating chart "Basecaller runtimes for whole human genome (WHG) at 30x coverage" ...')
    generate_chart_runtime_whg_30x(results_publication)
    print('Generating cost tables ...')
    generate_cost_tables(results_publication)


def filter_results(df: pd.DataFrame):
    """

    Filter and collate all results of interest.

    In this function we collate all results from various benchmark runs. Failed and
    duplicate data is cleaned from the data set.

    """
    results = pd.DataFrame()

    # guppy

    temp = get_latest_run(df[(df['tags'] == 'guppy, no modified bases') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = 'no modified bases'
    results = pd.concat([results, temp], ignore_index=True)

    temp = get_latest_run(df[(df['tags'] == 'guppy, modified bases 5mCG') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = '5mCG'
    results = pd.concat([results, temp], ignore_index=True)

    temp = get_latest_run(df[(df['tags'] == 'guppy, modified bases 5mCG & 5hmCG') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = '5mCG_5hmCG'
    results = pd.concat([results, temp], ignore_index=True)

    # dorado

    temp = get_latest_run(df[(df['tags'] == 'dorado, no modified bases') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = 'no modified bases'
    results = pd.concat([results, temp], ignore_index=True)

    temp = get_latest_run(df[(df['tags'] == 'dorado, modified bases 5mCG') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = '5mCG'
    results = pd.concat([results, temp], ignore_index=True)

    temp = get_latest_run(df[(df['tags'] == 'dorado, modified bases 5mCG & 5hmCG') & (df['status'] == 'succeeded')].copy())
    if not temp.empty:
        temp.loc[:, 'modified_bases'] = '5mCG_5hmCG'
    results = pd.concat([results, temp], ignore_index=True)

    return results


def get_latest_run(df: pd.DataFrame):
    """

    Filter out multiple runs for each instance type. Only keep the run with the latest 'data_set_id'.

    Args:
        df: pandas dataframe already filtered by 'tag' column.

    Returns:
        results: filtered dataframe

    """
    last_runs = pd.merge(
        df.groupby('compute_environment').container_end_time.max().to_frame().reset_index(),
        df,
        left_on=['compute_environment', 'container_end_time'], right_on=['compute_environment', 'container_end_time'],
        how='left'
    )['data_set_id'].to_list()
    results = df[df['data_set_id'].isin(last_runs)]
    return results


def generate_chart_performance_samples_per_sec(results: pd.DataFrame):
    instance_order = results[
        (results['runtime_type'] == 'per WHG 30x') &
        (results['cost_region'] == 'us-west-2')
        ].sort_values(['samples_per_s'], ascending=False)['display_label'].unique()
    fig = px.bar(
        results[
            (results['runtime_type'] == 'per WHG 30x') &
            (results['cost_region'] == 'us-west-2')
            ],
        title='<b>Basecaller performance, samples/s (the higher the better)</b>',
        x='samples_per_s', y='display_label', color='basecaller', barmode='group', facet_col='modified_bases',
        facet_col_spacing=0.05,
        labels={
            'display_label': 'instance type',
            'samples_per_s': 'samples/s',
        },
        category_orders={
            'display_label': instance_order,
            'modified_bases': ['no modified bases', '5mCG', '5mCG_5hmCG'],
        },
        text_auto='.2s',
        orientation='h',
        height=200 + len(instance_order) * 90, width=1200,
    )
    fig.update_traces(textposition='outside', cliponaxis=False)
    fig.update_layout(legend_traceorder='reversed')
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=5mCG_5hmCG', 'with 5mCG/5hmCG calling'))
    )
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=5mCG', 'with 5mCG calling'))
    )
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=no modified bases', 'without modification calling'))
    )

    file_name = 'ONT_basecaller_performance_samples_s.png'
    print(f'Writing chart to file: {file_name}')
    fig.write_image(file_name, scale=4)


def generate_chart_runtime_whg_30x(results: pd.DataFrame):
    instance_order = results[
        (results['runtime_type'] == 'per WHG 30x') &
        (results['cost_region'] == 'us-west-2')
        ].sort_values(['runtime_h'], ascending=True)['display_label'].unique()
    fig = px.bar(
        results[
            (results['runtime_type'] == 'per WHG 30x') &
            (results['cost_region'] == 'us-west-2')
            ],
        title='<b>Basecaller performance, runtime [h] for whole human genome (WHG) at 30x coverage '
              '(the lower the better)</b>',
        x='runtime_h', y='display_label', color='basecaller', barmode='group', facet_col='modified_bases',
        facet_col_spacing=0.05,
        labels={
            'display_label': 'instance type',
            'runtime_h': 'runtime [h]',
        },
        category_orders={
            'display_label': instance_order,
            'modified_bases': ['no modified bases', '5mCG', '5mCG_5hmCG'],
        },
        text_auto='.1f',
        orientation='h',
        height=200 + len(instance_order) * 90, width=1200,
    )
    fig.update_traces(textposition='outside', cliponaxis=False)
    fig.update_layout(legend_traceorder='reversed')
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=5mCG_5hmCG', 'with 5mCG/5hmCG calling'))
    )
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=5mCG', 'with 5mCG calling'))
    )
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.replace('modified_bases=no modified bases', 'without modification calling'))
    )

    file_name = 'ONT_basecaller_performance_runtime_whg_30x.png'
    print(f'Writing chart to file: {file_name}')
    fig.write_image(file_name, scale=4)


def generate_cost_tables(results: pd.DataFrame):
    # transform data into structure suitable for multi-header Excel file
    columns = ['compute_environment', 'basecaller', 'modified_bases', 'runtime_type',
               'runtime_h', 'cost_region', 'cost_per_gigabase', 'cost_per_whg_30x']
    temp1 = results[columns].copy()
    temp1.rename(columns={'modified_bases': 'header_lvl_1'}, inplace=True)
    temp1.loc[:, 'header_lvl_2'] = 'runtime [h]'
    temp1.loc[:, 'header_lvl_3'] = temp1['runtime_type']
    temp1.loc[:, 'value'] = temp1['runtime_h']
    temp2 = results[columns].copy()
    temp2.rename(columns={'modified_bases': 'header_lvl_1'}, inplace=True)
    temp2.loc[:, 'header_lvl_2'] = 'cost [$]'
    temp2.loc[:, 'header_lvl_3'] = 'per gigabase'
    temp2.loc[:, 'value'] = temp2['cost_per_gigabase']
    temp3 = results[columns].copy()
    temp3.rename(columns={'modified_bases': 'header_lvl_1'}, inplace=True)
    temp3.loc[:, 'header_lvl_2'] = 'cost [$]'
    temp3.loc[:, 'header_lvl_3'] = 'per WHG 30x'
    temp3.loc[:, 'value'] = temp3['cost_per_whg_30x']
    df = pd.concat(
        [temp1, temp2, temp3], ignore_index=True
    )
    df_pivot = pd.pivot_table(
        df,
        values='value',
        index=['compute_environment', 'basecaller', 'cost_region'],
        columns=['header_lvl_1', 'header_lvl_2', 'header_lvl_3']
    )
    df_pivot = df_pivot.reindex(['runtime [h]', 'cost [$]'], axis=1, level=1)
    df_pivot = df_pivot.reindex(['per gigabase', 'per WHG 30x'], axis=1, level=2)
    df_pivot.reset_index(inplace=True)

    # add additional columns for Excel file
    df_pivot.loc[:, 'num_gpus'] = df_pivot.apply(
        lambda row: instance_specs[row.compute_environment.iloc[0]]['GpuInfo']['Gpus'][0]['Count'],
        axis=1
    )
    df_pivot.loc[:, 'cost_per_hour'] = df_pivot.apply(
        lambda row: instance_cost['instances'][row.cost_region.iloc[0]][row.compute_environment.iloc[0]]['cost_per_hour']
        if instance_cost['instances'][row.cost_region.iloc[0]][row.compute_environment.iloc[0]]['cost_per_hour'] else None,
        axis=1
    )

    # reorder and rename columns for readability
    df_pivot = df_pivot.round(decimals=2)
    df_pivot = df_pivot[[
        'cost_region', 'compute_environment', 'num_gpus', 'cost_per_hour', 'basecaller',
        'no modified bases']]
    df_pivot.rename(
        columns={
            'compute_environment': 'instance type',
            'num_gpus': 'GPUs',
            'cost_per_hour': 'cost/hour [$]',
            'no modified bases': 'without modification calling',
        },
        inplace=True
    )

    file_name = 'ONT_basecaller_performance_comparison.xlsx'
    print(f'Writing cost tables to file: {file_name}')
    with pd.ExcelWriter(file_name, engine='xlsxwriter') as writer:
        for region in df_pivot['cost_region'].unique():
            temp = df_pivot[df_pivot['cost_region'] == f'{region}'].copy()
            temp.sort_values([('without modification calling', 'cost [$]', 'per WHG 30x')], inplace=True)
            temp.reset_index(inplace=True)
            temp.drop('index', axis=1, level=0, inplace=True)
            temp.index += 1
            temp.loc[:, temp.columns != ('cost_region', '', '')].to_excel(writer, sheet_name=region)
    return


if __name__ == '__main__':
    main()
