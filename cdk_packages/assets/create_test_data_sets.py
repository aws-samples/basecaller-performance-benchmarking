#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

Create collections of symlinks to POD5 files to provide sets of test data of different sizes.
These are test data sets for use with the Oxford Nanopore dorado basecaller. The basecaller requires
a directory as input. With the different directories with symlinks back to the original files,
different data set sizes can be provided for testing purposes.

"""

import glob
import json
import os
import re
from string import Template

import numpy as np
import pandas as pd

POD5_DATA_PATH = '/fsx/pod5-all-files/'
POD5_SUBSET_PATH = '/fsx/pod5-subsets/'


def chunk_file_list(list_to_chunk, num_chunks=1):
    chunks = np.array_split(list_to_chunk, num_chunks)
    return chunks


def create_symlinks(batch, template, base_path):
    template = Template(template)
    file_list = []
    for idx, batch in enumerate(batch):
        # create directory with the name of the sub data set
        full_path = os.path.join(POD5_SUBSET_PATH, template.substitute(idx=idx))
        os.makedirs(full_path, exist_ok=True)
        for f in batch['file']:
            # create the symlinks within the new directory
            src = os.path.join(POD5_DATA_PATH, f)
            dst = os.path.join(full_path, f)
            if not os.path.islink(dst):
                os.symlink(src, dst)
        file_list.append(full_path)
    return file_list


def get_file_list():
    dir_path = f'{POD5_DATA_PATH}*.pod5'
    pod5_files = glob.glob(dir_path)
    files = [
        (f, int(re.search(r'_(?P<file_no>\d+)\.pod5', f)['file_no']))
        for f in [os.path.basename(f) for f in pod5_files]
    ]
    files_df = pd.DataFrame(files, columns=['file', 'no'])
    files_df.set_index('no', inplace=True)
    files_df.sort_index(inplace=True)
    return files_df


class TestData:

    def __init__(self):
        self.all_files = get_file_list()
        self.sample_data_sets = {
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
        self.num_chunks = [1, 2, 4, 8]
        self.create_list_files()
        self.save_manifest()

    def create_list_files(self):
        for data_set_name in self.sample_data_sets:
            for num_chunks in self.num_chunks:
                self.sample_data_sets[data_set_name].update({
                    num_chunks: create_symlinks(
                        chunk_file_list(
                            self.all_files[:self.sample_data_sets[data_set_name]['num_files']],
                            num_chunks=num_chunks
                        ),
                        f'{data_set_name}_{num_chunks}_${{idx}}.lst',
                        POD5_SUBSET_PATH
                    )
                })

    def save_manifest(self):
        with open(os.path.join(POD5_SUBSET_PATH, 'manifest.json'), 'w') as fp:
            json.dump(self.sample_data_sets, fp, indent=4)


test_data = TestData()
