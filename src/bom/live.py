"""Live gauge readings handed over by the WaterNSW integration.

The integration posts each gauge's new readings to the device's `waternsw`
channel, one message per fetch:

    {"site": "418002",
     "series": {"FlowRate": {"unit": "ML/day", "points": [[ms, value, quality], ...]},
                "StreamWaterLevel": {"unit": "m", "points": [...]}, ...},
     "qualities": {"125": "Auto QC - Passed", ...}}

Only level and flow are recorded here; the other variables stay in the channel.
"""

from datetime import datetime, timezone

from .hcs import Reading
from .wdo import TO_CUMEC, Flow

CHANNEL = "waternsw"
FLOW = "FlowRate"
LEVEL = "StreamWaterLevel"


def _points(payload: dict, variable: str) -> tuple[str | None, list[tuple[datetime, float]]]:
    series = (payload.get("series") or {}).get(variable) or {}
    points = [
        (datetime.fromtimestamp(ms / 1000, timezone.utc), float(value))
        for ms, value, *_ in series.get("points") or []
        if value is not None
    ]
    return series.get("unit"), sorted(points)


def live_flows(payload: dict) -> list[Flow]:
    """The payload's flow, in m³/s; empty if its units are not ones we know."""
    unit, points = _points(payload, FLOW)
    scale = TO_CUMEC.get(unit)
    if scale is None:
        return []
    return [Flow(t, v * scale) for t, v in points]


def live_levels(payload: dict) -> list[Reading]:
    """The payload's stream level (m, local gauge height) as river level readings."""
    _, points = _points(payload, LEVEL)
    site = payload.get("site", "")
    return [Reading(site, "WL", t, v, "metres", "LGH", None) for t, v in points]
