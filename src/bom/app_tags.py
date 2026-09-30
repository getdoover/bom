"""Current values shown in the UI, plus the bookkeeping kept between runs."""

from pydoover import tags
from pydoover.tags import Tag


class BomTags(tags.Tags):
    river_level = tags.Number(default=None)
    river_level_time = tags.Number(default=None)  # ms since epoch
    river_trend = tags.String(default=None)
    river_datum = tags.String(default=None)
    river_flood_class = tags.String(default=None)
    river_ranges = Tag("array", default=[])  # flood bands, from config

    rain_15min = tags.Number(default=None)
    rain_last_hour = tags.Number(default=None)
    rain_since_9am = tags.Number(default=None)
    rain_time = tags.Number(default=None)  # ms since epoch

    status = tags.String(default=None)

    # Bookkeeping: the 9am rain day that rain_since_9am belongs to.
    rain_day = tags.String(default=None)
