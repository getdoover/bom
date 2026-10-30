"""Queensland's Water Monitoring Information Portal (WMIP): live Qld government gauges.

The department's Hydstra web service, keyed by the Qld gauge number (e.g.
120002D for the Burdekin at Sellheim, flood-warning number 533075). Gauges log
on the hour and again whenever the level moves, and telemetry comes in hourly,
so a reading can be up to about 90 minutes old. Levels are in local gauge
height, the same datum as the BOM flood-warning feed.

There is no key and no published quota, but the service guide asks for hourly
calls at hh:30 and warns that excessive or malformed calls get the caller's IP
blocked. Our processors share Lambda's outbound IPs, so the app polls hourly and
checks gauge numbers before sending them.
"""

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from .flowstats import HISTORY_YEARS, History
from .hcs import Reading
from .wdo import Flow

DEFAULT_URL = "https://water-monitoring.information.qld.gov.au/cgi/webservice.exe"
LEVEL = "100"  # stage, m gauge height
FLOW = "140"  # discharge, m³/s (rated from the stage)
# Hydstra's code for a missing value; anything else is a reading.
MISSING = 255
TIME_FORMAT = "%Y%m%d%H%M%S"
# Qld has no daylight saving; responses also say the site's offset.
AEST = timezone(timedelta(hours=10))
# A healthy call takes 4-6 seconds.
FETCH_TIMEOUT = 30
HISTORY_TIMEOUT = 60
GAUGE_NUMBER = re.compile(r"^\d{6}[A-Z]?$")


class WmipError(Exception):
    pass


def valid_gauge(site: str) -> bool:
    """A Qld gauge number: six digits and an optional letter, e.g. 120002D."""
    return bool(GAUGE_NUMBER.match(site))


def fetch_levels(url: str, site: str, start: datetime, end: datetime) -> list[Reading]:
    """Every level the gauge logged between start and end, oldest first."""
    points = _points(_traces(url, site, "AT", LEVEL, LEVEL, start, end, "minute", "point"))
    return [Reading(site, "WL", t, v, "metres", "LGH", None) for t, v in points]


def fetch_flows(url: str, site: str, start: datetime, end: datetime) -> list[Flow]:
    """Flow (m³/s) at each logged level between start and end, oldest first."""
    points = _points(_traces(url, site, "AT", LEVEL, FLOW, start, end, "minute", "point"))
    return [Flow(t, v) for t, v in points]


def fetch_history(url: str, site: str, years: int = HISTORY_YEARS) -> History:
    """Daily mean flow for the last *years*: stored discharge, gaps filled by rating."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    trace = _traces(url, site, "ATQ", FLOW, FLOW, start, end, "day", "mean", HISTORY_TIMEOUT)
    return History(mean_flow={t.date(): v for t, v in _points(trace)})


def _traces(
    url: str,
    site: str,
    datasource: str,
    varfrom: str,
    varto: str,
    start: datetime,
    end: datetime,
    interval: str,
    data_type: str,
    timeout: float = FETCH_TIMEOUT,
) -> dict:
    if not valid_gauge(site):
        raise WmipError(f"Not a Qld gauge number: {site!r}")
    body = json.dumps(
        {
            "function": "get_ts_traces",
            "version": "2",
            "params": {
                "site_list": site,
                "datasource": datasource,
                "varfrom": varfrom,
                "varto": varto,
                "start_time": start.astimezone(AEST).strftime(TIME_FORMAT),
                "end_time": end.astimezone(AEST).strftime(TIME_FORMAT),
                "interval": interval,
                "multiplier": "1",
                "data_type": data_type,
            },
        }
    ).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "User-Agent": "doover-bom/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_trace(json.load(response))


def parse_trace(response: dict) -> dict:
    """The single trace in a get_ts_traces response. Raises WmipError on a service error."""
    if response.get("error_num"):
        raise WmipError(response.get("error_msg") or f"WMIP error {response['error_num']}")
    traces = (response.get("return") or {}).get("traces") or []
    if not traces:
        raise WmipError("WMIP returned no trace")
    trace = traces[0]
    if trace.get("error_num"):
        raise WmipError(trace.get("error_msg") or f"WMIP error {trace['error_num']}")
    return trace


def _points(trace: dict) -> list[tuple[datetime, float]]:
    """(time, value) points oldest first, without missing values."""
    try:
        offset = timezone(timedelta(hours=float(trace["site_details"]["timezone"])))
    except (KeyError, TypeError, ValueError):
        offset = AEST
    points = {}
    for p in trace.get("trace") or []:
        if p.get("q") == MISSING:
            continue
        try:
            value = float(p["v"])
            time = datetime.strptime(str(p["t"]), TIME_FORMAT).replace(tzinfo=offset)
        except (KeyError, TypeError, ValueError):
            continue
        points[time.astimezone(timezone.utc)] = value
    return sorted(points.items())
