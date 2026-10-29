"""Static configuration: API endpoints, bidding-zone codes and physical constants."""

from __future__ import annotations

import os

AGSI_URL = "https://agsi.gie.eu/api"
ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"

# IPCC default emission factor for natural gas: 56.1 tCO2/TJ = 0.20196 tCO2/MWh (thermal, NCV).
GAS_EMISSION_FACTOR = 0.202

# Typical CCGT efficiency band (LHV) used for the CSS fan chart.
EFFICIENCY_MIN = 0.50
EFFICIENCY_MAX = 0.58
EFFICIENCY_DEFAULT = 0.55

# Country -> ENTSO-E bidding zone EIC used for day-ahead prices and generation.
BIDDING_ZONES: dict[str, str] = {
    "DE": "10Y1001A1001A82H",  # DE-LU
    "FR": "10YFR-RTE------C",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
    "AT": "10YAT-APG------L",
    "ES": "10YES-REE------0",
    "IT": "10Y1001A1001A73I",  # IT-North
    "PL": "10YPL-AREA-----S",
}

# ENTSO-E production types (psrType).
PSR_WIND_OFFSHORE = "B18"
PSR_WIND_ONSHORE = "B19"
PSR_SOLAR = "B16"
PSR_GAS = "B04"


def api_key(name: str) -> str | None:
    """Read an API key from the environment, falling back to Streamlit secrets."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)  # type: ignore[no-any-return]
    except Exception:
        return None


PSR_LABELS: dict[str, str] = {
    "B01": "Biomass", "B02": "Lignite", "B03": "Coal-derived gas", "B04": "Fossil gas", "B05": "Hard coal",
    "B06": "Oil", "B09": "Geothermal", "B10": "Hydro pumped storage", "B11": "Hydro run-of-river",
    "B12": "Hydro reservoir", "B14": "Nuclear", "B15": "Other renewable", "B16": "Solar", "B17": "Waste",
    "B18": "Wind offshore", "B19": "Wind onshore", "B20": "Other", "B25": "Energy storage",
}
