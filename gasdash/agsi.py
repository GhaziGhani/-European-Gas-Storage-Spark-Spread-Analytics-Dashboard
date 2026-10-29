"""Client for the GIE AGSI+ gas storage transparency API (https://agsi.gie.eu).

A free API key is issued on registration at https://agsi.gie.eu/account.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from .config import AGSI_URL

NUMERIC_FIELDS = {
    "gasInStorage": "gas_in_storage_twh",
    "full": "full_pct",
    "workingGasVolume": "working_gas_volume_twh",
    "injection": "injection_gwh",
    "withdrawal": "withdrawal_gwh",
    "trend": "trend_pct",
}


class AGSIClient:
    def __init__(self, api_key: str | None, session: requests.Session | None = None, timeout: float = 30.0):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, params: dict) -> dict:
        headers = {"x-key": self.api_key} if self.api_key else {}
        resp = self.session.get(AGSI_URL, params=params, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def storage(self, country: str, start: date, end: date, page_size: int = 300) -> pd.DataFrame:
        """Daily aggregated storage for a country code (e.g. ``"DE"``) or ``"EU"``.

        Returns a frame indexed by gas day with the columns in ``NUMERIC_FIELDS``.
        """
        params: dict = {"from": start.isoformat(), "to": end.isoformat(), "size": page_size, "page": 1}
        if country.upper() == "EU":
            params["type"] = "eu"
        else:
            params["country"] = country.lower()

        rows: list[dict] = []
        while True:
            payload = self._get(params)
            rows.extend(payload.get("data", []))
            if params["page"] >= int(payload.get("last_page", 1)):
                break
            params["page"] += 1

        return parse_storage(rows)


def parse_storage(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(NUMERIC_FIELDS.values()), index=pd.DatetimeIndex([], name="date"))
    df = pd.DataFrame(rows)
    out = pd.DataFrame(index=pd.to_datetime(df["gasDayStart"]).rename("date"))
    for src, dst in NUMERIC_FIELDS.items():
        out[dst] = pd.to_numeric(df[src], errors="coerce").to_numpy() if src in df else float("nan")
    return out.sort_index().loc[lambda d: ~d.index.duplicated(keep="last")]
