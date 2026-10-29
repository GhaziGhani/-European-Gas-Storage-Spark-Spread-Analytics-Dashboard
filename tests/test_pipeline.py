from datetime import date

import pandas as pd

from gasdash import charts
from gasdash.pipeline import Params, main, run
from gasdash.prices import load_price_csv
from gasdash.spreads import efficiency_grid


def test_demo_pipeline_end_to_end():
    df, capacity = run("DE", date(2025, 1, 1), date(2025, 12, 31), Params(), demo_mode=True)
    assert df.index.min() == pd.Timestamp("2025-01-01")
    for col in ["storage_5y_avg", "storage_vs_5y_pp", "css", "css_z", "wind_mw_z", "signal", "wind_load_factor"]:
        assert col in df
    assert df["storage_5y_avg"].notna().all()
    assert df["css_z"].notna().mean() > 0.9
    assert not capacity.empty


def test_charts_build_from_demo():
    df, capacity = run("DE", date(2025, 1, 1), date(2025, 6, 30), Params(), demo_mode=True)
    figs = [
        charts.storage_vs_history(df),
        charts.storage_deviation(df),
        charts.spread_curves(df, efficiency_grid(), 0.55, 0.202, 0.0),
        charts.price_stack(df),
        charts.breakeven(df, efficiency_grid()),
        charts.zscore_panels(df, 1.0, 2.0),
        charts.wind(df),
        charts.capacity(capacity, {}),
    ]
    assert all(f.data for f in figs)


def test_cli_writes_outputs(tmp_path):
    main(["--demo", "--days", "120", "--end", "2025-06-30", "--out", str(tmp_path)])
    out = pd.read_csv(tmp_path / "analytics_demo.csv", index_col=0)
    assert len(out) == 121


def test_price_csv_forward_fills(tmp_path):
    p = tmp_path / "prices.csv"
    p.write_text("Date,gas_eur_mwh,co2_eur_t\n2025-01-03,30,70\n2025-01-06,32,71\n")
    df = load_price_csv(p)
    assert len(df) == 4
    assert df.loc["2025-01-05", "gas_eur_mwh"] == 30
