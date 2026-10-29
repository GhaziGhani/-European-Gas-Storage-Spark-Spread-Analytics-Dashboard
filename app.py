"""Streamlit dashboard: European gas storage & clean spark spread analytics.

    streamlit run app.py
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from gasdash import charts
from gasdash.config import (
    BIDDING_ZONES,
    EFFICIENCY_DEFAULT,
    EFFICIENCY_MAX,
    EFFICIENCY_MIN,
    GAS_EMISSION_FACTOR,
    PSR_LABELS,
    api_key,
)
from gasdash.pipeline import Params, analyse, fetch_live
from gasdash import demo
from gasdash.prices import constant_prices, load_price_csv
from gasdash.spreads import efficiency_grid

st.set_page_config(page_title="Gas Storage & Spark Spreads", page_icon="⚡", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Fetching AGSI+ and ENTSO-E data…")
def load_live(country: str, start: date, end: date) -> tuple[pd.DataFrame, pd.Series]:
    return fetch_live(country, start, end)


@st.cache_data
def load_demo(start: date, end: date) -> tuple[pd.DataFrame, pd.Series]:
    return demo.demo_daily(date(start.year - 5, 1, 1), end), demo.demo_capacity()


# ---------------------------------------------------------------- sidebar
st.sidebar.title("⚡ Settings")
have_keys = bool(api_key("GIE_API_KEY") and api_key("ENTSOE_API_KEY"))
source = st.sidebar.radio("Data source", ["Live APIs", "Demo data"], index=0 if have_keys else 1,
                          help="Live mode needs GIE_API_KEY and ENTSOE_API_KEY (env vars or .streamlit/secrets.toml).")
country = st.sidebar.selectbox("Market", sorted(BIDDING_ZONES), index=sorted(BIDDING_ZONES).index("DE"))
end = st.sidebar.date_input("End date", date.today() - timedelta(days=1))
days = st.sidebar.slider("Lookback (days)", 90, 1095, 365, step=15)
start = end - timedelta(days=days)

st.sidebar.subheader("Plant & carbon")
efficiency = st.sidebar.slider("CCGT efficiency η", EFFICIENCY_MIN, EFFICIENCY_MAX, EFFICIENCY_DEFAULT, 0.01)
emission_factor = st.sidebar.number_input("Gas emission factor (tCO₂/MWh_th)", 0.15, 0.25, GAS_EMISSION_FACTOR, 0.001, format="%.3f")
vom = st.sidebar.number_input("Variable O&M (€/MWh_el)", 0.0, 20.0, 0.0, 0.5)

st.sidebar.subheader("Anomaly detection")
window = st.sidebar.slider("Z-score window (days)", 10, 90, 30)
threshold = st.sidebar.slider("Storage / wind Z threshold", 0.5, 3.0, 1.0, 0.1)
css_threshold = st.sidebar.slider("CSS anomaly |Z|", 1.0, 4.0, 2.0, 0.1)

prices = None
if source == "Live APIs":
    st.sidebar.subheader("Gas & EUA prices")
    upload = st.sidebar.file_uploader("Price CSV (date, gas_eur_mwh, co2_eur_t)", type="csv")
    gas_flat = st.sidebar.number_input("Flat TTF if no CSV (€/MWh)", 0.0, 300.0, 35.0, 0.5)
    co2_flat = st.sidebar.number_input("Flat EUA if no CSV (€/t)", 0.0, 200.0, 70.0, 0.5)

# ---------------------------------------------------------------- data
try:
    if source == "Live APIs":
        if not have_keys:
            st.error("Set GIE_API_KEY and ENTSOE_API_KEY to use live data, or switch to demo data.")
            st.stop()
        raw, capacity = load_live(country, start, end)
        prices = load_price_csv(upload) if upload else constant_prices(raw.index, gas_flat, co2_flat)
        raw = raw.join(prices.reindex(raw.index).ffill())
    else:
        raw, capacity = load_demo(start, end)
except Exception as exc:  # surface API problems instead of a stack trace
    st.error(f"Data load failed: {exc}")
    st.stop()

params = Params(efficiency, emission_factor, vom, window, threshold, css_threshold)
df = analyse(raw, params, start)
effs = efficiency_grid()

# ---------------------------------------------------------------- header & KPIs
st.title("European Gas Storage & Clean Spark Spread Analytics")
label = "synthetic demo data" if source == "Demo data" else f"{country} · AGSI+ & ENTSO-E"
st.caption(f"{label} · {start:%d %b %Y} – {end:%d %b %Y} · CSS = P_el − P_gas/η − (EF/η)·P_CO₂ − VOM")

latest = df.dropna(subset=["full_pct"]).iloc[-1] if df["full_pct"].notna().any() else None
priced = df.dropna(subset=["css"]) if "css" in df else df.iloc[0:0]
k1, k2, k3, k4, k5 = st.columns(5)
if latest is not None:
    k1.metric("Storage fill", f"{latest['full_pct']:.1f}%", f"{latest['storage_vs_5y_pp']:+.1f} pp vs 5y avg")
if not priced.empty:
    last = priced.iloc[-1]
    prev = priced["css"].iloc[-8] if len(priced) > 7 else None
    k2.metric(f"CSS η={efficiency:.2f} (€/MWh)", f"{last['css']:.2f}",
              f"{last['css'] - prev:+.2f} w/w" if prev is not None else None)
    k3.metric("Power baseload (€/MWh)", f"{last['power_eur_mwh']:.2f}")
    k4.metric("Break-even η", f"{last['breakeven_efficiency'] * 100:.1f}%")
signal_now = df["signal"].iloc[-1] if len(df) else ""
icons = {"Bullish power": "🔺", "Bearish power": "🔻", "CSS rich": "◆", "CSS cheap": "◇"}
k5.metric("Signal today", f"{icons.get(signal_now, '')} {signal_now or 'None'}",
          f"score {df['signal_score'].iloc[-1]:+.2f}" if pd.notna(df["signal_score"].iloc[-1]) else None,
          delta_color="off")

# ---------------------------------------------------------------- tabs
tab_storage, tab_spread, tab_signals, tab_power, tab_data, tab_method = st.tabs(
    ["🛢️ Storage", "📈 Spark spreads", "🚨 Anomalies", "🌬️ Wind & capacity", "📋 Data", "📐 Methodology"]
)

with tab_storage:
    st.plotly_chart(charts.storage_vs_history(df), width="stretch")
    st.plotly_chart(charts.storage_deviation(df), width="stretch")

with tab_spread:
    if priced.empty:
        st.info("No price data for this window.")
    else:
        st.plotly_chart(charts.spread_curves(priced, effs, efficiency, emission_factor, vom), width="stretch")
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.price_stack(priced), width="stretch")
        c2.plotly_chart(charts.breakeven(priced, effs), width="stretch")
        stats = priced[["spark_spread", "css", "css_peak"] if "css_peak" in priced else ["spark_spread", "css"]]
        st.markdown("**Spread statistics (€/MWh)**")
        st.dataframe(stats.describe().T.round(2), width="stretch")

with tab_signals:
    st.plotly_chart(charts.zscore_panels(df, threshold, css_threshold), width="stretch")
    events = df.loc[df["signal"] != "", ["signal", "signal_score", "full_pct", "storage_vs_5y_pp",
                                         "storage_vs_5y_pp_z", "wind_mw_z", "css", "css_z"]]
    events = events.drop(columns=[c for c in ("css", "css_z") if c not in df])
    st.markdown(f"**{len(events)} signal days** — bullish = storage deficit and low wind both beyond −{threshold:.1f}σ; "
                f"CSS rich/cheap = |Z| ≥ {css_threshold:.1f}.")
    st.dataframe(events.sort_index(ascending=False).round(2), width="stretch")

with tab_power:
    st.plotly_chart(charts.wind(df), width="stretch")
    if "wind_load_factor" in df:
        st.caption(f"Average wind load factor in window: {df['wind_load_factor'].mean() * 100:.1f}%")
    if capacity is not None and not capacity.empty:
        st.plotly_chart(charts.capacity(capacity, PSR_LABELS), width="stretch")

with tab_data:
    st.dataframe(df.round(3), width="stretch")
    st.download_button("Download CSV", df.to_csv().encode(), f"gas_spark_{country}_{end}.csv", "text/csv")

with tab_method:
    st.markdown(
        r"""
