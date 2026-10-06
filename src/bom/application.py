"""Poll BOM's FTP feeds and record one location's river level and rainfall."""

import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pydoover.models import DeploymentEvent, ManualInvokeEvent, ScheduleEvent
from pydoover import ui
from pydoover.processor import Application
from pydoover.tags.manager import LogMode

from .app_config import FLOW_RANGE_FIELDS, STATES, BomConfig
from .app_tags import BomTags
from .app_ui import BomUI, layout
from .floodmap import find_levels
from .ftp import download_latest
from .hcs import Reading, flood_class, level_trend, parse_hcs, rain_day, unique_readings
from .obs import Observation, parse_observations
from .flowstats import fetch_history, flow_ranges, thresholds
from .wdo import Flow, convert_flow, fetch_discharge

FLOW_BACKFILL = timedelta(days=7)
# Bump when the flow statistics change meaning, so every gauge recomputes them.
FLOW_STATS_VERSION = 3

log = logging.getLogger(__name__)


def to_ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def flood_ranges(levels: list[float | None], lowest: float) -> list[dict]:
    """Gauge bands from (minor, moderate, major) flood levels; empty if none are set."""
    bands = [
        (name, v, colour)
        for name, v, colour in zip(
            ("Minor", "Moderate", "Major"),
            levels,
            (ui.Colour.yellow, ui.Colour.orange, ui.Colour.red),
        )
        if v is not None
    ]
    if not bands:
        return []
    lower = min(0, math.floor(lowest))
    ranges = [ui.Range("Below flood level", lower, bands[0][1], ui.Colour.green)]
    for i, (name, start, colour) in enumerate(bands):
        prev = bands[i - 1][1] if i else lower
        end = bands[i + 1][1] if i + 1 < len(bands) else round(start + max(1.0, start - prev), 2)
        ranges.append(ui.Range(name, start, end, colour))
    return [r.to_dict() for r in ranges]


def split_prefixes(value: str, letter: str) -> list[str]:
    return [p.strip().replace("{state}", letter) for p in value.split(",") if p.strip()]


