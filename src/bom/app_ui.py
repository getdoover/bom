"""Device page UI: river level and rainfall side by side for one location."""

import hashlib
import json
from pathlib import Path

from pydoover import ui
from pydoover.ui import Colour, Range

from .app_tags import BomTags as T
from .wdo import FLOW_UNITS

# BOM / WMO rain-rate classes (mm/h), scaled to each value's period.
RAIN_RATE_CLASSES = (
    ("Light", 0, 2.5, Colour.limegreen),
    ("Moderate", 2.5, 10, Colour.yellow),
    ("Heavy", 10, 50, Colour.orange),
    ("Violent", 50, 100, Colour.red),
)


def rain_ranges(hours: float) -> list[Range]:
    return [Range(label, lo * hours, hi * hours, c) for label, lo, hi, c in RAIN_RATE_CLASSES]


# Daily totals (mm since 9am), after BOM's daily rainfall descriptors.
RAIN_DAY_RANGES = [
    Range("Light", 0, 10, Colour.limegreen),
    Range("Moderate", 10, 25, Colour.yellow),
    Range("Heavy", 25, 50, Colour.orange),
    Range("Very Heavy", 50, 100, Colour.red),
    Range("Extreme", 100, 200, Colour.magenta),
]
TEMP_RANGES = [
    Range("Cold", -10, 10, Colour.blue),
    Range("Mild", 10, 20, Colour.limegreen),
    Range("Warm", 20, 30, Colour.yellow),
    Range("Hot", 30, 37, Colour.orange),
    Range("Extreme", 37, 50, Colour.red),
]
HUMIDITY_RANGES = [
    Range("Dry", 0, 30, Colour.orange),
    Range("Comfortable", 30, 60, Colour.limegreen),
    Range("Humid", 60, 80, Colour.yellow),
    Range("Very Humid", 80, 100, Colour.blue),
]
# Dew point is the usual comfort measure; above ~20 °C feels muggy regardless of RH.
DEW_POINT_RANGES = [
    Range("Dry", -10, 10, Colour.limegreen),
    Range("Comfortable", 10, 16, Colour.green),
    Range("Humid", 16, 20, Colour.yellow),
    Range("Muggy", 20, 24, Colour.orange),
    Range("Oppressive", 24, 30, Colour.red),
]
PRESSURE_RANGES = [
    Range("Low", 960, 1000, Colour.orange),
    Range("Normal", 1000, 1025, Colour.limegreen),
    Range("High", 1025, 1050, Colour.blue),
]
# After BOM's wind warning thresholds: strong 48 km/h, gale 63, storm force 89.
WIND_RANGES = [
    Range("Light", 0, 20, Colour.limegreen),
    Range("Moderate", 20, 48, Colour.yellow),
    Range("Strong", 48, 63, Colour.orange),
    Range("Gale", 63, 89, Colour.red),
    Range("Storm", 89, 150, Colour.magenta),
]


def layout(config, tags) -> str:
    """Which optional parts the UI shows, from the configured stations and their data.

    `river` plots the level, `radial:<fingerprint>` shows it as a gauge (it has
    flood bands; the fingerprint changes with them, since the plot carries them
    literally), the rain series is the 15-minute total when the feed is
    15-minute, else the last-hour total, `weather` shows the weather station
    section and `flow:<units>:<fingerprint>` the river flow values in those
    units, with the fingerprint of its bands (carried literally, like the level's).
    """
    parts = []
    if config.river.station_id.value.strip() and tags.river_level.value is not None:
        parts.append("river")
        if tags.river_ranges.value:
            digest = hashlib.md5(json.dumps(tags.river_ranges.value, sort_keys=True).encode())
            parts.append(f"radial:{digest.hexdigest()[:8]}")
    if config.rain.station_id.value.strip() and tags.rain_period_s.value is not None:
        parts.append("rain_15min" if tags.rain_period_s.value == 900 else "rain_last_hour")
    if config.weather.station_id.value.strip():
        parts.append("weather")
    if config.flow.station_id.value.strip():
        digest = hashlib.md5(json.dumps(tags.river_flow_ranges.value or [], sort_keys=True).encode())
        parts.append(f"flow:{config.flow.units.value}:{digest.hexdigest()[:8]}")
    return ",".join(parts)


