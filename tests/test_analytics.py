import numpy as np
import pandas as pd
import pytest

from gasdash import analytics


def test_historical_band_uses_previous_five_years_only():
    idx = pd.date_range("2019-01-01", "2025-12-31", freq="D")
    s = pd.Series(idx.year.astype(float), index=idx)  # value == year
    band = analytics.historical_band(s, years=5)
    # 2025 compares with 2020..2024
    assert band.loc["2025-06-01", "avg"] == pytest.approx(2022.0)
    assert band.loc["2025-06-01", "min"] == 2020.0
    assert band.loc["2025-06-01", "max"] == 2024.0
    # 2023 has only 2019..2022 (4 years) of history -> undefined
    assert np.isnan(band.loc["2023-06-01", "avg"])


def test_historical_band_aligns_leap_years():
    idx = pd.date_range("2019-01-01", "2024-12-31", freq="D")
    s = pd.Series(idx.dayofyear.astype(float), index=idx)
    s[idx.is_leap_year & (idx.dayofyear >= 60)] -= 1  # same calendar date -> same value; 29 Feb == 28 Feb
    band = analytics.historical_band(s, years=5)
    assert band.loc["2024-12-31", "avg"] == pytest.approx(365.0)
    assert band.loc["2024-03-01", "avg"] == pytest.approx(60.0)
    assert band.loc["2024-02-29", "avg"] == pytest.approx(59.0)


def test_rolling_zscore_flags_shock_and_excludes_current():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0, 1, 100), index=pd.date_range("2024-01-01", periods=100))
    s.iloc[-1] = 10.0
    z = analytics.rolling_zscore(s, window=30)
    base = s.iloc[-31:-1]
    assert z.iloc[-1] == pytest.approx((10.0 - base.mean()) / base.std())
    assert z.iloc[-1] > 5
    assert z.iloc[:20].isna().all()


def test_rolling_zscore_constant_series_is_nan_not_inf():
    z = analytics.rolling_zscore(pd.Series(np.ones(50)), window=10)
    assert not np.isinf(z).any()


def test_detect_signals_rules():
    df = pd.DataFrame(
        {
            "storage_vs_5y_pp_z": [-1.5, 1.5, -1.5, 0.0, 0.0],
            "wind_mw_z": [-1.2, 1.3, 0.5, 0.0, 0.0],
            "css_z": [0.0, 0.0, 0.0, 2.5, -2.5],
        }
    )
    out = analytics.detect_signals(df, threshold=1.0, css_threshold=2.0)
    assert out["signal"].tolist() == ["Bullish power", "Bearish power", "", "CSS rich", "CSS cheap"]
    assert out.loc[0, "signal_score"] == pytest.approx(1.35)
