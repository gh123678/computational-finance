"""Registered periods keep the sealed 2024-2025 test set inaccessible by default."""
DATASETS = {
    'development_2020q4': {'start': '20201001', 'end': '20201231', 'evaluation_start': None,
                           'title': '2020 年第四季度开发期'},
    'development_2020': {'start': '20191101', 'end': '20201231', 'evaluation_start': '20200101',
                         'title': '2020 年度开发期（2019 年末预热）'},
}


def dataset_config(name):
    if name not in DATASETS:
        raise ValueError('Unregistered dataset; sealed test periods cannot be requested')
    return DATASETS[name].copy()
