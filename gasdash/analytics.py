"""Seasonal storage benchmarks, rolling Z-scores and the anomaly / signal engine."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _season_day(index: pd.DatetimeIndex) -> np.ndarray:
    """Day of year on a 365-day calendar (29 Feb shares 28 Feb's slot)."""
    doy = index.dayofyear.to_numpy().copy()
    doy[index.is_leap_year & (doy >= 60)] -= 1
    return doy


def historical_band(series: pd.Series, years: int = 5) -> pd.DataFrame:
    """For every date, the mean/min/max of the same calendar day over the ``years`` prior years.

    Only completed prior years are used, so the band never includes the value it is compared with.
    Dates without a full ``years`` of history get NaN.
    """
    s = series.dropna()
    if s.empty:
        return pd.DataFrame(columns=["avg", "min", "max"], index=series.index, dtype=float)
    frame = pd.DataFrame({"year": s.index.year, "day": _season_day(s.index), "value": s.to_numpy()})
    table = frame.pivot_table(index="day", columns="year", values="value", aggfunc="mean")

    idx = series.index
    days = _season_day(idx)
    out = np.full((len(idx), 3), np.nan)
    for year in np.unique(idx.year):
        prior = [y for y in range(year - years, year) if y in table.columns]
        if len(prior) < years:
            continue
        window = table[prior]
        stats = pd.DataFrame({"avg": window.mean(axis=1), "min": window.min(axis=1), "max": window.max(axis=1)})
        mask = idx.year == year
        out[mask] = stats.reindex(days[mask]).to_numpy()
    return pd.DataFrame(out, index=idx, columns=["avg", "min", "max"])


def rolling_zscore(series: pd.Series, window: int = 30, min_periods: int | None = None, exclude_current: bool = True) -> pd.Series:
    """Rolling Z-score of ``series`` against its trailing ``window``-day mean and std.

    With ``exclude_current`` the baseline is the *previous* ``window`` observations, so a shock is
    not partly absorbed into its own benchmark.
    """
    min_periods = min_periods or max(2, int(window * 2 / 3))
    base = series.shift(1) if exclude_current else series
    roll = base.rolling(window, min_periods=min_periods)
    std = roll.std().replace(0, np.nan)
    return ((series - roll.mean()) / std).rename(f"{series.name}_z" if series.name else None)


def add_zscores(df: pd.DataFrame, columns: list[str], window: int = 30) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out:
            out[f"{col}_z"] = rolling_zscore(out[col], window)
    return out


def detect_signals(df: pd.DataFrame, threshold: float = 1.0, css_threshold: float = 2.0) -> pd.DataFrame:
    """Rule-based market signals on a frame that already carries Z-score columns.

    * ``bullish_power``: storage deficit vs 5y average is unusually wide *and* wind is unusually low
      (both Z < -threshold) -> tight system, upward pressure on power prices.
    * ``bearish_power``: the mirror image (both Z > +threshold).
    * ``css_anomaly``: |CSS Z| >= css_threshold -> CSS far from its recent range; a candidate
      mispricing between power, gas and carbon.
    * ``signal_score``: continuous tightness score, positive = bullish power.
    """
    out = df.copy()
    zs = out.get("storage_vs_5y_pp_z", pd.Series(np.nan, index=out.index))
    zw = out.get("wind_mw_z", pd.Series(np.nan, index=out.index))
    zc = out.get("css_z", pd.Series(np.nan, index=out.index))

    out["bullish_power"] = (zs < -threshold) & (zw < -threshold)
    out["bearish_power"] = (zs > threshold) & (zw > threshold)
    out["css_anomaly"] = zc.abs() >= css_threshold
    out["signal_score"] = -(zs.fillna(0) + zw.fillna(0)) / 2
    out.loc[zs.isna() & zw.isna(), "signal_score"] = np.nan
    out["signal"] = np.select(
        [out["bullish_power"], out["bearish_power"], out["css_anomaly"] & (zc > 0), out["css_anomaly"] & (zc < 0)],
        ["Bullish power", "Bearish power", "CSS rich", "CSS cheap"],
        default="",
    )
    return out
