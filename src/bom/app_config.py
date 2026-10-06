"""Installation config: the BOM data sources to follow for this location."""

from pathlib import Path

from pydoover import config
from pydoover.config import NotSet
from pydoover.processor import ScheduleConfig

from .wdo import AS_RECORDED, DEFAULT_FLOW_UNIT, DEFAULT_URL, FLOW_UNITS, HOURLY_MEAN

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
    "protocol": "FTP",
    "host": "ftp.bom.gov.au",
    "username": "anonymous",
    "password": "",
    "private_key": "",
    "directory": "/anon/gen/fwo",
}
STALE_HELP = "Show a warning when the latest reading is older than this."
RIVER_DEFAULTS = {
    "station_id": "",
    "files": "ID{state}65911,ID{state}65910",
    "stale_after_hours": 6.0,
    "flood_levels": "BOM flood maps",
    "minor_flood_level": None,
    "moderate_flood_level": None,
    "major_flood_level": None,
}
FLOOD_HELP = "Flood classification level in the gauge's datum (m)."
RAIN_DEFAULTS = {"station_id": "", "files": "ID{state}65900", "stale_after_hours": 3.0}
WEATHER_DEFAULTS = {"station_id": "", "files": "ID{state}60920.xml", "stale_after_hours": 3.0}
FLOW_DEFAULTS = {
    "station_id": "",
    "display_units": DEFAULT_FLOW_UNIT,
    "series": HOURLY_MEAN,
    "service_url": DEFAULT_URL,
    "stale_after_hours": 72.0,
    "flow_ranges": "Gauge history",
    "low_flow_below": None,
    "high_flow_above": None,
}
FLOW_RANGE_HELP = "In the display units. Leave blank to take it from the gauge's history."
# Threshold name (see flowstats) -> RiverFlowSettings attribute holding its override.
FLOW_RANGE_FIELDS = {
    "low": "low_flow",
    "high": "high_flow",
}


def stale_after(default: float) -> config.Number:
    return config.Number(
        "Stale After (hours)", default=default, minimum=0.25, description=STALE_HELP, advanced=True
    )


uses_ftp = config.equal("protocol", "FTP")
uses_sftp = config.equal("protocol", "SFTP")


class FtpSettings(config.Object):
    protocol = config.Enum(
        "Protocol",
        choices=["FTP", "SFTP"],
        default=FTP_DEFAULTS["protocol"],
        description="FTP for ftp.bom.gov.au; SFTP (SSH key) for sftp-reg.cloud.bom.gov.au.",
    )
    host = config.String("Host", default=FTP_DEFAULTS["host"])
    username = config.String("Username", default=FTP_DEFAULTS["username"])
    password = config.String(
        "Password",
        default="",
        description="Leave blank for anonymous access.",
        show_if=uses_ftp,
    )
    private_key = config.String(
        "Private Key",
        default="",
        description="The SSH private key (PEM or OpenSSH format) registered with BOM.",
        show_if=uses_sftp,
    )
    directory = config.String("Directory", default=FTP_DEFAULTS["directory"])


manual = config.equal("flood_levels", "Manual")


class RiverLevelSettings(config.Object):
    station_id = config.String(
        "Station ID",
        default="",
        description="BOM river gauge number, e.g. 068212. Leave blank to skip.",
    )
    files = config.String(
        "Files", default=RIVER_DEFAULTS["files"], description=FILES_HELP, advanced=True
    )
    flood_levels = config.Enum(
        "Flood Levels",
        choices=["BOM flood maps", "Manual"],
        default=RIVER_DEFAULTS["flood_levels"],
        description=(
            "Where the minor / moderate / major flood levels come from. BOM has no river "
            "flood maps for WA or NT, so choose Manual there."
        ),
    )
    minor_flood_level = config.Number(
        "Minor Flood Level", default=None, description=FLOOD_HELP, show_if=manual
    )
    moderate_flood_level = config.Number(
        "Moderate Flood Level", default=None, description=FLOOD_HELP, show_if=manual
    )
    major_flood_level = config.Number(
        "Major Flood Level", default=None, description=FLOOD_HELP, show_if=manual
    )
    stale_after_hours = stale_after(RIVER_DEFAULTS["stale_after_hours"])


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
        advanced=True,
    )
    stale_after_hours = stale_after(RAIN_DEFAULTS["stale_after_hours"])


