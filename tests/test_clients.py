from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from gasdash.agsi import AGSIClient
from gasdash.entsoe import ENTSOEClient, parse_timeseries
from gasdash.pipeline import daily_power

PRICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <Period>
      <timeInterval><start>2024-01-01T23:00Z</start><end>2024-01-02T03:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>50.0</price.amount></Point>
      <Point><position>2</position><price.amount>60.0</price.amount></Point>
      <Point><position>4</position><price.amount>80.0</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""

GEN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries><MktPSRType><psrType>B19</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2024-01-01T00:00Z</start><end>2024-01-01T00:30Z</end></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>100</quantity></Point>
      <Point><position>2</position><quantity>110</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries><MktPSRType><psrType>B19</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2024-01-01T00:00Z</start><end>2024-01-01T00:30Z</end></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>5</quantity></Point>
      <Point><position>2</position><quantity>5</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""

NO_DATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">
  <Reason><code>999</code><text>No matching data found for Data item ...</text></Reason>
</Acknowledgement_MarketDocument>"""


def test_parse_prices_forward_fills_a03_curve():
    s = parse_timeseries(PRICE_XML, "price.amount")
    assert len(s) == 4
    assert s.index[0] == pd.Timestamp("2024-01-01T23:00Z")
    assert s.tolist() == [50.0, 60.0, 60.0, 80.0]


def test_parse_generation_sums_series():
    s = parse_timeseries(GEN_XML, "quantity")
    assert s.tolist() == [105.0, 115.0]


def test_parse_no_data_ack_is_empty():
    assert parse_timeseries(NO_DATA_XML, "price.amount").empty


def test_daily_power_uses_local_calendar_day():
    idx = pd.date_range("2024-01-01T23:00Z", periods=24, freq="h")  # = 2 Jan 00:00..23:00 CET
    hourly = pd.Series(range(24), index=idx, dtype=float)
    out = daily_power(hourly)
    assert list(out.index) == [pd.Timestamp("2024-01-02")]
    assert out["power_eur_mwh"].iloc[0] == pytest.approx(11.5)
    assert out["power_peak_eur_mwh"].iloc[0] == pytest.approx(sum(range(8, 20)) / 12)


def _response(json=None, text="", status=200):
    r = MagicMock(status_code=status, text=text)
    r.json.return_value = json
    r.raise_for_status.return_value = None
    return r


def test_agsi_client_paginates_and_parses():
    session = MagicMock()
    session.get.side_effect = [
        _response({"last_page": 2, "data": [{"gasDayStart": "2024-01-02", "gasInStorage": "200.5", "full": "80.1",
                                              "workingGasVolume": "250", "injection": "0", "withdrawal": "900", "trend": "-0.3"}]}),
        _response({"last_page": 2, "data": [{"gasDayStart": "2024-01-01", "gasInStorage": "201.4", "full": "80.4",
                                              "workingGasVolume": "250", "injection": "1", "withdrawal": "850", "trend": "-0.2"}]}),
    ]
    df = AGSIClient("key", session=session).storage("DE", date(2024, 1, 1), date(2024, 1, 2))
    assert session.get.call_count == 2
    assert session.get.call_args_list[0].kwargs["headers"] == {"x-key": "key"}
    assert session.get.call_args_list[0].kwargs["params"]["country"] == "de"
    assert df.index.is_monotonic_increasing
    assert df["full_pct"].tolist() == [80.4, 80.1]


def test_entsoe_client_chunks_long_ranges():
    session = MagicMock()
    session.get.return_value = _response(text=PRICE_XML)
    client = ENTSOEClient("token", session=session)
    client.day_ahead_prices("10Y1001A1001A82H", date(2023, 1, 1), date(2024, 6, 1))
    assert session.get.call_count == 2
    params = session.get.call_args_list[0].kwargs["params"]
    assert params["documentType"] == "A44" and params["securityToken"] == "token"
