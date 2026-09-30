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

from .app_config import STATES, BomConfig
from .app_tags import BomTags
from .app_ui import BomUI
from .floodmap import find_levels
from .ftp import download_latest
from .hcs import Reading, flood_class, level_trend, parse_hcs, rain_day, unique_readings

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
        await self.refresh()

    async def on_manual_invoke(self, event: ManualInvokeEvent) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        river_id = self.config.river.station_id.value.strip()
        rain_id = self.config.rain.station_id.value.strip()
        if not river_id and not rain_id:
            await self.tags.status.set("No station configured")
            return

        letter, utc_offset = STATES[self.config.state.value]
        prefixes = []
        if river_id:
            prefixes += split_prefixes(self.config.river.files.value, letter)
        if rain_id:
            prefixes += split_prefixes(self.config.rain.files.value, letter)

        ftp = self.config.ftp
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
            log.exception("BOM fetch failed")
            await self.tags.status.set(f"Fetch failed: {e}")
            return

        readings = unique_readings(
            r for text in files.values() for r in parse_hcs(text)
            if r.station_id in (river_id, rain_id)
        )

        levels = [r for r in readings if r.kind == "WL" and r.station_id == river_id]
        rains = [r for r in readings if r.kind == "RN" and r.station_id == rain_id]
        if rains:
            # If both 15-min and hourly files are configured, sum only the finest.
            finest = min(r.period_s or 0 for r in rains)
            rains = [r for r in rains if (r.period_s or 0) == finest]

        history: dict[int, dict] = defaultdict(dict)
        if river_id:
            await self.update_river(levels, await self.flood_levels(river_id, letter), history)
        await self.update_rain(rains, utc_offset, history)

        for ts in sorted(history):
            await self.api.create_message(
                "tag_values", {self.app_key: history[ts]}, timestamp=ts
            )

        missing = [
            f"{name} {sid}"
            for name, sid, got in (("river", river_id, levels), ("rain", rain_id, rains))
            if sid and not got
        ]
        await self.tags.status.set(
            f"No data in BOM files for {', '.join(missing)}" if missing else "OK"
        )

        latest = max((r.time for r in levels + rains), default=None)
        if latest is not None:
            await self.ping_connection(
                online_at=latest,
                offline_at=latest
                + timedelta(minutes=self.config.offline_after_minutes.value),
            )

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
            except Exception:
                log.exception("BOM flood map lookup failed")
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
            history[to_ms(r.time)].update(
                rain_15min=r.value, rain_since_9am=round(total, 1)
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
