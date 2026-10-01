# BoM Station

A Doover processor that records Bureau of Meteorology (BOM) data for one
location. Every 15 minutes it downloads the newest BOM files from FTP, keeps the
configured stations, and writes each reading into history at its BOM
observation time.

## Data sources

| Section | Values | BOM files (public feed) |
| --- | --- | --- |
| River Level | Level (m), trend, flood class, datum (`AHD` or `LGH` local gauge height) | `IDx65911` (15-min readings, last ~3 h) + `IDx65910` (latest) |
| Rainfall | Last 15 min, last hour, since 9am (mm) | `IDx65900` (15-min totals, last ~2 h) |
| Weather Station | Temperature, feels like, humidity, dew point, pressure, wind direction / speed / gust | `IDx60920.xml` (latest ~10-min observation per station) |
| River Flow | Flow (ML/day by default) with its own "as at" time | Water Data Online SOS2 API over HTTPS, not FTP (see below) |

Each section takes a BOM station number (e.g. `068212`); leave it blank to skip
that source. Many sites use the same number for river and rain, and the rain
gauge is often also the weather station (e.g. Moree Aero, `053115`). The
observation file only carries each station's latest reading, so weather history
is one point per run.

**River Flow** is different: it comes from BOM's Water Data Online, which
republishes the state water agencies' gauges, so the station number is the
agency's (e.g. `418001` for Gwydir River at Pallamallawa, whose flood-warning
number is `553000`). Look it up at
[bom.gov.au/waterdata](http://www.bom.gov.au/waterdata/). Flow is derived from
level through the agency's rating curve and is published about a day behind, so
the UI shows it with its own timestamp and it does not count towards the device
being online unless it is the only source. The default series is the hourly
mean; the first run backfills a week. BOM publishes flow in m³/s; **Display
Units** (advanced) converts it when recorded, to ML/day by default, or m³/s,
L/s or GL/day. History already recorded stays in the units of the time, so
pick the unit before the first run where possible.

The flow's bands come from the gauge's own record by default (**Flow Ranges:
Gauge history**): the app reads up to 16 years of daily flow and level from
Water Data Online once a month (a few requests of ~1 MB) and takes the 10th /
90th / 99th percentiles as the Low / Normal / High / Very High edges, and the
median flow on the days the river stood at each flood level as the Minor /
Moderate / Major Flood edges. A flood level the record never reached is left
out rather than extrapolated, and a record under three years gives no
percentile bands. **Manual** shows the six edges (in the display units); any
left blank still come from the history. River Level's minor /
moderate / major flood levels drive the flood class and the level gauge's colour
bands. By default (**Flood Levels: BOM flood maps**) they come from BOM's
flood-warning maps (the `IDx65xxx.html` pages on the public FTP feed): the
processor finds the gauge's page once, then re-reads just that page daily. WA and
NT have no river map pages, so choose **Manual** there to show and fill in the
level fields. **State** picks the
state's files (`x` above) and the 9am rain-day time zone.

**FTP Server** (advanced) defaults to BOM's public feed (`ftp.bom.gov.au`,
`/anon/gen/fwo`). For a Registered User (5-minute) feed:

| BOM service | Protocol | Login | Supported |
| --- | --- | --- | --- |
| Plain FTP, `ftp.bom.gov.au` | FTP | User ID + password | Yes |
| Cloud-SFTP, `sftp-reg.cloud.bom.gov.au` | SFTP | User ID + SSH private key | Yes |
| Cloud-FTP, `ftp-reg.cloud.bom.gov.au` | FTP | User ID + password + whitelisted IP | No: processors run on Lambda, which has no fixed outbound IP |

Set the directory and each section's file prefixes to match the feed. SFTP
accepts the server's host key on first connect (no key is pinned).

BOM keeps only a few hours of files, so a gap longer than that (e.g. the
processor disabled) is not backfilled, and the since-9am total undercounts for
that day.

Each section has an advanced **Stale After (hours)** setting; a warning shows
at the top of the page once that source's latest reading is older than it
(defaults: river level 6 h, rain 3 h, weather 3 h, river flow 72 h, as flow
is published a day behind). A warning also shows while the river is at or
above its minor flood level.

## Adding a data source

Add a config section in `app_config.py`, tags and UI elements for its values,
and a step in `Bom.refresh()`. `ftp.download_latest` fetches the newest file
for any prefix; `hcs.py` parses the flood-warning (BOM-HCS) format, `obs.py` the
observation XML, `wdo.py` fetches Water Data Online discharge, and
`floodmap.py` reads flood levels from the map pages.

## BoM FWIN Dashboard

A second app in this repo, `bom_dashboard`, gives an area (e.g. a council) one
page across its gauges. Install it on a Dashboard device and grant it the
group holding the gauges (extended permissions). Its widget (`widget/`) shows:

- flood status (worst flood class across the gauges), rivers rising, the
  wettest gauge since 9am, and how many gauges are reporting;
- a card per gauge: level, trend, flood class, the level against its flood
  bands, the last 7 days of level, and rain for the last hour and since 9am.

It reads each device's BoM Station install (found by application
name), so the gauges need no extra setup.

## Possible future data sources

Also on BOM's public FTP feed (`/anon/gen/fwo`), not yet used here:

| Data | Files | Would add |
| --- | --- | --- |
| Town forecasts | `IDx11xxx.xml` / `IDx10xxx.xml` precis forecasts (e.g. `IDQ11295`, `IDN11060`) | 7-day min/max, chance of rain, rain range, summary text |
| Warnings | `IDx2xxxx.cap.xml` (CAP format) | Flood, severe thunderstorm and wind warnings for the area; notifications when issued |
| Rain and level history | Water Data Online SOS2 API (HTTPS), as River Flow uses | Years of history to backfill a new device |

A notification when a gauge's flood class changes would build on the existing
River Level data.

## Development

```bash
uv sync
uv run pytest
sh build.sh
```