class WeatherStationSettings(config.Object):
    station_id = config.String(
        "Station ID",
        default="",
        description=(
            "BOM weather station number, e.g. 053115. Often the same as the rain gauge. "
            "Leave blank to skip."
        ),
    )
    files = config.String(
        "Files",
        default=WEATHER_DEFAULTS["files"],
        description=FILES_HELP + " Files must be BOM observation XML (the state IDx60920.xml).",
        advanced=True,
    )
    stale_after_hours = stale_after(WEATHER_DEFAULTS["stale_after_hours"])


manual_flow = config.equal("flow_ranges", "Manual")


class RiverFlowSettings(config.Object):
    station_id = config.String(
        "Station ID",
        default="",
        description=(
            "Water Data Online station number, e.g. 418001. This is the water agency's "
            "number for the gauge, usually different from the BOM river gauge number. "
            "Leave blank to skip. Flow is published about a day behind."
        ),
    )
    units = config.Enum(
        "Display Units",
        choices=list(FLOW_UNITS),
        default=FLOW_DEFAULTS["display_units"],
        description=(
            "Units the flow is shown and recorded in. Changing this later leaves "
            "earlier history in the old units."
        ),
        advanced=True,
    )
    series = config.Enum(
        "Series",
        choices=[HOURLY_MEAN, AS_RECORDED],
        default=FLOW_DEFAULTS["series"],
        description="Hourly mean, or the flow as recorded (usually every 15 minutes).",
        advanced=True,
    )
    url = config.String("Service URL", default=FLOW_DEFAULTS["service_url"], advanced=True)
    stale_after_hours = stale_after(FLOW_DEFAULTS["stale_after_hours"])
    ranges = config.Enum(
        "Flow Ranges",
        choices=["Gauge history", "Manual"],
        default=FLOW_DEFAULTS["flow_ranges"],
        description=(
            "Where the flow bands come from. Gauge history works them out from the "
            "station's own record (25th and 75th percentiles of daily flow). "
            "Manual shows the fields; any left blank still come from the history."
        ),
        advanced=True,
    )
    low_flow = config.Number(
        "Low Flow Below", default=None, description=FLOW_RANGE_HELP, show_if=manual_flow, advanced=True
    )
    high_flow = config.Number(
        "High Flow Above", default=None, description=FLOW_RANGE_HELP, show_if=manual_flow, advanced=True
    )


class BomConfig(config.Schema):
    state = config.Enum(
        "State",
        choices=list(STATES),
        default=NotSet,
        description="Selects the state's BOM files and the 9am rain-day time zone.",
    )
    river = RiverLevelSettings("River Level", default=RIVER_DEFAULTS)
    rain = RainfallSettings("Rainfall", default=RAIN_DEFAULTS)
    weather = WeatherStationSettings("Weather Station", default=WEATHER_DEFAULTS)
    flow = RiverFlowSettings("River Flow", default=FLOW_DEFAULTS)
    ftp = FtpSettings(
        "FTP Server",
        default=FTP_DEFAULTS,
        description="Defaults are BOM's public feed (15-minute data). Change for a Registered User feed.",
        advanced=True,
    )
    offline_after_minutes = config.Number(
        "Offline After (minutes)",
        default=120.0,
        minimum=15.0,
        description="Show the device offline if BOM has no new reading for this long.",
        advanced=True,
    )

    schedule = ScheduleConfig(
        allowed_modes=["rate", "cron"], default="rate(15 minutes)", advanced=True
    )
    position = config.ApplicationPosition()
    default_open = config.ApplicationDefaultOpen()


def export() -> None:
    BomConfig.export(Path(__file__).parents[2] / "doover_config.json", "bom")
