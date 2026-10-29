import numpy as np
import pandas as pd
import pytest

from gasdash import spreads


def test_clean_spark_spread_hand_calculation():
    # 100 - 40/0.5 - (0.2/0.5)*80 - 2 = 100 - 80 - 32 - 2 = -14
    assert spreads.clean_spark_spread(100.0, 40.0, 80.0, 0.5, emission_factor=0.2, vom=2.0) == pytest.approx(-14.0)


def test_spark_spread_excludes_carbon():
    assert spreads.spark_spread(100.0, 40.0, 0.5) == pytest.approx(20.0)


def test_higher_efficiency_raises_css():
    low = spreads.clean_spark_spread(90.0, 35.0, 70.0, 0.50)
    high = spreads.clean_spark_spread(90.0, 35.0, 70.0, 0.58)
    assert high > low


def test_breakeven_efficiency_zeroes_css():
    power = pd.Series([95.0, 120.0])
    gas = pd.Series([35.0, 40.0])
    co2 = pd.Series([70.0, 90.0])
    eta = spreads.breakeven_efficiency(power, gas, co2, vom=3.0)
    css = [spreads.clean_spark_spread(p, g, c, e, vom=3.0) for p, g, c, e in zip(power, gas, co2, eta)]
    assert np.allclose(css, 0.0)


def test_breakeven_nan_for_non_positive_power():
    eta = spreads.breakeven_efficiency(pd.Series([-5.0, 0.0]), pd.Series([30.0, 30.0]), pd.Series([60.0, 60.0]))
    assert eta.isna().all()


@pytest.mark.parametrize("eta", [0, -0.1, 1.2])
def test_invalid_efficiency(eta):
    with pytest.raises(ValueError):
        spreads.clean_spark_spread(100.0, 30.0, 60.0, eta)


def test_add_spreads_columns_are_consistent():
    df = pd.DataFrame({"power_eur_mwh": [100.0], "gas_eur_mwh": [30.0], "co2_eur_t": [60.0]})
    out = spreads.add_spreads(df, 0.55)
    row = out.iloc[0]
    assert row["css"] == pytest.approx(row["power_eur_mwh"] - row["fuel_cost"] - row["carbon_cost"])
    assert row["spark_spread"] - row["css"] == pytest.approx(row["carbon_cost"])


def test_css_by_efficiency_is_monotonic():
    df = pd.DataFrame({"power_eur_mwh": [100.0], "gas_eur_mwh": [30.0], "co2_eur_t": [60.0]})
    grid = spreads.css_by_efficiency(df, spreads.efficiency_grid())
    assert list(grid.columns) == ["css_0.50", "css_0.52", "css_0.54", "css_0.56", "css_0.58"]
    assert grid.iloc[0].is_monotonic_increasing
