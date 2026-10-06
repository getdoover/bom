"""Flow bands for a gauge, worked out from its own Water Data Online record.

Percentiles of the daily mean discharge give the low / normal / high bands.
The bands stop at High on purpose: river flow is so skewed that bands reaching
up to flood flows (let alone the record maximum) squash a normal day's trace
onto the floor of the graph. The UI grows the top band when a flow exceeds it,
so floods still plot; they just read as High on the flow axis, while the river
level carries the flood classification.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pydoover import ui

from .wdo import DISCHARGE, TO_CUMEC, fetch_series, list_procedures

HISTORY_YEARS = 16
MIN_DAYS = 3 * 365  # record needed before percentiles mean much
PERCENTILES = {"low": 25, "high": 75}
TOP_BAND_FACTOR = 1.5  # the top band ends this far above its own edge

# Threshold -> the band that starts there. Order matters: bands must rise.
BANDS = (
    ("low", "Normal", ui.Colour.green),
    ("high", "High", ui.Colour.blue),
)


@dataclass
class History:
    mean_flow: dict[date, float]  # m³/s


def fetch_history(url: str, station_id: str, years: int = HISTORY_YEARS) -> History:
    """Daily mean flow for the last *years*."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    procedures = [p for p in list_procedures(url, station_id, DISCHARGE) if p.endswith("_C_B_1_DailyMean")]
    if not procedures:
        return History(mean_flow={})
    unit, points = fetch_series(url, station_id, DISCHARGE, procedures[0], start, end)
    if unit not in TO_CUMEC:
        raise ValueError(f"Unexpected discharge unit {unit!r}")
    scale = TO_CUMEC[unit]
    return History(mean_flow={t.date(): v * scale for t, v in points})


def thresholds(history: History) -> dict[str, float]:
    """Band edges in m³/s, if the record is long enough to support them."""
    flows = sorted(history.mean_flow.values())
    if len(flows) < MIN_DAYS:
        return {}
    return {name: flows[round(pct / 100 * (len(flows) - 1))] for name, pct in PERCENTILES.items()}


def flow_ranges(edges: dict[str, float]) -> list[dict]:
    """Gauge bands from threshold edges (any units); non-rising edges are dropped."""
    cuts = []
    for key, label, colour in BANDS:
        value = edges.get(key)
        if value is None or (cuts and value <= cuts[-1][0]):
            continue
        cuts.append((value, label, colour))
    if not cuts:
        return []

    bottom = ("Low", ui.Colour.grey) if cuts[0][1] == "Normal" else ("Normal", ui.Colour.green)
    ranges = [ui.Range(bottom[0], 0, cuts[0][0], bottom[1])]
    for i, (value, label, colour) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else value * TOP_BAND_FACTOR
        ranges.append(ui.Range(label, value, end, colour))
    return [r.to_dict() for r in ranges]
