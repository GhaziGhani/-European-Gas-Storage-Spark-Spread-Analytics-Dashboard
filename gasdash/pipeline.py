"""End-to-end pipeline: fetch -> daily frame -> spreads -> Z-scores -> signals.

Run from the command line::

    python -m gasdash.pipeline --country DE --days 365 --out data/
    python -m gasdash.pipeline --demo --out data/
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import analytics, demo, spreads
from .agsi import AGSIClient
from .config import BIDDING_ZONES, EFFICIENCY_DEFAULT, GAS_EMISSION_FACTOR, PSR_WIND_OFFSHORE, PSR_WIND_ONSHORE, api_key
from .entsoe import ENTSOEClient
from .prices import constant_prices, load_price_csv

log = logging.getLogger(__name__)

HISTORY_YEARS = 5
ZSCORE_COLUMNS = ["css", "storage_vs_5y_pp", "wind_mw", "power_eur_mwh", "gas_eur_mwh", "breakeven_efficiency"]
LOCAL_TZ = "Europe/Brussels"


@dataclass
class Params:
    efficiency: float = EFFICIENCY_DEFAULT
    emission_factor: float = GAS_EMISSION_FACTOR
    vom: float = 0.0
    window: int = 30
    threshold: float = 1.0
    css_threshold: float = 2.0


def daily_power(hourly: pd.Series) -> pd.DataFrame:
    """Baseload (all hours) and peakload (weekdays 08-20 local) daily averages."""
    if hourly.empty:
        return pd.DataFrame(columns=["power_eur_mwh", "power_peak_eur_mwh"], dtype=float)
    local = hourly.tz_convert(LOCAL_TZ) if hourly.index.tz is not None else hourly
    day = local.index.tz_localize(None).normalize()
    base = local.groupby(day).mean()
    peak_mask = (local.index.dayofweek < 5) & (local.index.hour >= 8) & (local.index.hour < 20)
    peak = local[peak_mask].groupby(day[peak_mask]).mean()
    out = pd.DataFrame({"power_eur_mwh": base, "power_peak_eur_mwh": peak})
    out.index.name = "date"
    return out


def daily_mean(series: pd.Series, name: str) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float, name=name)
    local = series.tz_convert(LOCAL_TZ) if series.index.tz is not None else series
    return local.groupby(local.index.tz_localize(None).normalize()).mean().rename(name)


def fetch_live(country: str, start: date, end: date, prices: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Fetch storage (with 5y history) and power/wind data, joined on gas day.

    Returns the daily frame and the latest installed capacity per production type.
    """
    zone = BIDDING_ZONES[country]
    agsi = AGSIClient(api_key("GIE_API_KEY"))
    entsoe = ENTSOEClient(api_key("ENTSOE_API_KEY"))

    hist_start = date(start.year - HISTORY_YEARS, 1, 1)
    log.info("AGSI storage %s %s..%s", country, hist_start, end)
    storage = agsi.storage(country, hist_start, end)

    # Extra lead-in so the first Z-scores in the window are defined.
    lead_start = start - timedelta(days=60)
    log.info("ENTSO-E prices / wind %s %s..%s", zone, lead_start, end)
    power = daily_power(entsoe.day_ahead_prices(zone, lead_start, end + timedelta(days=1)))
    wind = daily_mean(entsoe.wind_generation(zone, lead_start, end + timedelta(days=1)), "wind_mw")

    try:
        capacity = entsoe.installed_capacity(zone, end.year)
    except Exception as exc:  # capacity is informative only
        log.warning("installed capacity unavailable: %s", exc)
        capacity = pd.Series(dtype=float, name="installed_mw")

    df = storage.join([power, wind], how="outer")
    wind_cap = capacity.get(PSR_WIND_ONSHORE, 0.0) + capacity.get(PSR_WIND_OFFSHORE, 0.0)
    if wind_cap:
        df["wind_capacity_mw"] = wind_cap
    df = _attach_prices(df, prices)
    return df, capacity


def _attach_prices(df: pd.DataFrame, prices: pd.DataFrame | None) -> pd.DataFrame:
    if prices is None:
        return df
    return df.join(prices.reindex(df.index).ffill(), how="left")


def analyse(df: pd.DataFrame, params: Params, start: date | None = None) -> pd.DataFrame:
    """Add the 5y storage band, spreads, Z-scores and signals; optionally trim to ``start``."""
    out = df.copy()
    band = analytics.historical_band(out["full_pct"], HISTORY_YEARS)
    out["storage_5y_avg"] = band["avg"]
    out["storage_5y_min"] = band["min"]
    out["storage_5y_max"] = band["max"]
    out["storage_vs_5y_pp"] = out["full_pct"] - out["storage_5y_avg"]
    if "wind_capacity_mw" in out:
        out["wind_load_factor"] = out["wind_mw"] / out["wind_capacity_mw"]

    has_prices = {"power_eur_mwh", "gas_eur_mwh", "co2_eur_t"} <= set(out.columns)
    if has_prices:
        out = spreads.add_spreads(out, params.efficiency, params.emission_factor, params.vom)

    out = analytics.add_zscores(out, ZSCORE_COLUMNS, params.window)
    out = analytics.detect_signals(out, params.threshold, params.css_threshold)
    if start is not None:
        out = out.loc[pd.Timestamp(start):]
    return out


def run(country: str, start: date, end: date, params: Params, demo_mode: bool = False,
        price_csv: str | None = None, gas: float | None = None, co2: float | None = None) -> tuple[pd.DataFrame, pd.Series]:
    if demo_mode:
        raw = demo.demo_daily(date(start.year - HISTORY_YEARS, 1, 1), end)
        capacity = demo.demo_capacity()
    else:
        prices = load_price_csv(price_csv) if price_csv else None
        raw, capacity = fetch_live(country, start, end, prices)
        if prices is None and gas is not None and co2 is not None:
            raw = raw.join(constant_prices(raw.index, gas, co2))
    return analyse(raw, params, start), capacity


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country", default="DE", choices=sorted(BIDDING_ZONES))
    parser.add_argument("--days", type=int, default=365, help="analysis window length")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--demo", action="store_true", help="use synthetic data (no API keys needed)")
    parser.add_argument("--prices", help="CSV with date,gas_eur_mwh,co2_eur_t")
    parser.add_argument("--gas", type=float, help="flat TTF price if no CSV [EUR/MWh]")
    parser.add_argument("--co2", type=float, help="flat EUA price if no CSV [EUR/t]")
    parser.add_argument("--efficiency", type=float, default=EFFICIENCY_DEFAULT)
    parser.add_argument("--window", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    start = args.end - timedelta(days=args.days)
    params = Params(efficiency=args.efficiency, window=args.window)
    df, capacity = run(args.country, start, args.end, params, args.demo, args.prices, args.gas, args.co2)

    args.out.mkdir(parents=True, exist_ok=True)
    tag = "demo" if args.demo else args.country
    df.to_csv(args.out / f"analytics_{tag}.csv")
    capacity.to_csv(args.out / f"capacity_{tag}.csv")
    latest = df.dropna(subset=["full_pct"]).iloc[-1]
    log.info("wrote %d rows to %s", len(df), args.out)
    log.info("latest %s: storage %.1f%% (%.1f pp vs 5y), CSS %.2f EUR/MWh, signal=%r",
             latest.name.date(), latest["full_pct"], latest["storage_vs_5y_pp"], latest.get("css", float("nan")), latest["signal"])


if __name__ == "__main__":
    main()
