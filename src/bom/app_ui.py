"""Device page UI: river level and rainfall side by side for one location."""

from pathlib import Path

from pydoover import ui
from pydoover.ui import Colour, Range

from .app_tags import BomTags as T

# BOM / WMO rain-rate classes (mm/h), scaled to each value's period.
RAIN_RATE_CLASSES = (
    ("Light", 0, 2.5, Colour.limegreen),
    ("Moderate", 2.5, 10, Colour.yellow),
    ("Heavy", 10, 50, Colour.orange),
    ("Violent", 50, 100, Colour.red),
)


def rain_ranges(hours: float) -> list[Range]:
    return [Range(label, lo * hours, hi * hours, c) for label, lo, hi, c in RAIN_RATE_CLASSES]


class BomUI(ui.UI):
    river_level = ui.NumericVariable(
        "River Level",
        value=T.river_level,
        precision=2,
        units="m",
        icon="water",
        ranges=T.river_ranges,
    )
    river_flood_class = ui.TextVariable(
        "Flood Class", value=T.river_flood_class, icon="house-flood-water"
    )
    river_trend = ui.TextVariable("River Trend", value=T.river_trend, icon="arrow-trend-up")
    river_level_time = ui.Timestamp(
        "River Reading", value=T.river_level_time, precision="minute", icon="clock"
    )

    rain_since_9am = ui.NumericVariable(
        "Rain Since 9am", value=T.rain_since_9am, precision=1, units="mm", icon="droplet"
    )
    rain_last_hour = ui.NumericVariable(
        "Rain Last Hour",
        value=T.rain_last_hour,
        precision=1,
        units="mm",
        icon="cloud-showers-heavy",
        ranges=rain_ranges(1),
    )
    rain_15min = ui.NumericVariable(
        "Rain Last 15 min",
        value=T.rain_15min,
        precision=1,
        units="mm",
        icon="cloud-rain",
        ranges=rain_ranges(0.25),
    )
    rain_time = ui.Timestamp(
        "Rain Reading", value=T.rain_time, precision="minute", icon="clock"
    )

    details = ui.Submodule(
        "Details",
        children=[
            ui.TextVariable("River Level Datum", value=T.river_datum, icon="ruler-vertical"),
            ui.TextVariable("Status", value=T.status, icon="circle-info"),
        ],
    )


def export() -> None:
    BomUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "bom",
    )
