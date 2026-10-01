from datetime import datetime, timezone

from bom.ftp import latest_file
from bom.obs import parse_observations

OBS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<product version="v1.7.1">
  <observations>
    <station wmo-id="95527" bom-id="053115" stn-name="MOREE AERO" type="AWS">
      <period index="0" time-utc="2026-09-30T23:40:00+00:00" time-local="2026-10-01T09:40:00+10:00">
        <level index="0" type="surface">
          <element units="Celsius" type="apparent_temp">15.0</element>
          <element units="km/h" type="gust_kmh">35</element>
          <element units="Celsius" type="air_temperature">20.6</element>
          <element units="Celsius" type="dew_point">8.6</element>
          <element units="hPa" type="pres">1028.5</element>
          <element units="hPa" type="msl_pres">1028.4</element>
          <element units="%" type="rel-humidity">46</element>
          <element type="wind_dir">N</element>
          <element units="km/h" type="wind_spd_kmh">28</element>
          <element units="knots" type="wind_spd">15</element>
          <element units="mm" type="rainfall">0.0</element>
        </level>
      </period>
    </station>
    <station bom-id="048245" stn-name="SPARSE" type="Non-AWS">
      <period index="0" time-utc="2026-09-30T23:00:00+00:00">
        <level index="0" type="surface">
          <element units="Celsius" type="air_temperature">18.1</element>
          <element type="wind_dir"></element>
        </level>
      </period>
    </station>
    <station bom-id="000000" stn-name="NO READING" type="AWS"/>
  </observations>
</product>
"""


def test_parse_observations() -> None:
    obs = parse_observations(OBS_XML)
    assert list(obs) == ["053115", "048245"]  # a station without a period is skipped

    moree = obs["053115"]
    assert moree.name == "MOREE AERO"
    assert moree.time == datetime(2026, 9, 30, 23, 40, tzinfo=timezone.utc)
    assert (moree.temp, moree.apparent_temp, moree.dew_point) == (20.6, 15.0, 8.6)
    assert moree.humidity == 46
    assert moree.pressure == 1028.4  # mean sea level, not station pressure
    assert (moree.wind_dir, moree.wind_speed, moree.wind_gust) == ("N", 28, 35)

    sparse = obs["048245"]
    assert sparse.temp == 18.1
    assert sparse.wind_dir is None
    assert sparse.humidity is None and sparse.wind_speed is None


def test_latest_file_matches_unsuffixed_products() -> None:
    names = ["IDN60920.xml", "IDN65900_20260930053800.hcs", "IDN65900_20260930055300.hcs"]
    assert latest_file(names, "IDN60920.xml") == "IDN60920.xml"
    assert latest_file(names, "IDN65900") == "IDN65900_20260930055300.hcs"
    assert latest_file(names, "IDN60920") is None
