import asyncio

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bom import handler
from bom.app_config import BomConfig
from bom.app_ui import BomUI
from bom.application import Bom
from bom.floodmap import parse_levels
from bom.ftp import latest_file
from bom.application import flood_ranges
from bom.hcs import flood_class, level_trend, parse_hcs, rain_day
from test_obs import OBS_XML
from bom.wdo import Flow
from bom.flowstats import History

HCS = """# HEADER: File Format: BOM-HCS
# HEADER: Data Fields: IndexNo, SensorType, SensorDataType, SiteIdType, SiteId, ObservationTimestamp, RealValue, Unit, SensorParam1, SensorParam2, Quality, Comment
1,"WL",1,"SR","068212","2026-09-30T03:00:00Z",1.00,"metres","AHD",,1,""
2,"WL",1,"SR","068212","2026-09-30T04:00:00Z",1.05,"metres","AHD",,1,""
3,"RN",6,"SR","068212","2026-09-29T22:45:00Z",0.4,"mm","",900,3,""
4,"RN",6,"SR","068212","2026-09-29T23:00:00Z",1.0,"mm","",900,3,""
5,"RN",6,"SR","068212","2026-09-29T23:15:00Z",0.6,"mm","",900,3,""
6,"RN",6,"SR","999999","2026-09-30T04:00:00Z",,"mm","",900,3,""
"""


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_parse_hcs_skips_headers_and_blank_values() -> None:
    readings = parse_hcs(HCS)
    assert len(readings) == 5
    assert readings[0].kind == "WL" and readings[0].datum == "AHD"
    assert readings[0].time == utc("2026-09-30T03:00:00")
    assert readings[2].period_s == 900


def test_latest_file() -> None:
    names = ["IDN65900_20260930053800.hcs", "IDN65900_20260930055300.hcs", "IDN65910_20260930060000.hcs"]
    assert latest_file(names, "IDN65900") == "IDN65900_20260930055300.hcs"
    assert latest_file(names, "IDQ65900") is None


def test_level_trend() -> None:
    levels = [r for r in parse_hcs(HCS) if r.kind == "WL"]
    assert level_trend(levels) == "rising"
    assert level_trend(levels[:1]) is None


def test_flood_class() -> None:
    levels = [1.7, 2.6, 3.5]
    assert flood_class(1.0, levels) == "Below flood level"
    assert flood_class(2.6, levels) == "Moderate"
    assert flood_class(9.0, levels) == "Major"
    assert flood_class(9.0, [None, None, None]) is None
    assert flood_class(3.0, [None, 2.6, None]) == "Moderate"


MAP_PAGE = (
    '<area onmouseover="javascript:PopupRiver(&quot;Kedron Brook at Toombul (Nudgee Rd)&quot;,'
    "'540548','-27.407','153.074','0.10','Below Flood Level','falling','30-09-2026 16:06:03',"
    "'2.30','2.80','3.20','Click mouse to display plot')\"/>"
    '<area onmouseover="javascript:PopupRiver(&quot;No Levels&quot;,'
    "'999999','-27','153','0.1','No Classification','steady','30-09-2026 16:00:00','','','','x')\"/>"
)


def test_parse_flood_map_levels() -> None:
    assert parse_levels(MAP_PAGE, "540548") == [2.3, 2.8, 3.2]
    assert parse_levels(MAP_PAGE, "999999") == [None, None, None]
    assert parse_levels(MAP_PAGE, "123456") is None


def test_flood_ranges() -> None:
    ranges = flood_ranges([1.7, 2.6, 3.5], lowest=-0.56)
    assert [(r["label"], r["min"], r["max"]) for r in ranges] == [
        ("Below flood level", -1, 1.7),
        ("Minor", 1.7, 2.6),
        ("Moderate", 2.6, 3.5),
        ("Major", 3.5, 4.5),
    ]
    assert flood_ranges([None, None, None], lowest=0) == []


def test_rain_day_rolls_at_9am_local() -> None:
    # 23:00Z = 09:00 AEST, which closes the day that started 9am the day before.
    assert rain_day(utc("2026-09-29T23:00:00"), 10) == "2026-09-29"
    assert rain_day(utc("2026-09-29T23:15:00"), 10) == "2026-09-30"


class FakeApi:
    def __init__(self) -> None:
        self.messages = []
        self.aggregates = []

    async def create_message(self, channel, data, timestamp=None):
        self.messages.append((channel, data, timestamp))

    async def update_channel_aggregate(self, channel, data, replace_keys=None):
        self.aggregates.append((channel, data))


