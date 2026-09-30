# Bureau of Meteorology

A Doover processor that records Bureau of Meteorology (BOM) data for one
location. Every 15 minutes it downloads the newest BOM files from FTP, keeps the
configured stations, and writes each reading into history at its BOM
observation time.

## Data sources

| Section | Values | BOM files (public feed) |
| --- | --- | --- |
| River Level | Level (m), trend, flood class, datum (`AHD` or `LGH` local gauge height) | `IDx65911` (15-min readings, last ~3 h) + `IDx65910` (latest) |
| Rainfall | Last 15 min, last hour, since 9am (mm) | `IDx65900` (15-min totals, last ~2 h) |

Each section takes a BOM station number (e.g. `068212`); leave it blank to skip
that source. Many sites use the same number for both. River Level's minor /
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

## Adding a data source

Add a config section in `app_config.py`, tags and UI elements for its values,
and a step in `Bom.refresh()`. `ftp.download_latest` fetches the newest file
for any prefix; `hcs.py` parses the flood-warning (BOM-HCS) format, and `floodmap.py` reads
flood levels from the map pages.

## Development

```bash
uv sync
uv run pytest
sh build.sh
```
