"""The Queensland integration: fetching, grouping and handing readings to gauges."""

import asyncio
import io
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qldwater import handler
from qldwater.api import (
    AEST,
    QldWaterError,
    Trace,
    by_site,
    fetch_since,
    format_time,
    parse_time,
    parse_trace,
)
from qldwater.app_config import QldWaterConfig
from qldwater.application import FIRST_FETCH, OVERLAP, QldWater, bom_installs

SAVAGES = {
    "timezone": "10.0",
    "short_name": "Brisbane_R Savages",
    "longitude": "152.668941000",
    "name": "Brisbane River at Savages Crossing",
    "latitude": "-27.439727000",
    "org_name": "DNR - Hydrographic",
}
NOT_CODED = {"130": "Not coded value"}
UNKNOWN = {"timezone": "10.0", "short_name": "", "name": ""}


def trace(site, varto, units, points, details=SAVAGES, error=None) -> dict:
    raw = {
        "error_num": 0,
        "site": site,
        "site_details": details,
        "quality_codes": NOT_CODED if points else None,
        "varfrom_details": {"variable": "100.00", "units": "Metres", "name": "Stream Water Level"},
        "varto_details": {"variable": varto, "units": units, "name": "x"},
        "trace": points,
    }
    if error:
        raw.update(error_num=20, error_msg=error)
    return raw


# The three responses of one fetch, as the portal shapes them (taken from a real
# call for 143001C): level, then rated flow, then rain. 143015A has no telemetry.
LEVEL = {"traces": [
    trace("143001C", "100.00", "Metres", [
        {"v": "1.572", "t": 20261025190000, "q": 130, "d": 1},
        {"v": "1.561", "t": 20261025200000, "q": 130, "d": 1},
        {"v": "", "t": 20261025210000, "q": 255, "d": 1},
    ]),
    trace("143015A", "100.00", "Metres", [], UNKNOWN, error="Invalid station/datasource"),
]}
FLOW = {"traces": [
    trace("143001C", "141.00", "Megalitres/Day", [
        {"v": "1063.56", "t": 20261025190000, "q": 130, "d": 1},
        {"v": "1104.61", "t": 20261025180000, "q": 130, "d": 1},
    ]),
    trace("143015A", "141.00", "Megalitres/Day", [], UNKNOWN, error="Invalid station/datasource"),
]}
RAIN = {"traces": [
    trace("143001C", "10.00", "millimetres", [{"v": "2.00", "t": 20261025190000, "q": 130, "d": 6}]),
    trace("143015A", "10.00", "millimetres", [], UNKNOWN, error="Invalid station/datasource"),
]}


def ms(local: str) -> int:
    return int(parse_time(local, 10.0).timestamp() * 1000)


def test_times_are_the_gauges_local_time() -> None:
    t = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    assert format_time(t) == "20261025200000"
    assert parse_time(20261025200000, 10.0) == t
    assert parse_time("20261025193000", 9.5) == t


def test_parse_trace_drops_missing_values_and_names_the_units() -> None:
    level = parse_trace(LEVEL["traces"][0], "StreamWaterLevel")
    assert level.site == "143001C" and level.unit == "m"
    assert level.points == [[ms("20261025190000"), 1.572, "130"], [ms("20261025200000"), 1.561, "130"]]
    assert level.qualities == NOT_CODED

    flow = parse_trace(FLOW["traces"][0], "FlowRate")
    assert flow.unit == "ML/day"
    # Sorted oldest first whatever order the portal used.
    assert [p[1] for p in flow.points] == [1104.61, 1063.56]

    odd = parse_trace(trace("1", "999.00", "furlongs", [{"v": "1", "t": 20261025190000, "q": 1}]), "Odd")
    assert odd.unit == "furlongs"


def test_by_site_builds_the_live_payload() -> None:
    traces = [
        parse_trace(LEVEL["traces"][0], "StreamWaterLevel"),
        parse_trace(FLOW["traces"][0], "FlowRate"),
        parse_trace(RAIN["traces"][0], "Rainfall"),
        Trace("143015A", "StreamWaterLevel", "m", [], {}),  # nothing: not posted
    ]
    sites = by_site(traces)
    assert set(sites) == {"143001C"}
    payload = sites["143001C"]
    assert payload["site"] == "143001C"
    assert set(payload["series"]) == {"StreamWaterLevel", "FlowRate", "Rainfall"}
    assert payload["series"]["FlowRate"] == {
        "unit": "ML/day",
        "points": [[ms("20261025180000"), 1104.61, "130"], [ms("20261025190000"), 1063.56, "130"]],
    }
    assert payload["series"]["Rainfall"]["unit"] == "mm"
    assert payload["qualities"] == NOT_CODED


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def envelope(result: dict) -> FakeResponse:
    return FakeResponse(json.dumps({"error_num": 0, "return": result, "licence": "CC_40_BY"}).encode())