class FakeTag:
    def __init__(self) -> None:
        self.value = None

    async def set(self, value, log=False) -> None:
        self.value = value


def make_app() -> Bom:
    app = Bom()
    app.config = BomConfig()
    app.config._inject_deployment_config(
        {
            "state": "NSW / ACT",
            "river_level": {"station_id": "068212"},
            "rainfall": {"station_id": "068212"},
            "weather_station": {"station_id": "053115"},
            "river_flow": {"station_id": "418001"},
        }
    )
    app.app_key = "bom_1"
    app.api = FakeApi()
    app.tags = type("Tags", (), {n: FakeTag() for n in (
        "river_level", "river_level_time", "river_trend", "river_datum",
        "river_flood_class", "river_ranges", "river_flow", "river_flow_cumec", "river_flow_units", "river_flow_time",
        "river_flow_ranges", "flow_stats", "flow_stats_checked",
        "rain_15min", "rain_last_hour", "rain_since_9am", "rain_time", "rain_period_s", "ui_layout",
        "weather_temp", "weather_apparent_temp", "weather_dew_point", "weather_humidity",
        "weather_pressure", "weather_wind_dir", "weather_wind_speed", "weather_wind_gust",
        "weather_time", "weather_station",
        "status", "rain_day", "flood_map_page", "flood_map_levels", "flood_map_checked",
        "river_level_ok", "river_flow_ok", "rain_ok", "weather_ok", "flood_ok",
    )})()

    async def ping_connection(**kwargs) -> None:
        pass

    app.ping_connection = ping_connection
    return app


FLOWS = [
    Flow(utc("2026-09-29T11:00:00"), 19.149),
    Flow(utc("2026-09-29T12:00:00"), 22.507),
]


@pytest.fixture(autouse=True)
def gauge_record():
    """Stand in for the Water Data Online history: flows 1..2000 m³/s, two days at 1.0 m (minor)."""
    from datetime import date
    start = date(2020, 1, 1)
    mean = {start + timedelta(days=i): float(i + 1) for i in range(2000)}
    level = {d: (1.0 if v in (1990.0, 1995.0) else 0.5) for d, v in mean.items()}
    with patch("bom.application.fetch_history", return_value=History(mean, dict(mean), level)) as fetch:
        yield fetch


