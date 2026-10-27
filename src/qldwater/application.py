"""Fetch live readings from Queensland's water monitoring portal for the org's gauges.

Each run asks the portal for every point logged since the last successful run
(less an overlap, as a gauge sends an hour of points at a time), in one
request per variable per 50 gauges, and posts each gauge's readings to the
`qldwater` channel of every device following it. The BoM Station app records
them from there, so it stays the only writer of its own tags and history.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pydoover.models import DeploymentEvent, ManualInvokeEvent, ScheduleEvent
from pydoover.processor import Application

from .api import MAX_SITES, by_site, fetch_since
from .app_config import QldWaterConfig
from .app_tags import QldWaterTags
from .app_ui import QldWaterUI

BOM_APP_NAME = "bom"
CHANNEL = "qldwater"
STATE = "QLD"
# The first fetch reaches back past Water Data Online's lag (about a day and a
# half), so the switch-over leaves no hole in a gauge's flow history.
FIRST_FETCH = timedelta(hours=40)
# Tag reads in flight at once, well inside the platform's ~10 requests/second.
READ_CONCURRENCY = 5
# Re-ask for this much before the last fetch: a gauge logs sub-hourly points
# but transmits them on the hour. The BoM app skips what it has.
OVERLAP = timedelta(hours=2)

log = logging.getLogger(__name__)


def to_ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def bom_installs(device_map: dict) -> dict[int, str]:
    """{device agent id: its BoM Station app key} for the devices we were granted."""
    found = {}
    for device_id, device in (device_map or {}).items():
        for install in device.get("app_installs") or []:
            if install.get("application_name") == BOM_APP_NAME and install.get("name"):
                found[int(device_id)] = install["name"]
                break
    return found


class QldWater(Application):
    config_cls = QldWaterConfig
    tags_cls = QldWaterTags
    ui_cls = QldWaterUI

    config: QldWaterConfig
    tags: QldWaterTags

    # An integration is installed on the organisation, not a device, so there
    # is no connection status to keep.
    async def on_deployment(self, event: DeploymentEvent) -> None:
        await self.refresh()

    async def on_schedule(self, event: ScheduleEvent) -> None:
        await self.refresh()

    async def on_manual_invoke(self, event: ManualInvokeEvent) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        gauges = await self.find_gauges()
        if not gauges:
            await self.tags.status.set("No QLD BoM Station gauges with a flow station")
            await self.tags.gauges.set(0)
            return

        now = datetime.now(timezone.utc)
        last = self.tags.fetched_at.value
        since = (
            datetime.fromtimestamp(last / 1000, timezone.utc) - OVERLAP
            if last
            else now - FIRST_FETCH
        )

        sites = sorted(gauges)
        traces, unknown, problems = [], {}, []
        for i in range(0, len(sites), MAX_SITES):
            batch = sites[i : i + MAX_SITES]
            try:
                got, missing = await asyncio.to_thread(fetch_since, batch, since, self.config.url.value)
            except Exception as e:
                log.exception("Queensland portal fetch failed for %s: %s", batch, e)
                problems.append(f"Fetch failed for {', '.join(batch)}: {e}")
                continue
            traces += got
            unknown.update(missing)

        fed = 0
        for site, payload in by_site(traces).items():
            for agent_id in gauges.get(site, []):
                try:
                    await self.api.create_message(CHANNEL, payload, agent_id=agent_id)
                    fed += 1
                except Exception as e:
                    log.exception("Posting %s to agent %s failed: %s", site, agent_id, e)
                    problems.append(f"Post failed for {site} on {agent_id}: {e}")

        # Only move on when everything landed; a retry re-sends what did, and
        # the BoM app skips readings it already has.
        if not problems:
            await self.tags.fetched_at.set(to_ms(now))
        readings = sum(len(t.points) for t in traces)
        await self.tags.gauges.set(sum(len(v) for v in gauges.values()))
        await self.tags.readings.set(readings)
        # A gauge the portal does not know is a configuration problem on that
        # device, not a failed run, so it is noted without holding the mark.
        notes = problems or [f"OK: {fed} gauge updates from {readings} readings"]
        if unknown:
            notes.append("No telemetry for " + ", ".join(f"{s} ({why})" for s, why in sorted(unknown.items())))
        await self.tags.status.set("; ".join(notes))

    async def find_gauges(self) -> dict[str, list[int]]:
        """{portal site id: agent ids of the devices following it}.

        Each BoM Station publishes the gauge it wants as its live_site tag (its
        River Flow station, which for Queensland is the portal's site id too)
        and its state; only Queensland devices are fed from here.
        """
        installs = bom_installs(self.received_deployment_config.get("DEVICE_MAP"))
        installs.pop(self.agent_id, None)

        limit = asyncio.Semaphore(READ_CONCURRENCY)

        async def site_of(agent_id: int, app_key: str) -> str | None:
            async with limit:
                aggregate = await self.api.fetch_channel_aggregate("tag_values", agent_id=agent_id)
            tags = (aggregate.data or {}).get(app_key) or {}
            # A device not yet publishing its state is given the benefit of the
            # doubt; the portal simply has no data for a gauge elsewhere.
            if tags.get("state") not in (None, STATE):
                return None
            return tags.get("live_site")

        agents = list(installs)
        found = await asyncio.gather(
            *(site_of(a, installs[a]) for a in agents), return_exceptions=True
        )
        gauges: dict[str, list[int]] = defaultdict(list)
        for agent_id, site in zip(agents, found):
            if isinstance(site, Exception):
                log.warning("Reading tags of agent %s failed: %s", agent_id, site)
            elif site:
                gauges[site].append(agent_id)
        return dict(gauges)
