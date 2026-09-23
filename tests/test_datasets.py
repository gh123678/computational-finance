import pytest
from quant_research.datasets import dataset_config
from quant_research.backtest import Config


def test_registered_annual_dataset_has_warmup_but_no_test_period():
    spec = dataset_config('development_2020')
    assert spec['start'] < spec['evaluation_start'] <= spec['end'] < '20240101'
    spec['end'] = '20251231'
    assert dataset_config('development_2020')['end'] == '20201231'


def test_unregistered_test_period_cannot_be_requested():
    with pytest.raises(ValueError, match='sealed'):
        dataset_config('test_2024')


def test_zero_transaction_cost_scenario_keeps_dividend_tax_assumption():
    cfg = Config(zero_trading_costs=True)
    fees = cfg.fees('2020-01-06')
    assert fees.cost(100000., 'buy') == fees.cost(100000., 'sell') == 0
    assert fees.slippage_bps == 0
    assert cfg.dividend_tax == .2
