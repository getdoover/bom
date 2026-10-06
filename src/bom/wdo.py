"""Fetch river discharge from BOM's Water Data Online (OGC SOS2, WaterML2 responses).

Water Data Online republishes the state water agencies' gauges, so stations are
keyed by the agency's number (e.g. 418001), not the flood-warning number the
HCS feed uses for the same gauge. Data is typically published a day behind.
"""

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

DEFAULT_URL = "https://www.bom.gov.au/waterdata/services"
SERVICES = "http://bom.gov.au/waterdata/services"
DISCHARGE = "Water Course Discharge"
LEVEL = "Water Course Level"
HOURLY_MEAN = "Pat4_C_B_1_HourlyMean"
AS_RECORDED = "Pat4_C_B_1"

# A healthy response takes about a second. Every scheduled run makes the
# discharge request, so give up well before the Lambda's own limit when the
# service hangs; the big history pulls (years of daily data) get longer.
FETCH_TIMEOUT = 20
HISTORY_TIMEOUT = 60

WML2 = "{http://www.opengis.net/waterml/2.0}"
OWS = "{http://www.opengis.net/ows/1.1}"

# Discharge is published in cumec; convert if a station reports megalitres/day.
TO_CUMEC = {None: 1.0, "cumec": 1.0, "m3/s": 1.0, "ML/d": 1000 / 86400, "ML/day": 1000 / 86400}

# Display unit -> (multiplier from m³/s, decimal places shown).
FLOW_UNITS = {
    "ML/day": (86.4, 1),
    "m³/s": (1.0, 2),
    "L/s": (1000.0, 0),
    "GL/day": (0.0864, 3),
}
DEFAULT_FLOW_UNIT = "ML/day"


def convert_flow(cumec: float, unit: str) -> float:
    scale, precision = FLOW_UNITS[unit]
    return round(cumec * scale, precision + 2)


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
    timeout: float = FETCH_TIMEOUT,
) -> list[Flow]:
    return parse_discharge(_get_observation(url, station_id, DISCHARGE, procedure, start, end, timeout))


def fetch_series(
    url: str,
    station_id: str,
    parameter: str,
    procedure: str,
    start: datetime,
    end: datetime,
    timeout: float = HISTORY_TIMEOUT,
) -> tuple[str | None, list[tuple[datetime, float]]]:
    """(unit, points oldest first) for any parameter and time-series type."""
    return parse_timeseries(_get_observation(url, station_id, parameter, procedure, start, end, timeout))


def list_procedures(url: str, station_id: str, parameter: str, timeout: float = HISTORY_TIMEOUT) -> list[str]:
    """The time-series types (e.g. Pat4_C_B_1_DailyMean) the station publishes for a parameter."""
    text = _get(
        url,
        {
            "request": "GetDataAvailability",
            "featureOfInterest": f"{SERVICES}/stations/{station_id}",
        },
        timeout,
    )
    return parse_procedures(text, parameter)


def parse_procedures(text: str, parameter: str) -> list[str]:
    """Time-series types for *parameter* in a GetDataAvailability response."""
    # The parameter is a URL in an xlink:href attribute, so it ends at a quote.
    wanted = re.compile(re.escape(f"parameters/{parameter}") + r'["<]')
    found = []
    for member in re.findall(r"<gda:dataAvailabilityMember.*?</gda:dataAvailabilityMember>", text, re.S):
        if wanted.search(member):
            m = re.search(r"tstypes/([A-Za-z0-9_]+)", member)
            if m:
                found.append(m.group(1))
    return found


def parse_discharge(text: str) -> list[Flow]:
    """Discharge points in m³/s, oldest first. Raises ValueError on a service error."""
    unit, points = parse_timeseries(text)
    if unit not in TO_CUMEC:
        raise ValueError(f"Unexpected discharge unit {unit!r}")
    scale = TO_CUMEC[unit]
    return [Flow(time, value * scale) for time, value in points]


def parse_timeseries(text: str) -> tuple[str | None, list[tuple[datetime, float]]]:
    """(unit code, (time, value) points oldest first). Raises ValueError on a service error."""
    root = ET.fromstring(text)
    error = root.find(f".//{OWS}ExceptionText")
    if error is not None:
        raise ValueError(error.text or "Water Data Online returned an error")

    uom = root.find(f".//{WML2}uom")
    unit = uom.get("code") if uom is not None else None

    points = {}
    for tvp in root.iter(f"{WML2}MeasurementTVP"):
        try:
            value = float(tvp.findtext(f"{WML2}value"))
        except (TypeError, ValueError):
            continue  # the series' end marker has an empty value
        time = datetime.fromisoformat(tvp.findtext(f"{WML2}time"))
        points[time] = value
    return unit, sorted(points.items())


def _get_observation(url, station_id, parameter, procedure, start, end, timeout) -> str:
    return _get(
        url,
        {
            "request": "GetObservation",
            "featureOfInterest": f"{SERVICES}/stations/{station_id}",
            "procedure": f"{SERVICES}/tstypes/{procedure}",
            "observedProperty": f"{SERVICES}/parameters/{parameter}",
            "temporalFilter": f"om:phenomenonTime,{_iso(start)}/{_iso(end)}",
        },
        timeout,
    )


def _get(url: str, params: dict, timeout: float) -> str:
    query = urllib.parse.urlencode({"service": "SOS", "version": "2.0", **params})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "doover-bom/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
