"""Device page UI: river level and rainfall side by side for one location."""

from pathlib import Path

from pydoover import ui

from .app_tags import BomTags as T


class BomUI(ui.UI):
    river_level = ui.NumericVariable(
        "River Level", value=T.river_level, precision=2, units="m"
    )
    river_trend = ui.TextVariable("River Trend", value=T.river_trend)
    river_level_time = ui.Timestamp(
        "River Reading", value=T.river_level_time, precision="minute"
    )

    rain_since_9am = ui.NumericVariable(
        "Rain Since 9am", value=T.rain_since_9am, precision=1, units="mm"
    )
    rain_last_hour = ui.NumericVariable(
        "Rain Last Hour", value=T.rain_last_hour, precision=1, units="mm"
    )
    rain_15min = ui.NumericVariable(
        "Rain Last 15 min", value=T.rain_15min, precision=1, units="mm"
    )
    rain_time = ui.Timestamp("Rain Reading", value=T.rain_time, precision="minute")

    details = ui.Submodule(
        "Details",
        children=[
            ui.TextVariable("River Level Datum", value=T.river_datum),
            ui.TextVariable("Status", value=T.status),
        ],
    )


def export() -> None:
    BomUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "bom",
    )
