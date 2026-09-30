"""Installation config: the BOM data sources to follow for this location."""

from pathlib import Path

from pydoover import config
from pydoover.processor import ScheduleConfig

# State -> (BOM product letter, UTC offset of local standard time). BOM rain
# days run 9am-9am local standard time, so daylight saving is ignored.
STATES = {
    "NSW / ACT": ("N", 10.0),
    "VIC": ("V", 10.0),
    "QLD": ("Q", 10.0),
    "TAS": ("T", 10.0),
    "SA": ("S", 9.5),
    "NT": ("D", 9.5),
    "WA": ("W", 8.0),
}

FILES_HELP = (
    "Comma-separated file name prefixes; the newest file for each is read. "
    "{state} becomes the state letter (N, V, Q, S, W, T, D)."
)

# Optional Objects only load their fields' defaults from the Object's own
# default, so each section's defaults are spelled out here as well.
FTP_DEFAULTS = {
    "host": "ftp.bom.gov.au",
    "username": "anonymous",
    "password": "",
    "directory": "/anon/gen/fwo",
}
RIVER_DEFAULTS = {
    "station_id": "",
    "files": "ID{state}65911,ID{state}65910",
    "minor_flood_level": None,
    "moderate_flood_level": None,
    "major_flood_level": None,
}
FLOOD_HELP = "BOM flood classification level for this gauge, in the gauge's datum (m). Optional."
RAIN_DEFAULTS = {"station_id": "", "files": "ID{state}65900"}


class FtpSettings(config.Object):
    host = config.String("Host", default=FTP_DEFAULTS["host"])
    username = config.String("Username", default=FTP_DEFAULTS["username"])
    password = config.String(
        "Password", default="", description="Leave blank for anonymous access."
    )
    directory = config.String("Directory", default=FTP_DEFAULTS["directory"])


class RiverLevelSettings(config.Object):
    station_id = config.String(
        "Station ID",
        default="",
        description="BOM river gauge number, e.g. 068212. Leave blank to skip.",
    )
    files = config.String("Files", default=RIVER_DEFAULTS["files"], description=FILES_HELP)
    minor_flood_level = config.Number("Minor Flood Level", default=None, description=FLOOD_HELP)
    moderate_flood_level = config.Number(
        "Moderate Flood Level", default=None, description=FLOOD_HELP
    )
    major_flood_level = config.Number("Major Flood Level", default=None, description=FLOOD_HELP)


class RainfallSettings(config.Object):
    station_id = config.String(
        "Station ID",
        default="",
        description="BOM rain gauge number. Often the same as the river gauge. Leave blank to skip.",
    )
    files = config.String(
        "Files",
        default=RAIN_DEFAULTS["files"],
        description=FILES_HELP + " Files must hold rainfall totals (e.g. 15-minute).",
    )


class BomConfig(config.Schema):
    state = config.Enum(
        "State",
        choices=list(STATES),
        default="NSW / ACT",
        description="Selects the state's BOM files and the 9am rain-day time zone.",
    )
    river = RiverLevelSettings("River Level", default=RIVER_DEFAULTS)
    rain = RainfallSettings("Rainfall", default=RAIN_DEFAULTS)
    ftp = FtpSettings(
        "FTP Server",
        default=FTP_DEFAULTS,
        description="Defaults are BOM's public feed (15-minute data). Change for a Registered User feed.",
    )
    offline_after_minutes = config.Number(
        "Offline After (minutes)",
        default=120.0,
        minimum=15.0,
        description="Show the device offline if BOM has no new reading for this long.",
    )

    schedule = ScheduleConfig(allowed_modes=["rate", "cron"], default="rate(15 minutes)")
    position = config.ApplicationPosition()
    default_open = config.ApplicationDefaultOpen()


def export() -> None:
    BomConfig.export(Path(__file__).parents[2] / "doover_config.json", "bom")