def test_fetch_since_asks_once_per_variable_and_reports_unknown_sites() -> None:
    requests = []

    def urlopen(request, timeout):
        url = request.full_url
        base, _, query = url.partition("?")
        requests.append(json.loads(urllib.parse.unquote(query)))
        assert base == "https://water-monitoring.information.qld.gov.au/cgi/webservice.exe"
        return envelope([LEVEL, FLOW, RAIN][len(requests) - 1])

    since = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)
    with patch("urllib.request.urlopen", urlopen):
        traces, unknown = fetch_since(["143001C", "143015A", "999999Z"], since)

    assert [(r["function"], r["version"]) for r in requests] == [("get_ts_traces", "2")] * 3
    assert [(r["params"]["varfrom"], r["params"]["varto"]) for r in requests] == [
        ("100.00", "100.00"), ("100.00", "141.00"), ("10.00", "10.00"),
    ]
    params = requests[0]["params"]
    assert params["site_list"] == "143001C,143015A,999999Z"
    assert params["datasource"] == "TE" and params["data_type"] == "point"
    assert params["start_time"] == "20261025180000"  # AEST
    assert params["end_time"] > format_time(datetime.now(timezone.utc))

    assert [(t.site, t.variable, len(t.points)) for t in traces] == [
        ("143001C", "StreamWaterLevel", 2), ("143001C", "FlowRate", 2), ("143001C", "Rainfall", 1),
    ]
    # One site the portal refused, one it left out of its answer entirely.
    assert unknown == {"143015A": "Invalid station/datasource", "999999Z": "Not in the portal's answer"}


def test_a_site_without_a_rating_still_has_its_level() -> None:
    level = {"traces": LEVEL["traces"][:1]}
    rain = {"traces": RAIN["traces"][:1]}
    unrated = {"traces": [trace("143001C", "141.00", "Megalitres/Day", [], error="No rating table")]}
    with patch("urllib.request.urlopen", side_effect=[envelope(level), envelope(unrated), envelope(rain)]):
        traces, unknown = fetch_since(["143001C"], datetime.now(timezone.utc))
    assert [t.variable for t in traces] == ["StreamWaterLevel", "Rainfall"]
    assert unknown == {}


def test_service_errors_are_raised() -> None:
    bad = FakeResponse(json.dumps({"error_num": 120, "error_msg": 'Missing top-level "params" item'}).encode())
    with (
        patch("urllib.request.urlopen", return_value=bad),
        pytest.raises(QldWaterError, match="get_ts_traces: Missing"),
    ):
        fetch_since(["143001C"], datetime.now(timezone.utc))


