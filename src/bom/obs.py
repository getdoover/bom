"""Parse BOM state observation files (IDx60920.xml): the latest reading per weather station."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

# Observation field -> element type in the file. Speeds are km/h, pressure is
# mean sea level. Non-AWS stations report only some of these.
NUMBER_ELEMENTS = {
    "temp": "air_temperature",
    "apparent_temp": "apparent_temp",
    "dew_point": "dew_point",
    "humidity": "rel-humidity",
    "pressure": "msl_pres",
    "wind_speed": "wind_spd_kmh",
    "wind_gust": "gust_kmh",
}


@dataclass(frozen=True)
class Observation:
    station_id: str
    name: str
    time: datetime
    temp: float | None
    apparent_temp: float | None
    dew_point: float | None
    humidity: float | None
    pressure: float | None
    wind_dir: str | None  # compass point, e.g. "NNE"
    wind_speed: float | None
    wind_gust: float | None


def parse_observations(text: str) -> dict[str, Observation]:
    """{BOM station id: latest observation} for every station in the file."""
    result = {}
    for station in ET.fromstring(text).iter("station"):
        period = station.find("period")
        station_id = station.get("bom-id")
        if period is None or not period.get("time-utc") or not station_id:
            continue
        elements = {e.get("type"): (e.text or "").strip() for e in period.iter("element")}
        result[station_id] = Observation(
            station_id=station_id,
            name=station.get("stn-name") or station_id,
            time=datetime.fromisoformat(period.get("time-utc")),
            wind_dir=elements.get("wind_dir") or None,
            **{field: _number(elements.get(kind)) for field, kind in NUMBER_ELEMENTS.items()},
        )
    return result


def _number(text: str | None) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None
