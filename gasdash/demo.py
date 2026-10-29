"""Deterministic synthetic market data so the dashboard and tests run without API keys.

The generator is not a forecast model; it only reproduces the stylised facts the analytics
look for (seasonal storage cycle, winter-heavy wind, power priced off the gas plant at the margin
with a wind merit-order effect, and occasional supply shocks).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import GAS_EMISSION_FACTOR, PSR_GAS, PSR_SOLAR, PSR_WIND_OFFSHORE, PSR_WIND_ONSHORE


def _ar1(rng: np.random.Generator, n: int, phi: float, sigma: float) -> np.ndarray:
    x = np.zeros(n)
    eps = rng.normal(0, sigma, n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def demo_daily(start: date, end: date, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="D", name="date")
    n = len(idx)
    doy = idx.dayofyear.to_numpy()

    # Storage: injection Apr-Oct, withdrawal Nov-Mar, with a slow, persistent deviation.
    seasonal = 57 - 33 * np.cos(2 * np.pi * (doy - 45) / 365.25)
    offset = _ar1(rng, n, 0.998, 0.35)
    full = np.clip(seasonal + offset, 5, 99)

    # Wind: winter-heavy load factor with weather-system persistence.
    capacity = 70_000 + 3_000 * (idx.year - idx.year.min()).to_numpy()
    lf = np.clip(0.24 + 0.08 * np.cos(2 * np.pi * (doy - 15) / 365.25) + _ar1(rng, n, 0.75, 0.07), 0.03, 0.75)
    wind = lf * capacity

    # Fuel and carbon: log random walks, gas reacting to storage tightness.
    tightness = (seasonal - full) / 10
    gas = np.clip(32 * np.exp(np.cumsum(rng.normal(0, 0.018, n)) * 0.6) + 4 * tightness, 12, None)
    co2 = np.clip(72 * np.exp(np.cumsum(rng.normal(0, 0.012, n)) * 0.5), 40, None)

    # Power: marginal CCGT (eta ~0.53) plus scarcity premium, minus a wind merit-order effect.
    marginal = (gas + GAS_EMISSION_FACTOR * co2) / 0.53
    wind_dev = (lf - lf.mean()) / lf.std()
    power = marginal + 6 - 9 * wind_dev + rng.normal(0, 5, n)
    weekend = idx.dayofweek.to_numpy() >= 5
    power[weekend] -= 12
    peak = power * 1.12 + rng.normal(0, 3, n)

    return pd.DataFrame(
        {
            "full_pct": full,
            "gas_in_storage_twh": full / 100 * 250,
            "injection_gwh": np.clip(np.gradient(full), 0, None) * 2_500,
            "withdrawal_gwh": np.clip(-np.gradient(full), 0, None) * 2_500,
            "power_eur_mwh": power,
            "power_peak_eur_mwh": peak,
            "wind_mw": wind,
            "wind_capacity_mw": capacity.astype(float),
            "gas_eur_mwh": gas,
            "co2_eur_t": co2,
        },
        index=idx,
    )


def demo_capacity() -> pd.Series:
    return pd.Series(
        {PSR_GAS: 33_500.0, PSR_WIND_ONSHORE: 63_000.0, PSR_WIND_OFFSHORE: 9_200.0, PSR_SOLAR: 99_000.0},
        name="installed_mw",
    )
