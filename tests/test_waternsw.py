"""The WaterNSW integration: fetching, grouping and handing readings to gauges."""

import asyncio
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from waternsw import handler
from waternsw.api import AEST, WaterNswError, by_site, fetch_since, format_time, parse_time
from waternsw.app_config import WaterNswConfig
from waternsw.application import FIRST_FETCH, OVERLAP, WaterNsw, bom_installs

RECORDS = [
    {"siteId": "418002", "timeStamp": "20-Oct-2026 09:15", "variableName": "FlowRate",
     "value": 711.6, "unitOfMeasure": "ML/day", "qualityCode": "125"},
    {"siteId": "418002", "timeStamp": "20-Oct-2026 09:00", "variableName": "FlowRate",
     "value": 700.0, "unitOfMeasure": "ML/day", "qualityCode": "125"},
    {"siteId": "418002", "timeStamp": "20-Oct-2026 09:15", "variableName": "StreamWaterLevel",
     "value": 1.553, "unitOfMeasure": "m", "qualityCode": "130"},
    {"siteId": "416201A", "timeStamp": "20-Oct-2026 09:00", "variableName": "FlowRate",
     "value": 484, "unitOfMeasure": "ML/day", "qualityCode": "130"},
]
QUALITIES = {"125": "Auto QC - Passed", "130": "Not quality coded - subject to change"}


def ms(s: str) -> int:
    return int(parse_time(s).timestamp() * 1000)


def test_times_are_aest_all_year() -> None:
    # January is daylight saving in NSW, but WaterNSW stays on AEST.
    t = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert format_time(t) == "01-Jan-2026 10:00"
    assert parse_time("01-Jan-2026 10:00") == t


def test_by_site_groups_and_sorts() -> None:
    sites = by_site(RECORDS, QUALITIES)
    assert set(sites) == {"418002", "416201A"}
    moree = sites["418002"]
    assert moree["site"] == "418002"
    assert moree["series"]["FlowRate"] == {
        "unit": "ML/day",
        "points": [[ms("20-Oct-2026 09:00"), 700.0, "125"], [ms("20-Oct-2026 09:15"), 711.6, "125"]],
    }
    assert moree["series"]["StreamWaterLevel"]["points"] == [[ms("20-Oct-2026 09:15"), 1.553, "130"]]
    assert moree["qualities"] == QUALITIES
    assert sites["416201A"]["qualities"] == {"130": QUALITIES["130"]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_since_follows_every_page() -> None:
    pages = [
        {"records": RECORDS[:2], "qualities": {"125": QUALITIES["125"]},
         "nextPageUrl": "https://api.waternsw.com.au/water/surface-water-data-api?siteId=418002&dataSince=20-Oct-2026 08:00&pageNumber=2&requestId=abc"},
        {"records": RECORDS[2:], "qualities": {"130": QUALITIES["130"]}, "nextPageUrl": ""},
    ]
    urls = []

    def urlopen(request, timeout):
        urls.append(request.full_url)
        assert request.get_header("Ocp-apim-subscription-key") == "key"
        return FakeResponse(json.dumps(pages[len(urls) - 1]).encode())

    since = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
    with patch("urllib.request.urlopen", urlopen):
        records, qualities = fetch_since("key", ["418002", "416201A"], since, pause=0)

    assert records == RECORDS and qualities == QUALITIES
    assert "siteId=418002%2C416201A" in urls[0]
    assert "frequency=Instantaneous" in urls[0] and "dataType=AutoQC" in urls[0]
    assert "dataSince=20-Oct-2026+08%3A00" in urls[0]
    # Page links carry raw spaces; they are escaped before use.
    assert " " not in urls[1] and "pageNumber=2" in urls[1]


def http_error(code: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body).encode()))


def test_no_data_is_an_empty_fetch_and_bad_keys_are_errors() -> None:
    since = datetime.now(timezone.utc)
    no_data = http_error(404, {"responseMessage": "No data found for the request criteria provided"})
    with patch("urllib.request.urlopen", side_effect=no_data):
        assert fetch_since("key", ["1"], since, pause=0) == ([], {})

    denied = http_error(401, {"statusCode": 401, "message": "Access denied due to invalid subscription key."})
    with patch("urllib.request.urlopen", side_effect=denied), pytest.raises(WaterNswError, match="401.*invalid subscription key"):
        fetch_since("key", ["1"], since, pause=0)


