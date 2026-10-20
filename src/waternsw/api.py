"""WaterNSW Water Data API: live readings from NSW stream gauges.

The same data WaterInsights shows, through the developer portal at
api-portal.waternsw.com.au. Requests need a subscription key; the free Basic
tier allows 29 requests a day and 5 a minute, and every page of a response
counts as one.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DEFAULT_URL = "https://api.waternsw.com.au/water"
# Timestamps in requests and responses are AEST, all year round.
AEST = timezone(timedelta(hours=10))
TIME_FORMAT = "%d-%b-%Y %H:%M"
MAX_SITES = 20  # per request
# Instantaneous data can only be asked for back this far.
MAX_SPAN = timedelta(hours=168)
FETCH_TIMEOUT = 30
# Basic allows 5 requests a minute; pages of one fetch are spaced to suit.
PAGE_PAUSE = 12.5
NO_DATA = "No data found"


class WaterNswError(Exception):
    pass


def format_time(t: datetime) -> str:
    return t.astimezone(AEST).strftime(TIME_FORMAT)


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, TIME_FORMAT).replace(tzinfo=AEST)


def _get(url: str, key: str, timeout: float) -> dict:
    # Page links come back with literal spaces in their timestamps.
    request = urllib.request.Request(
        url.replace(" ", "%20"), headers={"Ocp-Apim-Subscription-Key": key}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if NO_DATA in body:
            return {}
        try:
            detail = json.loads(body)
            message = "; ".join(
                err.get("description") or err.get("message") or ""
                for err in detail.get("errors") or []
            ) or detail.get("message") or detail.get("responseMessage")
        except ValueError:
            message = body[:200]
        raise WaterNswError(f"HTTP {e.code}: {message}") from e


def fetch_since(
    key: str,
    sites: list[str],
    since: datetime,
    url: str = DEFAULT_URL,
    timeout: float = FETCH_TIMEOUT,
    pause: float = PAGE_PAUSE,
) -> tuple[list[dict], dict[str, str]]:
    """(records, quality code descriptions) loaded since `since`, for up to 20 sites.

    `dataSince` asks for what reached WaterNSW after that time, so late
    telemetry still comes through on the next fetch. Every page is followed.
    """
    query = urllib.parse.urlencode(
        {
            "siteId": ",".join(sites),
            "frequency": "Instantaneous",
            "dataType": "AutoQC",
            "dataSince": format_time(since),
            "pageNumber": 1,
        }
    )
    page = f"{url}/surface-water-data-api?{query}"
    records: list[dict] = []
    qualities: dict[str, str] = {}
    while page:
        body = _get(page, key, timeout)
        if body.get("responseMessage", "").startswith(NO_DATA):
            break
        records += body.get("records") or []
        qualities.update(body.get("qualities") or {})
        page = body.get("nextPageUrl") or None
        if page:
            time.sleep(pause)
    return records, qualities


def by_site(records: list[dict], qualities: dict[str, str]) -> dict[str, dict]:
    """The channel payload for each site: its series by variable, oldest first.

    {"site": id, "series": {variable: {"unit": u, "points": [[ms, value, quality], ...]}},
     "qualities": {code: description}}
    """
    sites: dict[str, dict] = {}
    points: dict[tuple[str, str], dict[int, list]] = defaultdict(dict)
    for r in records:
        site, variable = r["siteId"], r["variableName"]
        ms = int(parse_time(r["timeStamp"]).timestamp() * 1000)
        quality = r.get("qualityCode")
        points[site, variable][ms] = [ms, r.get("value"), quality]
        payload = sites.setdefault(site, {"site": site, "series": {}, "qualities": {}})
        payload["series"].setdefault(variable, {"unit": r.get("unitOfMeasure")})
        if quality in qualities:
            payload["qualities"][quality] = qualities[quality]
    for (site, variable), by_time in points.items():
        sites[site]["series"][variable]["points"] = [by_time[ms] for ms in sorted(by_time)]
    return sites
