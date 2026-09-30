"""Parse BOM flood-warning observation files (BOM-HCS format)."""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Reading:
    station_id: str
    kind: str  # "WL" river level, "RN" rainfall
    time: datetime
    value: float
    unit: str
    datum: str  # WL only: "AHD" or "LGH" (local gauge height)
    period_s: int | None  # RN only: accumulation period in seconds


def parse_hcs(text: str) -> list[Reading]:
    readings = []
    lines = (ln for ln in text.splitlines() if ln and not ln.startswith("#"))
    for row in csv.reader(lines):
        if len(row) < 10 or row[6] == "":
            continue
        try:
            time = datetime.fromisoformat(row[5].replace("Z", "+00:00"))
            value = float(row[6])
        except ValueError:
            continue
        readings.append(
            Reading(
                station_id=row[4],
                kind=row[1],
                time=time,
                value=value,
                unit=row[7],
                datum=row[8],
                period_s=int(row[9]) if row[9].isdigit() else None,
            )
        )
    return readings


def unique_readings(readings) -> list[Reading]:
    """De-duplicate on (station, kind, time) across overlapping files, oldest first."""
    found = {(r.station_id, r.kind, r.time): r for r in readings}
    return sorted(found.values(), key=lambda r: r.time)


def level_trend(levels: list[Reading], threshold_m: float = 0.01) -> str | None:
    """Rising / falling / steady, comparing the latest level with ~1 hour earlier."""
    if len(levels) < 2:
        return None
    latest = levels[-1]
    earlier = [r for r in levels if r.time <= latest.time - timedelta(minutes=45)]
    base = earlier[-1] if earlier else levels[0]
    change = latest.value - base.value
    if change > threshold_m:
        return "rising"
    if change < -threshold_m:
        return "falling"
    return "steady"


def flood_class(level: float, levels: list[float | None]) -> str | None:
    """Minor / Moderate / Major, from (minor, moderate, major) flood levels."""
    names = ("Minor", "Moderate", "Major")
    set_levels = [(n, v) for n, v in zip(names, levels) if v is not None]
    if not set_levels:
        return None
    reached = [n for n, v in set_levels if level >= v]
    return reached[-1] if reached else "Below flood level"


def rain_day(time: datetime, utc_offset_hours: float) -> str:
    """The BOM rain day (9am to 9am local standard time) a reading falls in.

    A reading stamped exactly 09:00 closes the previous day's total.
    """
    local = time.astimezone(timezone(timedelta(hours=utc_offset_hours)))
    return (local - timedelta(hours=9, microseconds=1)).date().isoformat()