DEVICE_MAP = {
    "11": {"name": "mehi", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "12": {"name": "gwydir", "app_installs": [{"name": "bom_2", "application_name": "bom"}]},
    "13": {"name": "twin", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "14": {"name": "pump", "app_installs": [{"name": "pump_1", "application_name": "pump"}]},
    "15": {"name": "no-flow", "app_installs": [{"name": "bom_1", "application_name": "bom"}]},
    "99": {"name": "integration", "app_installs": [{"name": "waternsw_1", "application_name": "waternsw"}]},
}
SITES = {11: "418002", 12: "416201A", 13: "418002", 15: None}


def test_bom_installs() -> None:
    assert bom_installs(DEVICE_MAP) == {11: "bom_1", 12: "bom_2", 13: "bom_1", 15: "bom_1"}
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
        return SimpleNamespace(data={key: {"waternsw_site": SITES[agent_id]}, "other_1": {}})

    async def create_message(self, channel, data, agent_id=None):
        self.messages.append((channel, data, agent_id))


class FakeTag:
    def __init__(self, value=None) -> None:
        self.value = value

    async def set(self, value, log=False) -> None:
        self.value = value


PERMISSIONS = {"devices": [], "groups": [], "apps_installed": [], "all_devices": False}


def make_app(key="key", fetched_at=None, api=None) -> WaterNsw:
    app = WaterNsw()
    app.config = WaterNswConfig()
    app.config._inject_deployment_config({"subscription_key": key, "dv_proc_extended_permissions": PERMISSIONS})
    app.received_deployment_config = {"DEVICE_MAP": DEVICE_MAP}
    app.agent_id = 99
    app.api = api or FakeApi()
    app.tags = SimpleNamespace(
        status=FakeTag(), gauges=FakeTag(), readings=FakeTag(), fetched_at=FakeTag(fetched_at)
    )
    return app


def test_refresh_hands_each_gauge_its_readings() -> None:
    app = make_app()
    with patch("waternsw.application.fetch_since", return_value=(RECORDS, QUALITIES)) as fetch:
        asyncio.run(app.refresh())

    key, sites, since, url = fetch.call_args.args
    assert (key, sites) == ("key", ["416201A", "418002"])
    assert url == "https://api.waternsw.com.au/water"
    # First run reaches back past WDO's lag.
    assert abs(datetime.now(timezone.utc) - FIRST_FETCH - since) < timedelta(seconds=5)

    posted = {(agent, data["site"]) for channel, data, agent in app.api.messages}
    assert {c for c, _, _ in app.api.messages} == {"waternsw"}
    # Both devices on the Moree gauge get it; the device with no flow station does not.
    assert posted == {(11, "418002"), (13, "418002"), (12, "416201A")}
    assert app.tags.gauges.value == 3
    assert app.tags.readings.value == 4
    assert app.tags.status.value == "OK: 3 gauge updates from 4 readings"
    assert abs(app.tags.fetched_at.value / 1000 - datetime.now(timezone.utc).timestamp()) < 5


def test_refresh_asks_from_the_last_fetch_and_batches_by_twenty() -> None:
    last = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    app = make_app(fetched_at=int(last.timestamp() * 1000))
    many = {str(i): {"app_installs": [{"name": "bom_1", "application_name": "bom"}]} for i in range(100, 125)}
    app.received_deployment_config = {"DEVICE_MAP": many}

    async def fetch_channel_aggregate(channel, agent_id=None):
        return SimpleNamespace(data={"bom_1": {"waternsw_site": f"4180{agent_id}"}})

    app.api.fetch_channel_aggregate = fetch_channel_aggregate
    with (
        patch("waternsw.application.datetime", wraps=datetime) as clock,
        patch("waternsw.application.fetch_since", return_value=([], {})) as fetch,
        patch("waternsw.application.asyncio.sleep") as sleep,
    ):
        clock.now.return_value = last + timedelta(hours=1)
        asyncio.run(app.refresh())

    assert [len(c.args[1]) for c in fetch.call_args_list] == [20, 5]
    assert {c.args[2] for c in fetch.call_args_list} == {last - OVERLAP}
    sleep.assert_called_once()  # spaced for the Basic tier's 5 a minute


def test_a_failed_fetch_keeps_the_mark_for_a_retry() -> None:
    last = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)
    app = make_app(fetched_at=last, api=FakeApi(fail_agents={13}))
    with patch("waternsw.application.fetch_since", side_effect=WaterNswError("HTTP 429: Rate limit")):
        asyncio.run(app.refresh())
    assert app.tags.fetched_at.value == last
    assert app.tags.status.value.startswith("Fetch failed for 416201A, 418002: HTTP 429")
    # A device whose tags cannot be read is skipped, not fatal.
    assert app.tags.gauges.value == 2


def test_refresh_needs_a_key_and_gauges() -> None:
    app = make_app(key="")
    asyncio.run(app.refresh())
    assert app.tags.status.value == "No subscription key"

    app = make_app()
    app.received_deployment_config = {"DEVICE_MAP": {}}
    asyncio.run(app.refresh())
    assert app.tags.status.value == "No BoM Station gauges with a flow station"


def test_config_schema() -> None:
    props = WaterNswConfig.to_schema()["properties"]
    assert props["dv_proc_schedules"]["default"] == "rate(1 hour)"
    fields = set(props["dv_proc_extended_permissions"]["x-extraDeviceFields"])
    assert {"app_installs__name", "app_installs__application_name"} <= fields
    assert handler
