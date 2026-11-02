"""Qld WMIP: parsing its traces, and the BoM app taking level and flow from it."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from bom import wmip
from bom.app_config import BomConfig
from bom.application import wmip_slot
from bom.hcs import Reading
from bom.wdo import Flow
from test_hcs import HCS, gauge_record, make_app  # noqa: F401 (autouse WDO history stub)
from test_obs import OBS_XML


def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
T1, T2 = NOW - timedelta(minutes=90), NOW - timedelta(minutes=30)

TRACE = {
    "error_num": 0,
    "return": {
        "traces": [
            {
                "error_num": 0,
                "site": "120002D",
                "site_details": {"timezone": "10.0", "name": "Burdekin River at Sellheim"},
                "quality_codes": {"130": "Not coded value", "255": ""},
                "trace": [
                    {"v": "1.416", "t": 20261030110000, "q": 130},
                    {"v": "1.414", "t": 20261030120000, "q": 130},
                    {"v": "0.000", "t": 20261030130000, "q": 255},
                ],
            }
        ]
    },
}


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_parse_trace_reads_local_times_and_skips_missing() -> None:
    points = wmip._points(wmip.parse_trace(TRACE))
    # 11:00 and 12:00 AEST; the missing 13:00 value is left out.
    assert points == [(utc("2026-10-30T01:00:00"), 1.416), (utc("2026-10-30T02:00:00"), 1.414)]


def test_service_errors_raise() -> None:
    bad_site = {"error_num": 0, "return": {"traces": [{"error_num": 20, "error_msg": "Invalid station/datasource"}]}}
    with pytest.raises(wmip.WmipError, match="Invalid station"):
        wmip.parse_trace(bad_site)
    with pytest.raises(wmip.WmipError):
        wmip.parse_trace({"error_num": 1, "error_msg": "Bad request"})


def test_gauge_numbers_are_checked_before_sending() -> None:
    assert wmip.valid_gauge("120002D") and wmip.valid_gauge("119003A") and wmip.valid_gauge("416201")
    assert not wmip.valid_gauge("533075 ") and not wmip.valid_gauge("12002D")
    with patch("urllib.request.urlopen") as urlopen, pytest.raises(wmip.WmipError):
        wmip.fetch_levels(wmip.DEFAULT_URL, "Sellheim", NOW, NOW)
    urlopen.assert_not_called()


def test_polling_hour_starts_at_25_past() -> None:
    assert wmip_slot(utc("2026-10-30T02:24:00")) == "2026-10-30T01"
    assert wmip_slot(utc("2026-10-30T02:25:00")) == "2026-10-30T02"


LEVELS = [
    Reading("120002D", "WL", T1, 1.416, "metres", "LGH", None),
    Reading("120002D", "WL", T2, 1.524, "metres", "LGH", None),
]
FLOWS = [Flow(T1, 23.4), Flow(T2, 23.9)]


def qld_app():
    app = make_app()
    app.config = BomConfig()
    app.config._inject_deployment_config(
        {
            "state": "QLD",
            "river_level": {"station_id": "533075"},
            "rainfall": {"station_id": "533075"},
            "weather_station": {"station_id": "034101"},
            "qld_water_monitoring": {"gauge_number": "120002d"},
        }
    )
    return app


def run(app, force=False, files=None, levels=LEVELS, flows=FLOWS):
    with (
        patch("bom.application.download_latest", return_value=files or {}) as download,
        patch("bom.application.find_levels", return_value=("IDQ65323.html", [12.0, 14.0, 15.0])),
        patch("bom.application.fetch_discharge") as wdo,
        patch("bom.wmip.fetch_levels", return_value=levels) as fetch_levels,
        patch("bom.wmip.fetch_flows", return_value=flows) as fetch_flows,
        patch("bom.wmip.fetch_history", return_value=wmip.History({})),
    ):
        asyncio.run(app.refresh(force_wmip=force))
    return download, wdo, fetch_levels, fetch_flows


def history(app) -> dict[int, dict]:
    return {ts: data["bom_1"] for channel, data, ts in app.api.messages if channel == "tag_values"}


def test_level_and_flow_come_from_wmip() -> None:
    app = qld_app()
    download, wdo, fetch_levels, fetch_flows = run(app, files={"IDQ65910_1.hcs": HCS})

    _, site, start, _ = fetch_levels.call_args.args
    assert site == "120002D"
    assert start == pytest.approx(NOW - timedelta(days=7), abs=timedelta(minutes=2))
    assert app.tags.river_level.value == 1.524
    assert app.tags.river_datum.value == "LGH"
    assert app.tags.river_trend.value == "rising"
    assert history(app)[ms(T1)]["river_level"] == 1.416
    # Flood levels still come from the flood-warning gauge's map page.
    assert app.tags.river_flood_class.value == "Below flood level"
    # Flow is live, so Water Data Online isn't asked.
    wdo.assert_not_called()
    assert app.tags.river_flow_time.value == ms(T2)
    assert history(app)[ms(T2)]["river_flow"] == pytest.approx(23.9 * 86.4)
    # The BOM river files aren't fetched; rain and weather still are.
    prefixes = download.call_args.args[4]
    assert "IDQ65911" not in prefixes and "IDQ65900" in prefixes
    assert "river" not in app.tags.status.value
    assert "flow:ML/day" in app.tags.ui_layout.value


def test_wmip_is_asked_once_an_hour() -> None:
    app = qld_app()
    run(app)
    app.api.messages.clear()
    _, _, fetch_levels, _ = run(app, files={"IDQ60920.xml": OBS_XML})
    fetch_levels.assert_not_called()
    # Without new WMIP readings the BOM river files don't count as missing.
    assert "river" not in app.tags.status.value
    assert app.tags.river_level.value == 1.524

    # A deployment or manual run asks straight away, from just before the last reading.
    _, _, fetch_levels, _ = run(app, force=True)
    _, _, start, _ = fetch_levels.call_args.args
    assert start == T2 - timedelta(hours=3)


def test_a_failed_fetch_waits_for_the_next_hour() -> None:
    app = qld_app()
    with (
        patch("bom.application.download_latest", return_value={}),
        patch("bom.application.find_levels", return_value=None),
        patch("bom.wmip.fetch_levels", side_effect=wmip.WmipError("Invalid station/datasource")),
    ):
        asyncio.run(app.refresh())
    assert "WMIP fetch failed: Invalid station/datasource" in app.tags.status.value
    assert app.tags.wmip_checked.value == wmip_slot(datetime.now(timezone.utc))
    _, _, fetch_levels, _ = run(app)
    fetch_levels.assert_not_called()


def test_stale_wmip_readings_warn() -> None:
    app = qld_app()
    old = NOW - timedelta(hours=80)
    run(app, levels=[Reading("120002D", "WL", old, 1.4, "metres", "LGH", None)], flows=[Flow(old, 20.0)])
    assert app.tags.river_level_ok.value is False
    assert app.tags.river_flow_ok.value is False


def test_without_a_gauge_number_wmip_is_never_asked() -> None:
    app = make_app()
    _, _, fetch_levels, fetch_flows = run(app)
    fetch_levels.assert_not_called()
    fetch_flows.assert_not_called()
