"""Gas (TTF) and carbon (EUA) price inputs.

There is no free official API for TTF or EUA settlement prices, so prices come from
a user-supplied CSV (e.g. exported from ICE/EEX/your broker) with the columns
``date, gas_eur_mwh, co2_eur_t``. Missing days are forward-filled.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO

import pandas as pd

REQUIRED = ["gas_eur_mwh", "co2_eur_t"]


def load_price_csv(source: str | Path | IO) -> pd.DataFrame:
    df = pd.read_csv(source)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"date", *REQUIRED} - set(df.columns)
    if missing:
        raise ValueError(f"price CSV is missing columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    out = df.set_index("date")[REQUIRED].apply(pd.to_numeric, errors="coerce").sort_index()
    return out.asfreq("D").ffill()


def constant_prices(index: pd.DatetimeIndex, gas: float, co2: float) -> pd.DataFrame:
    return pd.DataFrame({"gas_eur_mwh": gas, "co2_eur_t": co2}, index=index)
