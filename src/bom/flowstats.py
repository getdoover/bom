"""Flow bands for a gauge, worked out from its own Water Data Online record.

Percentiles of the daily mean discharge give the low / normal / high / very
high bands, and the days the river stood at a flood level give the flow that
level corresponds to, where the record has such days. Nothing is interpolated:
a threshold the record cannot support is simply left out.
"""

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pydoover import ui

from .wdo import DISCHARGE, LEVEL, TO_CUMEC, fetch_series, list_procedures

HISTORY_YEARS = 16
MIN_DAYS = 3 * 365  # record needed before percentiles mean much
PERCENTILES = {"low": 10, "high": 90, "very_high": 99}
FLOOD_NAMES = ("minor", "moderate", "major")
LEVEL_TOLERANCE_M = 0.15  # a day counts as "at" a flood level within this
MIN_FLOOD_DAYS = 2

# Threshold -> the band that starts there. Order matters: bands must rise.
BANDS = (
    ("low", "Normal", ui.Colour.green),
    ("high", "High", ui.Colour.blue),
    ("very_high", "Very High", ui.Colour.purple),
    ("minor", "Minor Flood", ui.Colour.yellow),
    ("moderate", "Moderate Flood", ui.Colour.orange),
    ("major", "Major Flood", ui.Colour.red),
)


@dataclass
class History:
    mean_flow: dict[date, float]  # m³/s
    max_flow: dict[date, float]
    max_level: dict[date, float]  # m, gauge datum


def fetch_history(url: str, station_id: str, years: int = HISTORY_YEARS) -> History:
    """Daily mean and maximum flow, and daily maximum level, for the last *years*."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)

    def daily(parameter: str, suffix: str, to_cumec: bool) -> dict[date, float]:
        procedures = [p for p in list_procedures(url, station_id, parameter) if p.endswith(suffix)]
        if not procedures:
            return {}
        unit, points = fetch_series(url, station_id, parameter, procedures[0], start, end)
        scale = 1.0
        if to_cumec:
            if unit not in TO_CUMEC:
                raise ValueError(f"Unexpected discharge unit {unit!r}")
            scale = TO_CUMEC[unit]
        return {t.date(): v * scale for t, v in points}

    return History(
        mean_flow=daily(DISCHARGE, "_C_B_1_DailyMean", True),
        max_flow=daily(DISCHARGE, "_C_B_1_DailyMax", True),
        max_level=daily(LEVEL, "_C_B_1_DailyMax", False),
    )


def thresholds(history: History, flood_levels: list[float | None]) -> dict[str, float]:
    """Band edges in m³/s that the record supports, plus the record maximum."""
    result: dict[str, float] = {}
    flows = sorted(history.mean_flow.values())
    if len(flows) >= MIN_DAYS:
        for name, pct in PERCENTILES.items():
            result[name] = flows[round(pct / 100 * (len(flows) - 1))]
    peak = max(history.max_flow.values(), default=None)
    if peak is None and flows:
        peak = flows[-1]
    if peak is not None:
        result["max"] = peak

    days = history.max_level.keys() & history.max_flow.keys()
    for name, level in zip(FLOOD_NAMES, flood_levels):
        if level is None:
            continue
        at_level = [
            history.max_flow[d] for d in days if abs(history.max_level[d] - level) <= LEVEL_TOLERANCE_M
        ]
        flow = statistics.median(at_level) if len(at_level) >= MIN_FLOOD_DAYS else None
        # A flood flow below the high-flow percentile means the levels don't
        # belong to this record (wrong gauge or datum); leave it out.
        if flow is not None and flow > result.get("high", 0):
            result[name] = flow
    return result


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

    # The record maximum closes the top band; 1.5x the last edge if there is
    # none above it.
    top = edges.get("max") or 0
    if top <= cuts[-1][0]:
        top = cuts[-1][0] * 1.5
    bottom = ("Low", ui.Colour.grey) if cuts[0][1] == "Normal" else ("Normal", ui.Colour.green)
    ranges = [ui.Range(bottom[0], 0, cuts[0][0], bottom[1])]
    for i, (value, label, colour) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else top
        ranges.append(ui.Range(label, value, end, colour))
    return [r.to_dict() for r in ranges]