class BomUI(ui.UI):
    # Warnings bind to the positive state tag and are hidden while it holds.
    flood_warning = ui.WarningIndicator(
        "River at or above minor flood level", name="flood_warning", hidden=T.flood_ok
    )
    river_level_warning = ui.WarningIndicator(
        "River level reading is stale", name="river_level_warning", hidden=T.river_level_ok
    )
    river_flow_warning = ui.WarningIndicator(
        "River flow reading is stale", name="river_flow_warning", hidden=T.river_flow_ok
    )
    rain_warning = ui.WarningIndicator("Rain reading is stale", name="rain_warning", hidden=T.rain_ok)
    weather_warning = ui.WarningIndicator(
        "Weather reading is stale", name="weather_warning", hidden=T.weather_ok
    )

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
    # Units and precision are set in setup() from the Display Units config.
    river_flow = ui.NumericVariable(
        "River Flow", value=T.river_flow, icon="water", ranges=T.river_flow_ranges
    )
    # The flood class is shown by the gauge's bands; the tag stays for the dashboard.
    river_flood_class = ui.TextVariable(
        "Flood Class", value=T.river_flood_class, icon="house-flood-water", hidden=True
    )
    river_trend = ui.TextVariable("River Trend", value=T.river_trend, icon="arrow-trend-up")

    rain_since_9am = ui.NumericVariable(
        "Rain Since 9am",
        value=T.rain_since_9am,
        precision=1,
        units="mm",
        icon="droplet",
        ranges=RAIN_DAY_RANGES,
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

    weather = ui.Submodule(
        "Weather",
        children=[
            ui.NumericVariable(
                "Temperature",
                value=T.weather_temp,
                precision=1,
                units="°C",
                icon="temperature-half",
                ranges=TEMP_RANGES,
            ),
            ui.NumericVariable(
                "Feels Like",
                value=T.weather_apparent_temp,
                precision=1,
                units="°C",
                icon="person",
                ranges=TEMP_RANGES,
            ),
            ui.NumericVariable(
                "Humidity",
                value=T.weather_humidity,
                precision=0,
                units="%",
                icon="droplet",
                ranges=HUMIDITY_RANGES,
            ),
            ui.NumericVariable(
                "Dew Point",
                value=T.weather_dew_point,
                precision=1,
                units="°C",
                icon="droplet",
                ranges=DEW_POINT_RANGES,
            ),
            ui.NumericVariable(
                "Pressure",
                value=T.weather_pressure,
                precision=1,
                units="hPa",
                icon="gauge-high",
                ranges=PRESSURE_RANGES,
            ),
            ui.TextVariable("Wind Direction", value=T.weather_wind_dir, icon="compass"),
            ui.NumericVariable(
                "Wind Speed",
                value=T.weather_wind_speed,
                precision=0,
                units="km/h",
                icon="wind",
                ranges=WIND_RANGES,
            ),
            ui.NumericVariable(
                "Wind Gust",
                value=T.weather_wind_gust,
                precision=0,
                units="km/h",
                icon="wind",
                ranges=WIND_RANGES,
            ),
        ],
    )

    # Reading times live here; flow's matters most, as it is published about a
    # day behind the others.
    details = ui.Submodule(
        "Details",
        children=[
            ui.Timestamp(
                "River Level As At", value=T.river_level_time, precision="minute", icon="clock"
            ),
            ui.Timestamp(
                "River Flow As At", value=T.river_flow_time, precision="minute", icon="clock"
            ),
            ui.Timestamp("Rain As At", value=T.rain_time, precision="minute", icon="clock"),
            ui.Timestamp(
                "Weather As At", value=T.weather_time, precision="minute", icon="clock"
            ),
            ui.TextVariable("River Level Datum", value=T.river_datum, icon="ruler-vertical"),
            ui.TextVariable("Weather Station", value=T.weather_station, icon="tower-observation"),
            ui.TextVariable("Status", value=T.status, icon="circle-info"),
        ],
    )


    async def setup(self) -> None:
        parts = layout(self.config, self.tags).split(",")
        radial = any(p.startswith("radial") for p in parts)
        if radial:
            self.river_level.form = ui.Widget.radial

        series = []
        if "river" in parts:
            # The plot does not resolve tag references in a series' ranges, so
            # the flood bands go in literally; layout() republishes on change.
            bands = [
                Range(b["label"], b["min"], b["max"], b["colour"])
                for b in (self.tags.river_ranges.value or [])
            ]
            series.append(
                ui.Series(
                    "River Level",
                    value=T.river_level,
                    name="river_level",
                    data_type="number",
                    units="m",
                    colour=Colour.blue,
                    ranges=bands or None,
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
            # Available on the plot, but off until selected, so the river view
            # stays uncluttered.
            for label, tag, name, units, colour in (
                ("Temperature", T.weather_temp, "weather_temp", "°C", Colour.tomato),
                ("Humidity", T.weather_humidity, "weather_humidity", "%", Colour.grey),
                ("Wind Speed", T.weather_wind_speed, "weather_wind_speed", "km/h", Colour.orange),
            ):
                series.append(
                    ui.Series(
                        label,
                        value=tag,
                        name=name,
                        data_type="number",
                        units=units,
                        colour=colour,
                        shared_axis=False,
                        active=False,
                    )
                )
        else:
            self.remove_element("weather")
        flow = next((p for p in parts if p.startswith("flow:")), None)
        if flow:
            units = flow.split(":")[1]
            self.river_flow.units = units
            self.river_flow.precision = FLOW_UNITS[units][1]
            bands = [
                Range(b["label"], b["min"], b["max"], b["colour"])
                for b in (self.tags.river_flow_ranges.value or [])
            ]
            series.append(
                ui.Series(
                    "River Flow",
                    value=T.river_flow,
                    name="river_flow",
                    data_type="number",
                    units=units,
                    colour=Colour.green,
                    shared_axis=False,
                    ranges=bands or None,
                    active=True,
                )
            )
        else:
            self.remove_element("river_flow")
            self.details.remove_children(self.details._children["river_flow_as_at"])
        if series:
            self.overview.series = series
            if radial:
                self.overview.default_range_view = "zone"
        else:
            self.remove_element("overview")


def export() -> None:
    BomUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "bom",
    )
