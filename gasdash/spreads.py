r"""Clean Spark Spread maths.

For a gas plant with electrical efficiency :math:`\eta`:

.. math::

    CSS = P_{el} - \frac{P_{gas}}{\eta} - \frac{EF_{gas}}{\eta} \cdot P_{CO_2} - VOM

* ``P_el``  power price [EUR/MWh_el]
* ``P_gas`` gas price [EUR/MWh_th]
* ``EF_gas`` emission factor of gas [tCO2/MWh_th] (~0.202)
* ``P_CO2`` EUA price [EUR/tCO2]
* ``VOM``  variable O&M [EUR/MWh_el]

The *break-even efficiency* :math:`\eta^* = (P_{gas} + EF \cdot P_{CO_2}) / (P_{el} - VOM)` is the
least efficient plant that is still in the money; a falling :math:`\eta^*` means power is rich
relative to fuel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EFFICIENCY_MAX, EFFICIENCY_MIN, GAS_EMISSION_FACTOR


def spark_spread(power, gas, efficiency: float):
    """Dirty spark spread (no carbon cost)."""
    _check_efficiency(efficiency)
    return power - gas / efficiency


def clean_spark_spread(power, gas, co2, efficiency: float, emission_factor: float = GAS_EMISSION_FACTOR, vom: float = 0.0):
    _check_efficiency(efficiency)
    return power - gas / efficiency - (emission_factor / efficiency) * co2 - vom


def carbon_cost(co2, efficiency: float, emission_factor: float = GAS_EMISSION_FACTOR):
    """Carbon cost per MWh of electricity."""
    _check_efficiency(efficiency)
    return emission_factor / efficiency * co2


def breakeven_efficiency(power, gas, co2, emission_factor: float = GAS_EMISSION_FACTOR, vom: float = 0.0):
    """Efficiency at which CSS = 0. NaN where the net power price is not positive."""
    net_power = power - vom
    net = np.where(net_power > 0, net_power, np.nan)
    result = (gas + emission_factor * co2) / net
    return pd.Series(result, index=power.index) if isinstance(power, pd.Series) else result


def efficiency_grid(n: int = 5) -> np.ndarray:
    return np.round(np.linspace(EFFICIENCY_MIN, EFFICIENCY_MAX, n), 3)


def css_by_efficiency(df: pd.DataFrame, efficiencies, emission_factor: float = GAS_EMISSION_FACTOR, vom: float = 0.0) -> pd.DataFrame:
    """CSS for each efficiency in ``efficiencies`` (one column per efficiency)."""
    return pd.DataFrame(
        {
            f"css_{eta:.2f}": clean_spark_spread(df["power_eur_mwh"], df["gas_eur_mwh"], df["co2_eur_t"], eta, emission_factor, vom)
            for eta in efficiencies
        },
        index=df.index,
    )


def add_spreads(df: pd.DataFrame, efficiency: float, emission_factor: float = GAS_EMISSION_FACTOR, vom: float = 0.0) -> pd.DataFrame:
    """Append spark spread, CSS, carbon cost and break-even efficiency columns to a daily frame."""
    out = df.copy()
    p, g, c = out["power_eur_mwh"], out["gas_eur_mwh"], out["co2_eur_t"]
    out["fuel_cost"] = g / efficiency
    out["carbon_cost"] = carbon_cost(c, efficiency, emission_factor)
    out["spark_spread"] = spark_spread(p, g, efficiency)
    out["css"] = clean_spark_spread(p, g, c, efficiency, emission_factor, vom)
    out["breakeven_efficiency"] = breakeven_efficiency(p, g, c, emission_factor, vom)
    if "power_peak_eur_mwh" in out:
        out["css_peak"] = clean_spark_spread(out["power_peak_eur_mwh"], g, c, efficiency, emission_factor, vom)
    return out


def _check_efficiency(efficiency: float) -> None:
    if not 0 < efficiency <= 1:
        raise ValueError(f"efficiency must be in (0, 1], got {efficiency}")
