"""Queensland's Water Monitoring Information Portal: live readings from its gauges.

The portal (water-monitoring.information.qld.gov.au) is a Kisters Hydstra
install whose JSON web service is open to anonymous callers under CC BY 4.0.
Gauges log and transmit hourly; the department asks for time-series calls no
more often than hourly, at half past, and blocks addresses that abuse the
service. There is no key and no documented rate limit.

A call is the JSON request, URL-encoded, as the whole query string. Times in
requests and responses are the gauge's local time (Queensland has no daylight
saving, so AEST) as YYYYMMDDHHMMSS.
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_URL = "https://water-monitoring.information.qld.gov.au/cgi/webservice.exe"
DATASOURCE = "TE"  # telemetry: what the gauge sent, as yet unverified
MAX_SITES = 50  # per request; the service sets no documented limit
FETCH_TIMEOUT = 60
TIME_FORMAT = "%Y%m%d%H%M%S"
AEST = timezone(timedelta(hours=10))
MISSING = 255  # Hydstra quality code for no value

# Series name in the live payload -> (varfrom, varto). The portal rates stage
# to discharge on the fly; 141.00 asks for it in megalitres a day, the unit
# the BoM Station already converts from.
VARIABLES = {
    "StreamWaterLevel": ("100.00", "100.00"),
    "FlowRate": ("100.00", "141.00"),
    "Rainfall": ("10.00", "10.00"),
}
# The portal's unit names -> the ones the BoM Station knows.
UNITS = {"Metres": "m", "Megalitres/Day": "ML/day", "Cumecs": "m3/s", "millimetres": "mm"}


class QldWaterError(Exception):
    pass


@dataclass
class Trace:
    site: str
    variable: str  # series name in the live payload
    unit: str | None
    points: list[list]  # [ms, value, quality], oldest first
    qualities: dict[str, str]  # quality code -> description


def format_time(t: datetime) -> str:
    return t.astimezone(AEST).strftime(TIME_FORMAT)


def parse_time(t: int | str, utc_offset_hours: float) -> datetime:
    tz = timezone(timedelta(hours=utc_offset_hours))
    return datetime.strptime(str(t), TIME_FORMAT).replace(tzinfo=tz)


def call(url: str, function: str, version: str, params: dict, timeout: float) -> dict:
    """The `return` of a web service call; raises QldWaterError on a service error."""
    request = json.dumps(
        {"function": function, "version": version, "params": params}, separators=(",", ":")
    )
    req = urllib.request.Request(
        f"{url}?{urllib.parse.quote(request)}", headers={"User-Agent": "doover-bom/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
    if body.get("error_num"):
        raise QldWaterError(f"{function}: {body.get('error_msg') or body['error_num']}")
    return body.get("return") or {}


def fetch_since(
    sites: list[str],
    since: datetime,
    url: str = DEFAULT_URL,
    timeout: float = FETCH_TIMEOUT,
) -> tuple[list[Trace], dict[str, str]]:
    """(traces, {site: why the portal gave nothing}) for level, flow and rain since `since`.

    One request per variable covers every site. A site is reported only when
    no variable came back for it, since a gauge without a rating still has a
    level; a site the portal leaves out of its answer altogether is reported
    too.
    """
    now = datetime.now(timezone.utc)
    base = {
        "site_list": ",".join(sites),
        "datasource": DATASOURCE,
        "start_time": format_time(since),
        "end_time": format_time(now + timedelta(hours=1)),
        "data_type": "point",
        "interval": "default",
        "multiplier": "1",
    }
    traces: list[Trace] = []
    errors: dict[str, str] = {}
    answered: set[str] = set()
    for name, (varfrom, varto) in VARIABLES.items():
        result = call(url, "get_ts_traces", "2", {**base, "varfrom": varfrom, "varto": varto}, timeout)
        for raw in result.get("traces") or []:
            site = raw.get("site", "")
            if raw.get("error_num"):
                errors.setdefault(site, raw.get("error_msg") or f"error {raw['error_num']}")
                continue
            answered.add(site)
            traces.append(parse_trace(raw, name))
    return traces, {s: errors.get(s, "Not in the portal's answer") for s in sites if s not in answered}


def parse_trace(raw: dict, variable: str) -> Trace:
    """One site's trace from a get_ts_traces response; missing values are dropped."""
    offset = float((raw.get("site_details") or {}).get("timezone") or 10.0)
    unit = (raw.get("varto_details") or {}).get("units")
    points: dict[int, list] = {}
    for p in raw.get("trace") or []:
        quality = int(p.get("q", MISSING))
        if quality >= MISSING:
            continue
        try:
            value = float(p["v"])
        except (KeyError, TypeError, ValueError):
            continue
        ms = int(parse_time(p["t"], offset).timestamp() * 1000)
        points[ms] = [ms, value, str(quality)]
    return Trace(
        site=raw.get("site", ""),
        variable=variable,
        unit=UNITS.get(unit, unit),
        points=[points[ms] for ms in sorted(points)],
        qualities={str(k): v for k, v in (raw.get("quality_codes") or {}).items()},
    )


def by_site(traces: list[Trace]) -> dict[str, dict]:
    """The channel payload for each site that has readings, in the live.py shape:

    {"site": id, "series": {variable: {"unit": u, "points": [[ms, value, quality], ...]}},
     "qualities": {code: description}}
    """
    sites: dict[str, dict] = {}
    for t in traces:
        if not t.points:
            continue
        payload = sites.setdefault(t.site, {"site": t.site, "series": {}, "qualities": {}})
        payload["series"][t.variable] = {"unit": t.unit, "points": t.points}
        payload["qualities"].update(t.qualities)
    return sites
