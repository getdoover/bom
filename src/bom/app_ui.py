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


def layout(config, tags) -> str:
    """Which optional parts the UI shows, from the configured stations and their data.

    `river` plots the level, `radial` shows it as a gauge (it has flood bands),
    and the rain series is the 15-minute total when the feed is 15-minute, else
    the last-hour total.
    """
    parts = []
    if config.river.station_id.value.strip() and tags.river_level.value is not None:
        parts.append("river")
        if tags.river_ranges.value:
            parts.append("radial")
    if config.rain.station_id.value.strip() and tags.rain_period_s.value is not None:
        parts.append("rain_15min" if tags.rain_period_s.value == 900 else "rain_last_hour")
    return ",".join(parts)


class BomUI(ui.UI):
    # Series are added in setup(), once it is known which data this device has.
    overview = ui.Multiplot("Overview", series=[])

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


    async def setup(self) -> None:
        parts = layout(self.config, self.tags).split(",")
        if "radial" in parts:
            self.river_level.form = ui.Widget.radial

        series = []
        if "river" in parts:
            series.append(
                ui.Series(
                    "River Level",
                    value=T.river_level,
                    name="river_level",
                    data_type="number",
                    units="m",
                    colour=Colour.blue,
                    ranges=T.river_ranges,
                    active=True,
                )
            )
        rain = next((p for p in parts if p.startswith("rain_")), None)
        if rain:
            series.append(
                ui.Series(
                    "Rain Last 15 min" if rain == "rain_15min" else "Rain Last Hour",
                    value=getattr(T, rain),
                    name=rain,
                    data_type="number",
                    units="mm",
                    colour=Colour.purple,
                    shared_axis=False,
                    active=True,
                )
            )
        if series:
            self.overview.series = series
            if "radial" in parts:
                self.overview.default_range_view = "zone"
        else:
            self.remove_element("overview")


def export() -> None:
    BomUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "bom",
    )