def test_refresh_records_history_and_totals(gauge_record) -> None:
    app = make_app()
    with (
        patch(
            "bom.application.download_latest",
            return_value={"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML},
        ),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS) as fetch,
    ):
        asyncio.run(app.refresh())

    # First run: a week's backfill, from the default service and series.
    url, station, series, start, end = fetch.call_args.args
    assert (url, station, series) == ("https://www.bom.gov.au/waterdata/services", "418001", "Pat4_C_B_1_HourlyMean")
    assert timedelta(days=6, hours=23) < end - start < timedelta(days=7, hours=2)
    assert app.tags.river_flow.value == pytest.approx(22.507 * 86.4)  # ML/day by default
    # The level and rain fixtures are well past their 6 h / 3 h limits, and 1.05 m is a Minor flood.
    assert (app.tags.river_level_ok.value, app.tags.rain_ok.value) == (False, False)
    assert app.tags.flood_ok.value is False
    assert app.tags.river_flow_units.value == "ML/day"
    assert app.tags.river_flow_time.value == int(utc("2026-09-29T12:00:00").timestamp() * 1000)
    # Flow bands from the gauge's record, in the display units: p10 / p90 / p99, and the minor flood flow.
    assert app.tags.flow_stats.value == {"low": 201.0, "high": 1800.0, "very_high": 1980.0, "minor": 1992.5, "max": 2000.0}
    assert [(b["label"], b["min"]) for b in app.tags.river_flow_ranges.value] == [
        ("Low", 0), ("Normal", 201.0 * 86.4), ("High", 1800.0 * 86.4), ("Very High", 1980.0 * 86.4), ("Minor Flood", 1992.5 * 86.4)
    ]
    assert app.tags.flow_stats_checked.value == datetime.now(timezone.utc).strftime("%Y-%m") + "/2"

    assert app.tags.status.value == "OK"
    assert app.tags.weather_station.value == "MOREE AERO"
    assert app.tags.weather_temp.value == 20.6
    assert app.tags.weather_wind_dir.value == "N"
    assert app.tags.weather_time.value == int(utc("2026-09-30T23:40:00").timestamp() * 1000)
    assert app.tags.flood_map_page.value == "IDN65195.html"
    assert app.tags.river_flood_class.value == "Minor"  # 1.05 m vs 1.0 m minor
    assert app.tags.river_level.value == 1.05
    assert app.tags.rain_15min.value == 0.6
    assert app.tags.rain_last_hour.value == 2.0

    history = {ts: data["bom_1"] for _, data, ts in app.api.messages}
    assert all(ch == "tag_values" for ch, _, _ in app.api.messages)
    assert list(history) == sorted(history)
    # 0.4 + 1.0 end the 29th's rain day; 0.6 starts the 30th's.
    assert history[int(utc("2026-09-29T23:00:00").timestamp() * 1000)]["rain_since_9am"] == 1.4
    assert history[int(utc("2026-09-29T23:15:00").timestamp() * 1000)]["rain_since_9am"] == 0.6
    assert history[int(utc("2026-09-29T23:15:00").timestamp() * 1000)]["rain_last_hour"] == 2.0
    weather = history[int(utc("2026-09-30T23:40:00").timestamp() * 1000)]
    assert weather["weather_temp"] == 20.6 and weather["weather_wind_gust"] == 35
    assert history[int(utc("2026-09-29T11:00:00").timestamp() * 1000)]["river_flow"] == pytest.approx(19.149 * 86.4)

    # The first readings and flood levels republish the UI: a radial level
    # gauge and an overview plot of level and 15-minute rain.
    [(channel, data)] = app.api.aggregates
    schema = data["state"]["children"]["bom_1"]["children"]
    assert channel == "ui_state"
    assert schema["river_level"]["form"] == "radialGauge"
    assert list(schema["overview"]["series"]) == [
        "river_level", "rain_15min", "weather_temp", "weather_humidity", "weather_wind_speed", "river_flow"
    ]
    assert all(schema["overview"]["series"][k]["active"] is False for k in ("weather_temp", "weather_humidity", "weather_wind_speed"))
    assert "river_flow" in schema
    assert (schema["river_flow"]["units"], schema["river_flow"]["decPrecision"]) == ("ML/day", 1)
    assert schema["overview"]["series"]["river_flow"]["units"] == "ML/day"
    assert [b["label"] for b in schema["overview"]["series"]["river_flow"]["ranges"]] == ["Low", "Normal", "High", "Very High", "Minor Flood"]
    assert schema["river_flow"]["ranges"] == "$tag.app().river_flow_ranges:array:[]"
    assert schema["overview"]["series"]["river_flow"]["active"] is True
    # Flow sits directly under the level; the flood class is kept but hidden.
    order = sorted(schema, key=lambda k: schema[k]["position"])
    assert all(schema[k]["type"] == "uiWarningIndicator" for k in order[:5])  # warnings first
    assert order[5:8] == ["overview", "river_level", "river_flow"]
    assert schema["flood_class"]["hidden"] is True
    assert schema["river_level_warning"]["hidden"] == "$tag.app().river_level_ok:boolean:true"
    assert schema["flood_warning"]["type"] == "uiWarningIndicator"
    assert schema["flood_warning"]["hidden"] == "$tag.app().flood_ok:boolean:true"
    # All the reading times sit together in Details.
    assert "river_reading" not in schema and "rain_as_at" not in schema
    assert list(schema["details"]["children"])[:4] == ["river_level_as_at", "river_flow_as_at", "rain_as_at", "weather_as_at"]
    assert [r["label"] for r in schema["rain_since_9am"]["ranges"]] == ["Light", "Moderate", "Heavy", "Very Heavy", "Extreme"]
    weather = schema["weather"]["children"]
    assert all("ranges" in weather[k] for k in ("temperature", "feels_like", "humidity", "dew_point", "pressure", "wind_speed", "wind_gust"))
    # The plot gets the flood bands literally (it cannot resolve a tag reference there).
    bands = schema["overview"]["series"]["river_level"]["ranges"]
    assert [(b["label"], b["min"], b["max"]) for b in bands] == [
        ("Below flood level", 0, 1.0), ("Minor", 1.0, 2.0), ("Moderate", 2.0, 3.0), ("Major", 3.0, 4.0)
    ]
    assert schema["overview"]["defaultRangeView"] == "zone"
    assert app.tags.ui_layout.value.startswith("river,radial:")
    assert "temperature" in schema["weather"]["children"]

    # A second run over the same file writes nothing new.
    app.api.messages.clear()
    with (
        patch(
            "bom.application.download_latest",
            return_value={"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML},
        ),
        patch("bom.application.find_levels") as find,
        patch("bom.application.fetch_discharge", return_value=FLOWS) as fetch,
    ):
        asyncio.run(app.refresh())
    find.assert_not_called()  # already looked up today
    assert app.api.messages == []
    # Later runs ask only for flow since the last recorded point.
    assert fetch.call_args.args[3] == utc("2026-09-29T12:00:00")
    assert gauge_record.call_count == 1  # the record is read once a month, not every run
    assert len(app.api.aggregates) == 1  # layout unchanged, so not republished


def test_manual_flood_levels_only_when_chosen() -> None:
    app = make_app()
    levels = {"minor_flood_level": 1.0, "moderate_flood_level": 2.0, "major_flood_level": 3.0}
    with patch("bom.application.find_levels", return_value=("IDN65195.html", [5.0, 6.0, 7.0])):
        app.config._inject_deployment_config(
            {"state": "NSW / ACT", "river_level": {"station_id": "068212", **levels}}
        )
        assert asyncio.run(app.flood_levels("068212", "N")) == [5.0, 6.0, 7.0]

        app = make_app()
        app.config._inject_deployment_config(
            {"state": "NSW / ACT", "river_level": {"station_id": "068212", "flood_levels": "Manual", **levels}}
        )
        assert asyncio.run(app.flood_levels("068212", "N")) == [1.0, 2.0, 3.0]


def test_schemas_and_entry_point() -> None:
    assert "ftp_server" in BomConfig.to_schema()["properties"]
    assert isinstance(BomUI(None, None, None).to_schema(), dict)
    assert handler


def test_weather_section_hidden_without_a_station() -> None:
    app = make_app()
    app.config._inject_deployment_config(
        {"state": "NSW / ACT", "river_level": {"station_id": "068212"}}
    )
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
    ):
        asyncio.run(app.refresh())

    assert app.tags.status.value == "OK"
    assert app.tags.weather_time.value is None
    [(_, data)] = app.api.aggregates
    schema = data["state"]["children"]["bom_1"]["children"]
    assert "weather" not in schema
    assert "river_flow" not in schema
    assert "river_flow_as_at" not in schema["details"]["children"]
    assert "river_level_as_at" in schema["details"]["children"]
    assert list(schema["overview"]["series"]) == ["river_level"]