class Bom(Application):
    config_cls = BomConfig
    tags_cls = BomTags
    ui_cls = BomUI

    config: BomConfig
    tags: BomTags
    ui: BomUI

    async def setup(self) -> None:
        # History is written explicitly at each reading's BOM timestamp, so the
        # end-of-run tag commit should only update current values.
        self.tag_manager.log_mode = LogMode.NEVER

    async def on_schedule(self, event: ScheduleEvent) -> None:
        await self.refresh()

    async def on_deployment(self, event: DeploymentEvent) -> None:
        # The framework has just published the UI for the current tags.
        await self.tags.ui_layout.set(layout(self.config, self.tags))
        await self.refresh()

    async def on_manual_invoke(self, event: ManualInvokeEvent) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        river_id = self.config.river.station_id.value.strip()
        rain_id = self.config.rain.station_id.value.strip()
        weather_id = self.config.weather.station_id.value.strip()
        flow_id = self.config.flow.station_id.value.strip()
        if not any((river_id, rain_id, weather_id, flow_id)):
            await self.tags.status.set("No station configured")
            return

        problems = []
        flows: list[Flow] = []
        if flow_id:
            try:
                flows = await self.fetch_flow(flow_id)
            except Exception as e:
                log.exception("Water Data Online fetch failed: %s", e)
                problems.append(f"Flow fetch failed: {e}")
            else:
                if not flows and self.tags.river_flow_time.value is None:
                    problems.append(f"No flow data for {flow_id}")

        letter, utc_offset = STATES[self.config.state.value]
        prefixes = []
        if river_id:
            prefixes += split_prefixes(self.config.river.files.value, letter)
        if rain_id:
            prefixes += split_prefixes(self.config.rain.files.value, letter)
        if weather_id:
            prefixes += split_prefixes(self.config.weather.files.value, letter)

        files = {}
        ftp = self.config.ftp
        if prefixes:
            try:
                files = await asyncio.to_thread(
                    download_latest,
                    ftp.host.value,
                    ftp.username.value,
                    ftp.password.value,
                    ftp.directory.value,
                    prefixes,
                    protocol=ftp.protocol.value,
                    private_key=ftp.private_key.value,
                )
            except Exception as e:
                log.exception("BOM fetch failed: %s", e)
                problems.append(f"Fetch failed: {e}")

        # Observation XML files hold the latest reading per weather station;
        # everything else is BOM-HCS.
        observation = None
        for name, text in files.items():
            if name.endswith(".xml"):
                observation = parse_observations(text).get(weather_id) or observation
        readings = unique_readings(
            r for name, text in files.items() if not name.endswith(".xml")
            for r in parse_hcs(text) if r.station_id in (river_id, rain_id)
        )

        levels = [r for r in readings if r.kind == "WL" and r.station_id == river_id]
        rains = [r for r in readings if r.kind == "RN" and r.station_id == rain_id]
        if rains:
            # If both 15-min and hourly files are configured, sum only the finest.
            finest = min(r.period_s or 0 for r in rains)
            rains = [r for r in rains if (r.period_s or 0) == finest]

        history: dict[int, dict] = defaultdict(dict)
        flood_levels: list[float | None] = [None, None, None]
        if river_id:
            flood_levels = await self.flood_levels(river_id, letter)
            await self.update_river(levels, flood_levels, history)
        await self.update_rain(rains, utc_offset, history)
        if observation:
            await self.update_weather(observation, history)
        await self.update_flow(flows, history)
        if flow_id:
            await self.update_flow_ranges(flow_id)

        for ts in sorted(history):
            await self.api.create_message(
                "tag_values", {self.app_key: history[ts]}, timestamp=ts
            )

        if files:
            missing = [
                f"{name} {sid}"
                for name, sid, got in (
                    ("river", river_id, levels),
                    ("rain", rain_id, rains),
                    ("weather", weather_id, observation),
                )
                if sid and not got
            ]
            if missing:
                problems.append(f"No data in BOM files for {', '.join(missing)}")
        await self.tags.status.set("; ".join(problems) or "OK")

        await self.update_warnings()
        await self.update_layout()

        # Flow runs a day behind, so it only decides online/offline on its own.
        times = [r.time for r in levels + rains]
        if observation:
            times.append(observation.time)
        if not times and flows:
            times.append(flows[-1].time)
        latest = max(times, default=None)
        if latest is not None:
            await self.ping_connection(
                online_at=latest,
                offline_at=latest
                + timedelta(minutes=self.config.offline_after_minutes.value),
            )

    async def update_warnings(self) -> None:
        """Flag readings older than each source's Stale After, and a river in flood."""
        now_ms = to_ms(datetime.now(timezone.utc))

        def fresh(section, time_ms: int | None) -> bool:
            if not section.station_id.value.strip():
                return True  # not configured, nothing to be stale
            limit_ms = section.stale_after_hours.value * 3600_000
            return time_ms is not None and now_ms - time_ms <= limit_ms

        c, t = self.config, self.tags
        await t.river_level_ok.set(fresh(c.river, t.river_level_time.value))
        await t.river_flow_ok.set(fresh(c.flow, t.river_flow_time.value))
        await t.rain_ok.set(fresh(c.rain, t.rain_time.value))
        await t.weather_ok.set(fresh(c.weather, t.weather_time.value))
        await t.flood_ok.set(
            not c.river.station_id.value.strip()
            or t.river_flood_class.value in (None, "Below flood level")
        )

    async def update_layout(self) -> None:
        """Republish the UI when this run's data changes which parts it shows.

        The UI is otherwise only published on deployment, which is before the
        first readings and flood levels are known.
        """
        current = layout(self.config, self.tags)
        if current == self.tags.ui_layout.value:
            return
        self.ui = self.ui_cls(self.config, self.tags, self.app_key)
        await self.ui.setup()
        await self.publish_ui_schema()
        await self.tags.ui_layout.set(current)

    async def flood_levels(self, river_id: str, letter: str) -> list[float | None]:
        """Manual flood levels, with any not given taken from BOM's flood maps."""
        river = self.config.river
        configured = [None, None, None]
        if river.flood_levels.value == "Manual":
            configured = [
                river.minor_flood_level.value,
                river.moderate_flood_level.value,
                river.major_flood_level.value,
            ]
        if None not in configured:
            return configured

        today = datetime.now(timezone.utc).date().isoformat()
        if self.tags.flood_map_checked.value != today:
            try:
                found = await asyncio.to_thread(
                    find_levels, river_id, letter, self.tags.flood_map_page.value
                )
            except Exception as e:
                log.exception("BOM flood map lookup failed: %s", e)
            else:
                page, bom_levels = found or (None, [])
                await self.tags.flood_map_page.set(page)
                await self.tags.flood_map_levels.set(bom_levels)
                await self.tags.flood_map_checked.set(today)

        bom_levels = self.tags.flood_map_levels.value or [None, None, None]
        return [c if c is not None else b for c, b in zip(configured, bom_levels)]

    async def update_river(
        self, levels: list[Reading], flood_levels: list[float | None], history: dict
    ) -> None:
        if not levels:
            return
        last_ms = self.tags.river_level_time.value or 0
        for r in levels:
            if to_ms(r.time) > last_ms:
                history[to_ms(r.time)]["river_level"] = r.value

        latest = levels[-1]
        if to_ms(latest.time) >= last_ms:
            await self.tags.river_level.set(latest.value)
            await self.tags.river_level_time.set(to_ms(latest.time))
            await self.tags.river_datum.set(latest.datum)
            await self.tags.river_trend.set(level_trend(levels))

        await self.tags.river_flood_class.set(flood_class(latest.value, flood_levels))
        await self.tags.river_ranges.set(
            flood_ranges(flood_levels, min(r.value for r in levels))
        )

    async def update_rain(
        self, rains: list[Reading], utc_offset: float, history: dict
    ) -> None:
        day = self.tags.rain_day.value
        total = self.tags.rain_since_9am.value or 0.0
        last_ms = self.tags.rain_time.value or 0

        for r in rains:
            if to_ms(r.time) <= last_ms:
                continue
            reading_day = rain_day(r.time, utc_offset)
            if reading_day != day:
                day, total = reading_day, 0.0
            total += r.value
            hour = sum(x.value for x in rains if r.time - timedelta(hours=1) < x.time <= r.time)
            history[to_ms(r.time)].update(
                rain_15min=r.value,
                rain_last_hour=round(hour, 1),
                rain_since_9am=round(total, 1),
            )
            last_ms = to_ms(r.time)

        # Roll the daily total over at 9am even if no reading has arrived since.
        today = rain_day(datetime.now(timezone.utc), utc_offset)
        if day != today:
            day, total = today, 0.0

        await self.tags.rain_day.set(day)
        await self.tags.rain_since_9am.set(round(total, 1))
        if rains:
            latest = rains[-1]
            hour = [r.value for r in rains if r.time > latest.time - timedelta(hours=1)]
            await self.tags.rain_15min.set(latest.value)
            await self.tags.rain_last_hour.set(round(sum(hour), 1))
            await self.tags.rain_time.set(last_ms)
            await self.tags.rain_period_s.set(latest.period_s)

    async def fetch_flow(self, flow_id: str) -> list[Flow]:
        """Flow since the last recorded point, or the last week on the first run."""
        now = datetime.now(timezone.utc)
        last_ms = self.tags.river_flow_time.value
        start = (
            datetime.fromtimestamp(last_ms / 1000, timezone.utc)
            if last_ms
            else now - FLOW_BACKFILL
        )
        return await asyncio.to_thread(
            fetch_discharge,
            self.config.flow.url.value,
            flow_id,
            self.config.flow.series.value,
            start,
            now + timedelta(hours=1),
        )

    async def update_flow(self, flows: list[Flow], history: dict) -> None:
        """Record new flow points, converted into the configured display units."""
        units = self.config.flow.units.value
        await self.tags.river_flow_units.set(units)
        last_ms = self.tags.river_flow_time.value or 0
        new = [f for f in flows if to_ms(f.time) > last_ms]
        for f in new:
            history[to_ms(f.time)]["river_flow"] = convert_flow(f.value, units)
        if new:
            await self.tags.river_flow_cumec.set(new[-1].value)
            await self.tags.river_flow_time.set(to_ms(new[-1].time))
        # Shown value always follows the configured units, even with no new point.
        latest = self.tags.river_flow_cumec.value
        if latest is not None:
            await self.tags.river_flow.set(convert_flow(latest, units))

    async def update_flow_ranges(self, flow_id: str) -> None:
        """Flow bands: configured values first, else from the gauge's own record.

        The record is read once a month (or again the next day after a failure);
        the bands are rebuilt every run so a config change shows on the next one.
        """
        now = datetime.now(timezone.utc)
        checked = self.tags.flow_stats_checked.value
        if checked not in (f"{now:%Y-%m}/{FLOW_STATS_VERSION}", f"fail:{now.date()}"):
            try:
                record = await asyncio.to_thread(fetch_history, self.config.flow.url.value, flow_id)
                await self.tags.flow_stats.set(thresholds(record))
                await self.tags.flow_stats_checked.set(f"{now:%Y-%m}/{FLOW_STATS_VERSION}")
            except Exception as e:
                log.exception("Water Data Online history fetch failed: %s", e)
                await self.tags.flow_stats_checked.set(f"fail:{now.date()}")

        units = self.config.flow.units.value
        edges = {k: convert_flow(v, units) for k, v in (self.tags.flow_stats.value or {}).items()}
        if self.config.flow.ranges.value == "Manual":
            for key, field in FLOW_RANGE_FIELDS.items():
                value = getattr(self.config.flow, field).value
                if value is not None:
                    edges[key] = value
        await self.tags.river_flow_ranges.set(flow_ranges(edges))

    async def update_weather(self, obs: Observation, history: dict) -> None:
        """Record the station's latest observation, once per BOM timestamp."""
        await self.tags.weather_station.set(obs.name)
        if to_ms(obs.time) <= (self.tags.weather_time.value or 0):
            return
        values = {
            "weather_temp": obs.temp,
            "weather_apparent_temp": obs.apparent_temp,
            "weather_dew_point": obs.dew_point,
            "weather_humidity": obs.humidity,
            "weather_pressure": obs.pressure,
            "weather_wind_dir": obs.wind_dir,
            "weather_wind_speed": obs.wind_speed,
            "weather_wind_gust": obs.wind_gust,
        }
        for name, value in values.items():
            await getattr(self.tags, name).set(value)
        await self.tags.weather_time.set(to_ms(obs.time))
        history[to_ms(obs.time)].update({k: v for k, v in values.items() if v is not None})
