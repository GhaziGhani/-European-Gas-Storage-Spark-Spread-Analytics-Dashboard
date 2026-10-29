"""Plotly figures for the dashboard. Each chart has a single y-axis; related measures are
stacked as small multiples rather than overlaid on twin axes."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .spreads import css_by_efficiency

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
GRAY = "#8a8984"
BAND = "rgba(138,137,132,0.18)"
FAN = "rgba(42,120,214,0.15)"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
NEG_BLUE = "#2a78d6"
POS_RED = "#e34948"

LAYOUT = dict(
    hovermode="x unified",
    margin=dict(l=10, r=10, t=50, b=10),
    legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="left", x=0),
    xaxis=dict(showgrid=False),
    yaxis=dict(gridcolor="rgba(128,128,128,0.15)", zeroline=False),
)


def storage_vs_history(df: pd.DataFrame, title: str = "Storage fill vs 5-year history") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["storage_5y_max"], line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=df.index, y=df["storage_5y_min"], fill="tonexty", fillcolor=BAND, line=dict(width=0),
                             name="5y min–max", hovertemplate="%{y:.1f}%"))
    fig.add_trace(go.Scatter(x=df.index, y=df["storage_5y_avg"], name="5y average",
                             line=dict(color=GRAY, width=2, dash="dash"), hovertemplate="%{y:.1f}%"))
    fig.add_trace(go.Scatter(x=df.index, y=df["full_pct"], name="Current", line=dict(color=BLUE, width=2),
                             hovertemplate="%{y:.1f}%"))
    fig.update_layout(**LAYOUT, title=title, yaxis_title="% full", yaxis_range=[0, 100])
    return fig


def storage_deviation(df: pd.DataFrame) -> go.Figure:
    dev = df["storage_vs_5y_pp"]
    colors = [POS_RED if v < 0 else NEG_BLUE for v in dev.fillna(0)]
    fig = go.Figure(go.Bar(x=df.index, y=dev, marker_color=colors, marker_line_width=0, name="vs 5y avg",
                           hovertemplate="%{y:+.1f} pp<extra></extra>"))
    fig.update_layout(**LAYOUT, title="Storage surplus (+) / deficit (−) vs 5-year average", yaxis_title="pp", showlegend=False)
    return fig


def spread_curves(df: pd.DataFrame, efficiencies, efficiency: float, emission_factor: float, vom: float) -> go.Figure:
    grid = css_by_efficiency(df, efficiencies, emission_factor, vom)
    lo, hi = grid.min(axis=1), grid.max(axis=1)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=hi, line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=df.index, y=lo, fill="tonexty", fillcolor=FAN, line=dict(width=0),
                             name=f"CSS η {min(efficiencies):.2f}–{max(efficiencies):.2f}", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=df.index, y=df["spark_spread"], name=f"Spark spread η={efficiency:.2f}",
                             line=dict(color=ORANGE, width=2), hovertemplate="%{y:.2f} €/MWh"))
    fig.add_trace(go.Scatter(x=df.index, y=df["css"], name=f"Clean spark spread η={efficiency:.2f}",
                             line=dict(color=BLUE, width=2), hovertemplate="%{y:.2f} €/MWh"))
    if "css_peak" in df and df["css_peak"].notna().any():
        fig.add_trace(go.Scatter(x=df.index, y=df["css_peak"], name="CSS peakload",
                                 line=dict(color=AQUA, width=2), hovertemplate="%{y:.2f} €/MWh", visible="legendonly"))
    fig.add_hline(y=0, line=dict(color=GRAY, width=1))
    fig.update_layout(**LAYOUT, title="Spark & clean spark spreads", yaxis_title="€/MWh_el")
    return fig


def price_stack(df: pd.DataFrame) -> go.Figure:
    """Power price vs. the cost build-up of the marginal gas plant (fuel + carbon)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["fuel_cost"], name="Fuel cost (gas/η)", stackgroup="cost",
                             line=dict(color=ORANGE, width=0.5), hovertemplate="%{y:.2f} €/MWh"))
    fig.add_trace(go.Scatter(x=df.index, y=df["carbon_cost"], name="Carbon cost (EF·CO₂/η)", stackgroup="cost",
                             line=dict(color=AQUA, width=0.5), hovertemplate="%{y:.2f} €/MWh"))
    fig.add_trace(go.Scatter(x=df.index, y=df["power_eur_mwh"], name="Day-ahead baseload",
                             line=dict(color=BLUE, width=2), hovertemplate="%{y:.2f} €/MWh"))
    fig.update_layout(**LAYOUT, title="Power price vs CCGT short-run cost", yaxis_title="€/MWh_el")
    return fig


