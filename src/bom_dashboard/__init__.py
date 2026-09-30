"""AWS Lambda entry point for the BOM dashboard processor."""

from typing import Any

from pydoover.processor import run_app

from .application import BomDashboard


def handler(event: dict[str, Any], context: Any) -> None:
    run_app(BomDashboard(), event, context)
