from datetime import datetime, timedelta, timezone

import pytest

from bom.wdo import FLOW_UNITS, convert_flow, parse_discharge

WML = """<?xml version="1.0" ?>
<sos:GetObservationResponse xmlns:sos="http://www.opengis.net/sos/2.0"
    xmlns:om="http://www.opengis.net/om/2.0" xmlns:wml2="http://www.opengis.net/waterml/2.0">
  <sos:observationData><om:OM_Observation><om:result>
    <wml2:MeasurementTimeseries>
      <wml2:defaultPointMetadata><wml2:DefaultTVPMeasurementMetadata>
        <wml2:uom code="{unit}"/>
      </wml2:DefaultTVPMeasurementMetadata></wml2:defaultPointMetadata>
      <wml2:point><wml2:MeasurementTVP>
        <wml2:time>2026-09-29T22:00:00.000+10:00</wml2:time><wml2:value>22.507</wml2:value>
      </wml2:MeasurementTVP></wml2:point>
      <wml2:point><wml2:MeasurementTVP>
        <wml2:time>2026-09-29T21:00:00.000+10:00</wml2:time><wml2:value>19.149</wml2:value>
      </wml2:MeasurementTVP></wml2:point>
      <wml2:point><wml2:MeasurementTVP>
        <wml2:time>2026-09-29T22:00:02.000+10:00</wml2:time><wml2:value/>
      </wml2:MeasurementTVP></wml2:point>
    </wml2:MeasurementTimeseries>
  </om:result></om:OM_Observation></sos:observationData>
</sos:GetObservationResponse>
"""

ERROR = """<?xml version="1.0" ?>
<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">
  <ows:Exception exceptionCode="InvalidParameterValue">
    <ows:ExceptionText>Unknown station</ows:ExceptionText>
  </ows:Exception>
</ows:ExceptionReport>
"""


def test_parse_discharge_sorts_and_skips_end_marker() -> None:
    flows = parse_discharge(WML.format(unit="cumec"))
    aest = timezone(timedelta(hours=10))
    assert [(f.time, f.value) for f in flows] == [
        (datetime(2026, 9, 29, 21, tzinfo=aest), 19.149),
        (datetime(2026, 9, 29, 22, tzinfo=aest), 22.507),
    ]


def test_parse_discharge_converts_megalitres_per_day() -> None:
    flows = parse_discharge(WML.format(unit="ML/d"))
    assert flows[-1].value == pytest.approx(22.507 * 1000 / 86400)
    with pytest.raises(ValueError, match="unit"):
        parse_discharge(WML.format(unit="furlongs"))


def test_parse_discharge_raises_service_errors() -> None:
    with pytest.raises(ValueError, match="Unknown station"):
        parse_discharge(ERROR)
    assert parse_discharge(
        '<sos:GetObservationResponse xmlns:sos="http://www.opengis.net/sos/2.0"/>'
    ) == []


def test_convert_flow() -> None:
    assert convert_flow(1.0, "ML/day") == 86.4
    assert convert_flow(22.507, "ML/day") == pytest.approx(1944.605)
    assert convert_flow(0.0123456, "L/s") == 12.35
    assert convert_flow(250.0, "GL/day") == 21.6
    assert convert_flow(22.507, "m³/s") == 22.507
    assert list(FLOW_UNITS) == ["ML/day", "m³/s", "L/s", "GL/day"]