def breakeven(df: pd.DataFrame, efficiencies) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df.index, y=df["breakeven_efficiency"] * 100, name="Break-even η",
                               line=dict(color=BLUE, width=2), hovertemplate="%{y:.1f}%<extra></extra>"))
    fig.add_hrect(y0=min(efficiencies) * 100, y1=max(efficiencies) * 100, fillcolor=BAND, line_width=0,
                  annotation_text="typical CCGT fleet", annotation_position="top left")
    fig.update_layout(**LAYOUT, title="Break-even plant efficiency (lower = power rich vs fuel)",
                      yaxis_title="η %", showlegend=False)
    return fig


def zscore_panels(df: pd.DataFrame, threshold: float, css_threshold: float) -> go.Figure:
    panels = [
        ("storage_vs_5y_pp_z", "Storage vs 5y (Z)", threshold),
        ("wind_mw_z", "Wind output (Z)", threshold),
        ("css_z", "Clean spark spread (Z)", css_threshold),
    ]
    panels = [p for p in panels if p[0] in df]
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[p[1] for p in panels])
    for row, (col, label, thr) in enumerate(panels, start=1):
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=label, line=dict(color=BLUE, width=2),
                                 hovertemplate="%{y:+.2f}σ", showlegend=False), row=row, col=1)
        for y in (thr, -thr):
            fig.add_hline(y=y, line=dict(color=GRAY, width=1, dash="dot"), row=row, col=1)

    bull = df[df["bullish_power"]]
    bear = df[df["bearish_power"]]
    for frame, color, symbol, name in ((bull, CRITICAL, "triangle-up", "Bullish power"),
                                       (bear, GOOD, "triangle-down", "Bearish power")):
        if not frame.empty:
            fig.add_trace(go.Scatter(x=frame.index, y=frame[panels[0][0]], mode="markers", name=name,
                                     marker=dict(color=color, size=10, symbol=symbol, line=dict(width=2, color="white"))),
                          row=1, col=1)
    if "css_z" in df:
        anomalies = df[df["css_anomaly"]]
        if not anomalies.empty:
            fig.add_trace(go.Scatter(x=anomalies.index, y=anomalies["css_z"], mode="markers", name="CSS anomaly",
                                     marker=dict(color=ORANGE, size=9, symbol="diamond", line=dict(width=2, color="white"))),
                          row=len(panels), col=1)
    fig.update_layout(**{k: v for k, v in LAYOUT.items() if k not in ("xaxis", "yaxis")},
                      height=220 * len(panels) + 60, title="Rolling Z-scores & detected signals")
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    return fig


def wind(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df.index, y=df["wind_mw"] / 1000, name="Wind", line=dict(color=AQUA, width=2),
                               hovertemplate="%{y:.1f} GW<extra></extra>"))
    fig.add_trace(go.Scatter(x=df.index, y=df["wind_mw"].rolling(30, min_periods=10).mean() / 1000, name="30-day mean",
                             line=dict(color=GRAY, width=2, dash="dash"), hovertemplate="%{y:.1f} GW<extra></extra>"))
    fig.update_layout(**LAYOUT, title="Daily average wind generation", yaxis_title="GW")
    return fig


def capacity(cap: pd.Series, labels: dict[str, str]) -> go.Figure:
    s = cap.rename(index=lambda k: labels.get(k, k)).sort_values()
    fig = go.Figure(go.Bar(x=s.to_numpy() / 1000, y=s.index, orientation="h", marker_color=BLUE,
                           text=[f"{v / 1000:.1f} GW" for v in s], textposition="outside",
                           hovertemplate="%{y}: %{x:.1f} GW<extra></extra>"))
    fig.update_layout(**{**LAYOUT, "hovermode": "closest"}, title="Installed generation capacity", xaxis_title="GW",
                      showlegend=False, height=max(260, 34 * len(s) + 80))
    return fig