DEVICE_MAP = {
    "11": {"name": "savages", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "12": {"name": "fitzroy", "app_installs": [{"name": "bom_2", "application_name": "bom"}]},
    "13": {"name": "twin", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "14": {"name": "pump", "app_installs": [{"name": "pump_1", "application_name": "pump"}]},
    "15": {"name": "no-flow", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "16": {"name": "moree", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "17": {"name": "old", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "99": {"name": "integration", "app_installs": [{"name": "qldwater_1", "application_name": "qldwater"}]},
}
# (site, state) each device publishes; the old device predates the state tag.
TAGS = {
    11: ("143001C", "QLD"),
    12: ("143015A", "QLD"),
    13: ("143001C", "QLD"),
    15: (None, "QLD"),
    16: ("418002", "NSW / ACT"),
    17: ("130105A", None),
}


def test_bom_installs() -> None:
    assert bom_installs(DEVICE_MAP) == {11: "bom_1", 12: "bom_2", 13: "bom_1", 15: "bom_1", 16: "bom_1", 17: "bom_1"}
    assert bom_installs(None) == {}


class FakeApi:
    def __init__(self, fail_agents=()) -> None:
        self.messages = []
        self.fail_agents = set(fail_agents)

    async def fetch_channel_aggregate(self, channel, agent_id=None):
        assert channel == "tag_values"
        if agent_id in self.fail_agents:
            raise OSError("forbidden")
        key = bom_installs(DEVICE_MAP)[agent_id]
        site, state = TAGS[agent_id]
        return SimpleNamespace(data={key: {"live_site": site, "state": state}, "other_1": {}})

    async def create_message(self, channel, data, agent_id=None):
        self.messages.append((channel, data, agent_id))


class FakeTag:
    def __init__(self, value=None) -> None:
        self.value = value

    async def set(self, value, log=False) -> None:
        self.value = value


PERMISSIONS = {"devices": [], "groups": [], "apps_installed": [], "all_devices": False}


def make_app(fetched_at=None, api=None) -> QldWater:
    app = QldWater()
    app.config = QldWaterConfig()
    app.config._inject_deployment_config({"dv_proc_extended_permissions": PERMISSIONS})
    app.received_deployment_config = {"DEVICE_MAP": DEVICE_MAP}
    app.agent_id = 99
    app.api = api or FakeApi()
    app.tags = SimpleNamespace(
        status=FakeTag(), gauges=FakeTag(), readings=FakeTag(), fetched_at=FakeTag(fetched_at)
    )
    return app


TRACES = [
    parse_trace(LEVEL["traces"][0], "StreamWaterLevel"),
    parse_trace(FLOW["traces"][0], "FlowRate"),
    parse_trace(RAIN["traces"][0], "Rainfall"),
]


def test_refresh_hands_each_queensland_gauge_its_readings() -> None:
    app = make_app()
    unknown = {"143015A": "Invalid station/datasource"}
    with patch("qldwater.application.fetch_since", return_value=(TRACES, unknown)) as fetch:
        asyncio.run(app.refresh())

    sites, since, url = fetch.call_args.args
    # The NSW gauge is left to its own integration; the device without a state yet is included.
    assert sites == ["130105A", "143001C", "143015A"]
    assert url == "https://water-monitoring.information.qld.gov.au/cgi/webservice.exe"
    # First run reaches back past WDO's lag.
    assert abs(datetime.now(timezone.utc) - FIRST_FETCH - since) < timedelta(seconds=5)

    posted = {(agent, data["site"]) for channel, data, agent in app.api.messages}
    assert {c for c, _, _ in app.api.messages} == {"qldwater"}
    # Both devices on the Savages Crossing gauge get it; nothing for the gauge with no telemetry.
    assert posted == {(11, "143001C"), (13, "143001C")}
    assert app.tags.gauges.value == 4
    assert app.tags.readings.value == 5
    assert app.tags.status.value == (
        "OK: 2 gauge updates from 5 readings; No telemetry for 143015A (Invalid station/datasource)"
    )
    assert abs(app.tags.fetched_at.value / 1000 - datetime.now(timezone.utc).timestamp()) < 5


def test_refresh_asks_from_before_the_last_fetch_and_batches_by_fifty() -> None:
    last = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    app = make_app(fetched_at=int(last.timestamp() * 1000))
    many = {str(i): {"app_installs": [{"name": "bom_1", "application_name": "bom"}]} for i in range(100, 160)}
    app.received_deployment_config = {"DEVICE_MAP": many}

    async def fetch_channel_aggregate(channel, agent_id=None):
        return SimpleNamespace(data={"bom_1": {"live_site": f"1430{agent_id}A", "state": "QLD"}})

    app.api.fetch_channel_aggregate = fetch_channel_aggregate
    with (
        patch("qldwater.application.datetime", wraps=datetime) as clock,
        patch("qldwater.application.fetch_since", return_value=([], {})) as fetch,
    ):
        clock.now.return_value = last + timedelta(hours=1)
        asyncio.run(app.refresh())

    assert [len(c.args[0]) for c in fetch.call_args_list] == [50, 10]
    assert {c.args[1] for c in fetch.call_args_list} == {last - OVERLAP}
    assert app.tags.status.value == "OK: 0 gauge updates from 0 readings"


def test_a_failed_fetch_keeps_the_mark_for_a_retry() -> None:
    last = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp() * 1000)
    app = make_app(fetched_at=last, api=FakeApi(fail_agents={13}))
    with patch("qldwater.application.fetch_since", side_effect=QldWaterError("get_ts_traces: boom")):
        asyncio.run(app.refresh())
    assert app.tags.fetched_at.value == last
    assert app.tags.status.value.startswith("Fetch failed for 130105A, 143001C, 143015A: get_ts_traces: boom")
    # A device whose tags cannot be read is skipped, not fatal.
    assert app.tags.gauges.value == 3


def test_refresh_needs_queensland_gauges() -> None:
    app = make_app()
    app.received_deployment_config = {"DEVICE_MAP": {k: v for k, v in DEVICE_MAP.items() if k in ("15", "16")}}
    asyncio.run(app.refresh())
    assert app.tags.status.value == "No QLD BoM Station gauges with a flow station"
    assert app.tags.gauges.value == 0


def test_config_schema() -> None:
    props = QldWaterConfig.to_schema()["properties"]
    assert props["dv_proc_schedules"]["default"] == "cron(30 * * * ?)"
    fields = set(props["dv_proc_extended_permissions"]["x-extraDeviceFields"])
    assert {"app_installs__name", "app_installs__application_name"} <= fields
    assert "subscription_key" not in props
    assert handler
    assert AEST.utcoffset(None) == timedelta(hours=10)