def test_flow_failure_keeps_other_sources() -> None:
    app = make_app()
    with (
        patch(
            "bom.application.download_latest",
            return_value={"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML},
        ),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", side_effect=OSError("timed out")),
    ):
        asyncio.run(app.refresh())

    assert app.tags.status.value == "Flow fetch failed: timed out"
    assert app.tags.river_level.value == 1.05
    assert app.tags.river_flow.value is None


def test_flood_level_change_republishes_the_plot() -> None:
    app = make_app()
    files = {"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML}
    with (
        patch("bom.application.download_latest", return_value=files),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),
    ):
        asyncio.run(app.refresh())
    first = app.tags.ui_layout.value

    # BOM revises the flood levels: the bands change, so the UI goes out again.
    app.tags.flood_map_checked.value = None
    with (
        patch("bom.application.download_latest", return_value=files),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.5, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),
    ):
        asyncio.run(app.refresh())
    assert app.tags.ui_layout.value != first
    assert len(app.api.aggregates) == 2
    bands = app.api.aggregates[-1][1]["state"]["children"]["bom_1"]["children"]["overview"]["series"]["river_level"]["ranges"]
    assert bands[1]["min"] == 1.5


def test_flow_display_units_are_configurable() -> None:
    app = make_app()
    app.config._inject_deployment_config(
        {
            "state": "NSW / ACT",
            "river_level": {"station_id": "068212"},
            "river_flow": {"station_id": "418001", "display_units": "m³/s"},
        }
    )
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),
    ):
        asyncio.run(app.refresh())

    assert app.tags.river_flow.value == 22.507
    assert app.tags.river_flow_units.value == "m³/s"
    assert ",flow:m³/s:" in app.tags.ui_layout.value
    schema = app.api.aggregates[-1][1]["state"]["children"]["bom_1"]["children"]
    assert (schema["river_flow"]["units"], schema["river_flow"]["decPrecision"]) == ("m³/s", 2)


