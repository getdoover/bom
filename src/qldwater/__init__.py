"""AWS Lambda entry point for the Queensland water monitoring live data integration."""

from typing import Any

from pydoover.processor import run_app

from .application import QldWater


def handler(event: dict[str, Any], context: Any) -> None:
    run_app(QldWater(), event, context)
