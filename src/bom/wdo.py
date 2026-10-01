"""Fetch river discharge from BOM's Water Data Online (OGC SOS2, WaterML2 responses).

Water Data Online republishes the state water agencies' gauges, so stations are
keyed by the agency's number (e.g. 418001), not the flood-warning number the
HCS feed uses for the same gauge. Data is typically published a day behind.
"""

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

DEFAULT_URL = "https://www.bom.gov.au/waterdata/services"
SERVICES = "http://bom.gov.au/waterdata/services"
DISCHARGE = "Water Course Discharge"
HOURLY_MEAN = "Pat4_C_B_1_HourlyMean"
AS_RECORDED = "Pat4_C_B_1"

WML2 = "{http://www.opengis.net/waterml/2.0}"
OWS = "{http://www.opengis.net/ows/1.1}"

# Discharge is published in cumec; convert if a station reports megalitres/day.
TO_CUMEC = {None: 1.0, "cumec": 1.0, "m3/s": 1.0, "ML/d": 1000 / 86400, "ML/day": 1000 / 86400}


@dataclass(frozen=True)
class Flow:
    time: datetime
    value: float  # m³/s


def fetch_discharge(
    url: str,
    station_id: str,
    procedure: str,
    start: datetime,
    end: datetime,
    timeout: float = 60,
) -> list[Flow]:
    params = {
        "service": "SOS",
        "version": "2.0",
        "request": "GetObservation",
        "featureOfInterest": f"{SERVICES}/stations/{station_id}",
        "procedure": f"{SERVICES}/tstypes/{procedure}",
        "observedProperty": f"{SERVICES}/parameters/{DISCHARGE}",
        "temporalFilter": f"om:phenomenonTime,{_iso(start)}/{_iso(end)}",
    }
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "doover-bom/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_discharge(response.read().decode("utf-8"))


def parse_discharge(text: str) -> list[Flow]:
    """Discharge points in m³/s, oldest first. Raises ValueError on a service error."""
    root = ET.fromstring(text)
    error = root.find(f".//{OWS}ExceptionText")
    if error is not None:
        raise ValueError(error.text or "Water Data Online returned an error")

    uom = root.find(f".//{WML2}uom")
    unit = uom.get("code") if uom is not None else None
    if unit not in TO_CUMEC:
        raise ValueError(f"Unexpected discharge unit {unit!r}")
    scale = TO_CUMEC[unit]

    points = {}
    for tvp in root.iter(f"{WML2}MeasurementTVP"):
        try:
            value = float(tvp.findtext(f"{WML2}value"))
        except (TypeError, ValueError):
            continue  # the series' end marker has an empty value
        time = datetime.fromisoformat(tvp.findtext(f"{WML2}time"))
        points[time] = Flow(time, value * scale)
    return sorted(points.values(), key=lambda f: f.time)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