### Clean Spark Spread
$$CSS_t = P^{el}_t - \frac{P^{gas}_t}{\eta} - \frac{EF_{gas}}{\eta}\,P^{CO_2}_t - VOM$$

* $\eta$ — CCGT electrical efficiency (0.50–0.58 fan, selected value as the main line)
* $EF_{gas}$ — 0.202 tCO₂/MWh_th (IPCC default 56.1 tCO₂/TJ)
* Break-even efficiency $\eta^* = (P^{gas} + EF\cdot P^{CO_2}) / (P^{el} - VOM)$: the least efficient
  gas plant that still covers fuel and carbon.

### Storage vs 5-year history
For every gas day, the mean / min / max fill level on the same calendar day of the **five previous
complete years** (29 Feb shares 28 Feb's slot). The deviation in percentage points feeds the signal model.

### Rolling Z-scores
$$Z_t = \frac{x_t - \mu_{t-w..t-1}}{\sigma_{t-w..t-1}}$$
with a trailing $w$-day window that excludes today, so a shock is not absorbed into its own baseline.

### Signals
| Signal | Rule | Reading |
|---|---|---|
| 🔺 Bullish power | Z(storage vs 5y) < −k **and** Z(wind) < −k | tight gas + low renewables ⇒ gas at the margin more often |
| 🔻 Bearish power | both > +k | ample gas + strong wind |
| ◆ CSS rich / ◇ cheap | \|Z(CSS)\| ≥ k₂ | spread far outside its recent range — candidate mispricing |

Signals are screening tools, not trading advice.
"""
    )
