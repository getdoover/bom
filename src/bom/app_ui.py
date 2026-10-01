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
    the rain series is the 15-minute total when the feed is 15-minute, else the
    last-hour total, `weather` shows the weather station section and `flow` the
    river flow values.
    """
    parts = []
    if config.river.station_id.value.strip() and tags.river_level.value is not None:
        parts.append("river")
        if tags.river_ranges.value:
            parts.append("radial")
    if config.rain.station_id.value.strip() and tags.rain_period_s.value is not None:
        parts.append("rain_15min" if tags.rain_period_s.value == 900 else "rain_last_hour")
    if config.weather.station_id.value.strip():
        parts.append("weather")
    if config.flow.station_id.value.strip():
        parts.append("flow")
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

    # Flow is published about a day behind, so its own timestamp sits beside it.
    river_flow = ui.NumericVariable(
        "River Flow", value=T.river_flow, precision=2, units="m³/s", icon="water"
    )
    river_flow_time = ui.Timestamp(
        "Flow As At", value=T.river_flow_time, precision="minute", icon="clock"
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

    weather = ui.Submodule(
        "Weather",
        children=[
            ui.NumericVariable(
                "Temperature", value=T.weather_temp, precision=1, units="°C", icon="temperature-half"
            ),
            ui.NumericVariable(
                "Feels Like", value=T.weather_apparent_temp, precision=1, units="°C", icon="person"
            ),
            ui.NumericVariable(
                "Humidity", value=T.weather_humidity, precision=0, units="%", icon="droplet"
            ),
            ui.NumericVariable(
                "Dew Point", value=T.weather_dew_point, precision=1, units="°C", icon="droplet"
            ),
            ui.NumericVariable(
                "Pressure", value=T.weather_pressure, precision=1, units="hPa", icon="gauge-high"
            ),
            ui.TextVariable("Wind Direction", value=T.weather_wind_dir, icon="compass"),
            ui.NumericVariable(
                "Wind Speed", value=T.weather_wind_speed, precision=0, units="km/h", icon="wind"
            ),
            ui.NumericVariable(
                "Wind Gust", value=T.weather_wind_gust, precision=0, units="km/h", icon="wind"
            ),
            ui.Timestamp(
                "Weather Reading", value=T.weather_time, precision="minute", icon="clock"
            ),
        ],
    )

    details = ui.Submodule(
        "Details",
        children=[
            ui.TextVariable("River Level Datum", value=T.river_datum, icon="ruler-vertical"),
            ui.TextVariable("Weather Station", value=T.weather_station, icon="tower-observation"),
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
        if "weather" in parts:
            series.append(
                ui.Series(
                    "Temperature",
                    value=T.weather_temp,
                    name="weather_temp",
                    data_type="number",
                    units="°C",
                    colour=Colour.tomato,
                    shared_axis=False,
                    active=False,
                )
            )
        else:
            self.remove_element("weather")
        if "flow" in parts:
            series.append(
                ui.Series(
                    "River Flow",
                    value=T.river_flow,
                    name="river_flow",
                    data_type="number",
                    units="m³/s",
                    colour=Colour.green,
                    shared_axis=False,
                    active=False,
                )
            )
        else:
            self.remove_element("river_flow")
            self.remove_element("river_flow_time")
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
