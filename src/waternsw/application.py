"""Fetch live readings from WaterNSW for every BoM Station gauge in the org.

Each run asks WaterNSW for everything loaded since the last successful run, in
one request per 20 gauges, and posts each gauge's new readings to the
`waternsw` channel of every device following it. The BoM Station app records
them from there, so it stays the only writer of its own tags and history.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pydoover.models import DeploymentEvent, ManualInvokeEvent, ScheduleEvent
from pydoover.processor import Application

from .api import MAX_SITES, MAX_SPAN, PAGE_PAUSE, by_site, fetch_since
from .app_config import WaterNswConfig
from .app_tags import WaterNswTags
from .app_ui import WaterNswUI

BOM_APP_NAME = "bom"
CHANNEL = "waternsw"
# The first fetch reaches back past Water Data Online's lag (about a day and a
# half), so the switch-over leaves no hole in a gauge's flow history. It costs
# several pages, once.
FIRST_FETCH = timedelta(hours=40)
# Tag reads in flight at once, well inside the platform's ~10 requests/second.
READ_CONCURRENCY = 5
# Re-ask for a little before the last fetch; the BoM app skips what it has.
OVERLAP = timedelta(minutes=10)

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


class WaterNsw(Application):
    config_cls = WaterNswConfig
    tags_cls = WaterNswTags
    ui_cls = WaterNswUI

    config: WaterNswConfig
    tags: WaterNswTags

    # Installed on the organisation rather than a device, so there is no
    # connection status to keep.
    async def on_deployment(self, event: DeploymentEvent) -> None:
        await self.refresh()

    async def on_schedule(self, event: ScheduleEvent) -> None:
        await self.refresh()

    async def on_manual_invoke(self, event: ManualInvokeEvent) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        key = self.config.subscription_key.value.strip()
        if not key:
            await self.tags.status.set("No subscription key")
            return

        gauges = await self.find_gauges()
        if not gauges:
            await self.tags.status.set("No BoM Station gauges with a flow station")
            await self.tags.gauges.set(0)
            return

        now = datetime.now(timezone.utc)
        last = self.tags.fetched_at.value
        since = (
            datetime.fromtimestamp(last / 1000, timezone.utc) - OVERLAP
            if last
            else now - FIRST_FETCH
        )
        # WaterNSW refuses anything older; after a long outage the gap stays.
        since = max(since, now - MAX_SPAN + OVERLAP)

        sites = sorted(gauges)
        records, qualities, problems = [], {}, []
        for i in range(0, len(sites), MAX_SITES):
            batch = sites[i : i + MAX_SITES]
            if i:
                await asyncio.sleep(PAGE_PAUSE)
            try:
                got, codes = await asyncio.to_thread(
                    fetch_since, key, batch, since, self.config.url.value
                )
            except Exception as e:
                log.exception("WaterNSW fetch failed for %s: %s", batch, e)
                problems.append(f"Fetch failed for {', '.join(batch)}: {e}")
                continue
            records += got
            qualities.update(codes)

        fed = 0
        for site, payload in by_site(records, qualities).items():
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
        await self.tags.gauges.set(sum(len(v) for v in gauges.values()))
        await self.tags.readings.set(len(records))
        await self.tags.status.set(
            "; ".join(problems) or f"OK: {fed} gauge updates from {len(records)} readings"
        )

    async def find_gauges(self) -> dict[str, list[int]]:
        """{WaterNSW site id: agent ids of the devices following it}.

        Each BoM Station publishes the gauge it wants as its waternsw_site tag.
        """
        installs = bom_installs(self.received_deployment_config.get("DEVICE_MAP"))
        installs.pop(self.agent_id, None)

        limit = asyncio.Semaphore(READ_CONCURRENCY)

        async def site_of(agent_id: int, app_key: str) -> str | None:
            async with limit:
                aggregate = await self.api.fetch_channel_aggregate("tag_values", agent_id=agent_id)
            return ((aggregate.data or {}).get(app_key) or {}).get("waternsw_site")

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