def test_warnings_follow_each_sources_stale_after() -> None:
    app = make_app()
    app.config._inject_deployment_config(
        {
            "state": "NSW / ACT",
            "river_level": {"station_id": "068212", "stale_after_hours": 6},
            "rainfall": {"station_id": "068212"},
            "weather_station": {"station_id": "053115", "stale_after_hours": 1},
            "river_flow": {"station_id": "418001"},
        }
    )
    now = datetime.now(timezone.utc)
    ms = lambda delta: int((now - delta).timestamp() * 1000)
    app.tags.river_level_time.value = ms(timedelta(hours=5))   # within 6 h
    app.tags.rain_time.value = ms(timedelta(hours=4))          # past the 3 h default
    app.tags.weather_time.value = ms(timedelta(minutes=90))    # past the 1 h override
    app.tags.river_flow_time.value = ms(timedelta(days=2))     # within 3 days
    app.tags.river_flood_class.value = "Below flood level"
    asyncio.run(app.update_warnings())
    assert app.tags.river_level_ok.value is True
    assert app.tags.rain_ok.value is False
    assert app.tags.weather_ok.value is False
    assert app.tags.river_flow_ok.value is True
    assert app.tags.flood_ok.value is True

    # No reading at all counts as stale; a source that isn't configured never warns.
    app.tags.river_level_time.value = None
    app.config._inject_deployment_config({"state": "NSW / ACT", "river_level": {"station_id": "068212"}})
    app.tags.river_flood_class.value = "Moderate"
    asyncio.run(app.update_warnings())
    assert app.tags.river_level_ok.value is False
    assert (app.tags.rain_ok.value, app.tags.weather_ok.value, app.tags.river_flow_ok.value) == (True, True, True)
    assert app.tags.flood_ok.value is False


def test_manual_flow_ranges_override_the_record_field_by_field(gauge_record) -> None:
    app = make_app()
    app.config._inject_deployment_config(
        {
            "state": "NSW / ACT",
            "river_level": {"station_id": "068212"},
            "river_flow": {
                "station_id": "418001",
                "display_units": "m³/s",
                "flow_ranges": "Manual",
                "high_flow_above": 1500,
                "major_flood_flow": 2500,
            },
        }
    )
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),
    ):
        asyncio.run(app.refresh())
    assert [(b["label"], b["min"], b["max"]) for b in app.tags.river_flow_ranges.value] == [
        ("Low", 0, 201.0),
        ("Normal", 201.0, 1500),         # overridden
        ("High", 1500, 1980.0),
        ("Very High", 1980.0, 1992.5),
        ("Minor Flood", 1992.5, 2500),   # from the record
        ("Major Flood", 2500, 3750),     # overridden; top is 1.5x as it exceeds the record max
    ]


def test_record_fetch_failure_keeps_old_bands_and_retries_tomorrow(gauge_record) -> None:
    app = make_app()
    app.tags.river_flow_ranges.value = [{"label": "Normal", "min": 0, "max": 10, "colour": "green"}]
    app.tags.flow_stats.value = {"max": 10.0}
    gauge_record.side_effect = OSError("timed out")
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),
    ):
        asyncio.run(app.refresh())
    assert app.tags.status.value == "OK"  # the flow itself still arrived
    assert app.tags.flow_stats.value == {"max": 10.0}
    assert app.tags.flow_stats_checked.value == f"fail:{datetime.now(timezone.utc).date()}"


def test_changing_units_reconverts_the_current_flow_without_a_new_point() -> None:
    app = make_app()
    app.config._inject_deployment_config(
        {"state": "NSW / ACT", "river_level": {"station_id": "068212"}, "river_flow": {"station_id": "418001"}}
    )
    # Recorded earlier in m³/s; the latest point is already known.
    app.tags.river_flow_cumec.value = 22.507
    app.tags.river_flow.value = 22.507
    app.tags.river_flow_time.value = int(utc("2026-09-29T12:00:00").timestamp() * 1000)
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=FLOWS),  # nothing newer
    ):
        asyncio.run(app.refresh())
    assert app.tags.river_flow.value == pytest.approx(22.507 * 86.4)
    assert app.tags.river_flow_units.value == "ML/day"
    assert not any("river_flow" in data["bom_1"] for _, data, _ in app.api.messages)  # history untouched
