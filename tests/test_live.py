"""The BoM app recording live readings handed over by the WaterNSW integration."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bom.app_config import BomConfig
from bom.live import live_flows, live_levels
from test_hcs import FLOWS, HCS, gauge_record, make_app  # noqa: F401 (autouse WDO history stub)
from test_obs import OBS_XML


def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
T1, T2 = NOW - timedelta(minutes=30), NOW - timedelta(minutes=15)


def payload(site: str = "418001") -> dict:
    return {
        "site": site,
        "series": {
            # Out of order on purpose; the app sorts them.
            "FlowRate": {"unit": "ML/day", "points": [[ms(T2), 864.0, "125"], [ms(T1), 432.0, "125"]]},
            "StreamWaterLevel": {"unit": "m", "points": [[ms(T1), 1.50, "125"], [ms(T2), 1.55, "125"]]},
            "WaterTemperature": {"unit": "degrees Centigrade", "points": [[ms(T2), 20.0, "135"]]},
        },
        "qualities": {"125": "Auto QC - Passed"},
    }


def reconfigure(app, **sections) -> None:
    app.config = BomConfig()
    app.config._inject_deployment_config({"state": "NSW / ACT", **sections})


def run(app, live=None, wdo=FLOWS, files=None):
    with (
        patch("bom.application.download_latest", return_value=files or {}),
        patch("bom.application.find_levels", return_value=("IDN65195.html", [1.0, 2.0, 3.0])),
        patch("bom.application.fetch_discharge", return_value=wdo) as fetch,
    ):
        asyncio.run(app.refresh(live=live))
    return fetch


def history(app) -> dict[int, dict]:
    return {ts: data["bom_1"] for channel, data, ts in app.api.messages if channel == "tag_values"}


def test_payload_parsing() -> None:
    flows = live_flows(payload())
    assert [f.time for f in flows] == [T1, T2]
    assert flows[-1].value == pytest.approx(10.0)  # 864 ML/day = 10 m³/s
    levels = live_levels(payload())
    assert [(r.value, r.datum, r.station_id) for r in levels] == [(1.50, "LGH", "418001"), (1.55, "LGH", "418001")]
    # Units we cannot convert are left out rather than recorded wrongly.
    odd = {"site": "1", "series": {"FlowRate": {"unit": "furlongs", "points": [[0, 1.0, "1"]]}}}
    assert live_flows(odd) == []


def test_live_flow_moves_the_mark_so_wdo_falls_behind() -> None:
    app = make_app()
    run(app, live=payload())

    # WDO's week and the live points are both new on the first run.
    assert app.tags.river_flow_time.value == ms(T2)
    assert app.tags.river_flow.value == pytest.approx(864.0)
    assert history(app)[ms(T2) + 2]["river_flow"] == pytest.approx(864.0)
    assert app.tags.waternsw_site.value == "418001"

    # The next scheduled run asks WDO only for what follows the live mark.
    app.api.messages.clear()
    fetch = run(app)
    _, _, _, start, _ = fetch.call_args.args
    assert start == T2
    assert not any("river_flow" in h for h in history(app).values())
    assert app.tags.river_flow_time.value == ms(T2)


def test_live_flow_keeps_the_device_online() -> None:
    app = make_app()
    reconfigure(app, river_flow={"station_id": "418001"})
    pings = []

    async def ping_connection(**kwargs) -> None:
        pings.append(kwargs["online_at"])

    app.ping_connection = ping_connection
    run(app, live=payload())
    assert pings == [T2]


def test_live_level_stands_in_without_a_flood_warning_gauge() -> None:
    app = make_app()
    reconfigure(app, river_flow={"station_id": "418001"}, river_level={"station_id": ""})
    run(app, live=payload())

    assert app.tags.river_level.value == 1.55
    assert app.tags.river_datum.value == "LGH"
    assert app.tags.river_trend.value == "rising"
    assert app.tags.river_level_time.value == ms(T2)
    assert history(app)[ms(T1) + 3]["river_level"] == 1.50
    # No flood levels without a flood-warning gauge or manual ones.
    assert app.tags.river_flood_class.value is None
    assert app.tags.flood_ok.value is True
    assert app.tags.river_level_ok.value is True
    assert "river" in app.tags.ui_layout.value.split(",")


def test_live_level_takes_manual_flood_levels() -> None:
    app = make_app()
    reconfigure(
        app,
        river_flow={"station_id": "418001"},
        river_level={"station_id": "", "flood_levels": "Manual", "minor_flood_level": 1.5},
    )
    with patch("bom.application.find_levels") as lookup:
        run(app, live=payload())
    lookup.assert_not_called()
    assert app.tags.river_flood_class.value == "Minor"
    assert app.tags.flood_ok.value is False


def test_flood_warning_gauge_level_wins_over_live() -> None:
    app = make_app()  # 068212 is the flood-warning gauge
    run(app, live=payload(), files={"IDN65910_1.hcs": HCS, "IDN60920.xml": OBS_XML})
    assert app.tags.river_level.value == 1.05
    assert app.tags.river_datum.value == "AHD"
    # Flow still comes through live.
    assert app.tags.river_flow_time.value == ms(T2)


def test_live_readings_for_another_gauge_are_ignored() -> None:
    app = make_app()
    run(app, live=payload(site="418002"), wdo=[])
    assert app.tags.river_flow_time.value is None


def test_only_the_waternsw_channel_triggers_a_refresh() -> None:
    app = make_app()
    calls = []

    async def refresh(live=None) -> None:
        calls.append(live)

    app.refresh = refresh

    def event(name: str):
        return SimpleNamespace(channel=SimpleNamespace(name=name), message=SimpleNamespace(data=payload()))

    asyncio.run(app.on_message_create(event("waternsw")))
    asyncio.run(app.on_message_create(event("tag_values")))
    assert calls == [payload()]


def test_bom_subscribes_to_the_waternsw_channel() -> None:
    schema = BomConfig.to_schema()["properties"]["dv_proc_subscriptions"]
    assert schema["default"] == ["waternsw"]
