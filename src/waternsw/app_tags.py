"""What the last fetch did, and where the next one starts from."""

from pydoover import tags


class WaterNswTags(tags.Tags):
    status = tags.String(default=None)
    gauges = tags.Number(default=None)  # devices fed on the last run
    readings = tags.Number(default=None)  # records fetched on the last run
    # When the last fully successful fetch started (ms since epoch); the next
    # asks for everything WaterNSW has loaded since.
    fetched_at = tags.Number(default=None)
