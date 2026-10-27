"""Unimplemented testing checklist. Skips are NOT passes or assignment completion.

Replace each skip with your own assertions after an independent derivation or
benchmark. Do not merely delete the skip and leave an empty test function.
"""
import pytest

@pytest.mark.parametrize("check", [
    "reject nonpositive or nonfinite prices",
    "audit duplicate, invalid, unsorted, and missing dates",
    "check a return-aggregation identity",
    "check histogram normalization and Q-Q ordering",
    "distinguish marginal and temporal statistics after permutation",
    "check physical-model annualization and units",
    "compare GBM moments and quantiles with independent reasoning",
    "handle deterministic limits and invalid model inputs",
    "test mean-interval scaling without mistaking it for prediction",
    "preserve a common terminal Brownian increment on coarse grids",
    "retain nonpositive Euler multipliers in a stress test",
    "compare discrete moments, convergence, and batch reproducibility",
])
def test_design_and_implement(check):
    pytest.skip("TODO: " + check)
