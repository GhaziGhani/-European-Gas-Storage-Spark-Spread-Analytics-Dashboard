"""Client for the ENTSO-E Transparency Platform REST API.

Request a security token by e-mailing transparency@entsoe.eu after registering at
https://transparency.entsoe.eu. Responses are IEC 62325 XML documents.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd
import requests

from .config import ENTSOE_URL, PSR_WIND_OFFSHORE, PSR_WIND_ONSHORE

RESOLUTIONS = {"PT15M": "15min", "PT30M": "30min", "PT60M": "60min", "P1D": "1D", "P1Y": "365D"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _iter(el: ET.Element, name: str):
    return (c for c in el.iter() if _local(c.tag) == name)


def parse_timeseries(xml_text: str, value_tag: str) -> pd.Series:
    """Flatten every TimeSeries/Period/Point in an ENTSO-E document into one UTC series.

    Handles curve type A03 (positions omitted when unchanged) by forward-filling
    within each period.
    """
    root = ET.fromstring(xml_text)
    if _local(root.tag) == "Acknowledgement_MarketDocument":
        reason = next((r.text for r in _iter(root, "text")), "no data")
        if "No matching data" in (reason or ""):
            return pd.Series(dtype=float)
        raise ValueError(f"ENTSO-E error: {reason}")

    chunks: list[pd.Series] = []
    for period in _iter(root, "Period"):
        interval = _child(period, "timeInterval")
        start = pd.Timestamp(_child(interval, "start").text)  # type: ignore[union-attr]
        end = pd.Timestamp(_child(interval, "end").text)  # type: ignore[union-attr]
        freq = RESOLUTIONS[_child(period, "resolution").text]  # type: ignore[union-attr]
        index = pd.date_range(start, end, freq=freq, inclusive="left")
        values = pd.Series(float("nan"), index=index)
        for point in _iter(period, "Point"):
            pos = int(_child(point, "position").text)  # type: ignore[union-attr]
            if pos <= len(index):
                values.iloc[pos - 1] = float(_child(point, value_tag).text)  # type: ignore[union-attr]
        chunks.append(values.ffill())

    if not chunks:
        return pd.Series(dtype=float)
    series = pd.concat(chunks).sort_index()
    return series.groupby(level=0).sum() if value_tag == "quantity" else series[~series.index.duplicated()]


class ENTSOEClient:
    def __init__(self, api_key: str | None, session: requests.Session | None = None, timeout: float = 60.0):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, params: dict) -> str:
        params = {"securityToken": self.api_key, **params}
        resp = self.session.get(ENTSOE_URL, params=params, timeout=self.timeout)
        # ENTSO-E returns HTTP 400 with an acknowledgement document for "no data".
        if resp.status_code == 400 and "Acknowledgement" in resp.text:
            return resp.text
        resp.raise_for_status()
        return resp.text

    def _chunked(self, params: dict, start: date, end: date, value_tag: str, max_days: int = 365) -> pd.Series:
        parts = []
        cursor = start
        while cursor < end:
            stop = min(cursor + timedelta(days=max_days), end)
            text = self._get({**params, "periodStart": _fmt(cursor), "periodEnd": _fmt(stop)})
            parts.append(parse_timeseries(text, value_tag))
            cursor = stop
        parts = [p for p in parts if not p.empty]
        if not parts:
            return pd.Series(dtype=float)
        s = pd.concat(parts).sort_index()
        return s[~s.index.duplicated()]

    def day_ahead_prices(self, zone: str, start: date, end: date) -> pd.Series:
        """Day-ahead prices in EUR/MWh (documentType A44)."""
        params = {"documentType": "A44", "in_Domain": zone, "out_Domain": zone}
        return self._chunked(params, start, end, "price.amount").rename("power_eur_mwh")

    def generation(self, zone: str, psr_type: str, start: date, end: date) -> pd.Series:
        """Actual generation per production type in MW (documentType A75)."""
        params = {"documentType": "A75", "processType": "A16", "in_Domain": zone, "psrType": psr_type}
        return self._chunked(params, start, end, "quantity", max_days=90)

    def wind_generation(self, zone: str, start: date, end: date) -> pd.Series:
        onshore = self.generation(zone, PSR_WIND_ONSHORE, start, end)
        offshore = self.generation(zone, PSR_WIND_OFFSHORE, start, end)
        return onshore.add(offshore, fill_value=0).rename("wind_mw")

    def installed_capacity(self, zone: str, year: int) -> pd.Series:
        """Installed generation capacity per production type in MW (documentType A68)."""
        params = {
            "documentType": "A68",
            "processType": "A33",
            "in_Domain": zone,
            "periodStart": f"{year}01010000",
            "periodEnd": f"{year}12310000",
        }
        root = ET.fromstring(self._get(params))
        capacity: dict[str, float] = {}
        for ts in _iter(root, "TimeSeries"):
            psr = next((p.text for p in _iter(ts, "psrType")), None)
            qty = next((p.text for p in _iter(ts, "quantity")), None)
            if psr and qty:
                capacity[psr] = capacity.get(psr, 0.0) + float(qty)
        return pd.Series(capacity, name="installed_mw", dtype=float)


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d0000")
