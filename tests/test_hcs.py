import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from bom import handler
from bom.app_config import BomConfig
from bom.app_ui import BomUI
from bom.application import Bom
from bom.floodmap import parse_levels
from bom.ftp import latest_file
from bom.application import flood_ranges
from bom.hcs import flood_class, level_trend, parse_hcs, rain_day

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

    async def create_message(self, channel, data, timestamp=None):
        self.messages.append((channel, data, timestamp))


class FakeTag:
    def __init__(self) -> None:
        self.value = None

    async def set(self, value, log=False) -> None:
        self.value = value


def make_app() -> Bom:
    app = Bom()
    app.config = BomConfig()
    app.config._inject_deployment_config(
        {"river_level": {"station_id": "068212"}, "rainfall": {"station_id": "068212"}}
    )
    app.app_key = "bom_1"
    app.api = FakeApi()
    app.tags = type("Tags", (), {n: FakeTag() for n in (
        "river_level", "river_level_time", "river_trend", "river_datum",
        "river_flood_class", "river_ranges",
        "rain_15min", "rain_last_hour", "rain_since_9am", "rain_time",
        "status", "rain_day", "flood_map_page", "flood_map_levels", "flood_map_checked",
    )})()

    async def ping_connection(**kwargs) -> None:
        pass

    app.ping_connection = ping_connection
    return app


def test_refresh_records_history_and_totals() -> None:
    app = make_app()
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
    ):
        asyncio.run(app.refresh())

    assert app.tags.status.value == "OK"
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

    # A second run over the same file writes nothing new.
    app.api.messages.clear()
    with (
        patch("bom.application.download_latest", return_value={"IDN65910_1.hcs": HCS}),
        patch("bom.application.find_levels") as find,
    ):
        asyncio.run(app.refresh())
    find.assert_not_called()  # already looked up today
    assert app.api.messages == []


def test_schemas_and_entry_point() -> None:
    assert "ftp_server" in BomConfig.to_schema()["properties"]
    assert isinstance(BomUI(None, None, None).to_schema(), dict)
    assert handler
