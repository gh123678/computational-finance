"""Explicitly registered development, validation and previously opened test windows."""
DATASETS = {
    'continuous_2016_2025_dividend_r1': {
        'start': '20151101', 'end': '20251231', 'evaluation_start': '20160101',
        'title': '2016–2025 连续账户公告分红修订r1（固定参数）',
    },
    'continuous_2016_2025': {
        'start': '20151101', 'end': '20251231', 'evaluation_start': '20160101',
        'title': '2016–2025 连续账户固定规则研究（一次初始资金）',
    },
    **{f'development_{year}': {
        'start': f'{year - 1}1101', 'end': f'{year}1231',
        'evaluation_start': f'{year}0101',
        'title': f'{year} 年度开发期（上年末预热，独立初始资金）',
    } for year in range(2016, 2020)},
    'development_2020q4': {'start': '20201001', 'end': '20201231', 'evaluation_start': None,
                           'title': '2020 年第四季度开发期'},
    'development_2020': {'start': '20191101', 'end': '20201231', 'evaluation_start': '20200101',
                         'title': '2020 年度开发期（2019 年末预热）'},
    **{f'validation_{year}': {
        'start': f'{year - 1}1101', 'end': f'{year}1231',
        'evaluation_start': f'{year}0101',
        'title': f'{year} 年度补充验证期（上年末预热，固定当前规则）',
    } for year in (2021, 2022, 2023)},
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
