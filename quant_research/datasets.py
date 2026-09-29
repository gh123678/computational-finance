"""Registered periods keep the sealed 2024-2025 test set inaccessible by default."""
DATASETS = {
    **{f'development_{year}': {
        'start': f'{year - 1}1101', 'end': f'{year}1231',
        'evaluation_start': f'{year}0101',
        'title': f'{year} 年度开发期（上年末预热，独立初始资金）',
    } for year in range(2016, 2020)},
    'development_2020q4': {'start': '20201001', 'end': '20201231', 'evaluation_start': None,
                           'title': '2020 年第四季度开发期'},
    'development_2020': {'start': '20191101', 'end': '20201231', 'evaluation_start': '20200101',
                         'title': '2020 年度开发期（2019 年末预热）'},
    **{f'out_of_sample_{year}': {
        'start': f'{year - 1}1101', 'end': f'{year}1231',
        'evaluation_start': f'{year}0101',
        'title': f'{year} 年度样本外测试期（上年末预热，参数已冻结）',
    } for year in (2024, 2025)},
}


def dataset_config(name):
    if name not in DATASETS:
        raise ValueError('Unregistered dataset; sealed test periods cannot be requested')
    return DATASETS[name].copy()
