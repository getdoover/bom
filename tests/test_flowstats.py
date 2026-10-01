from datetime import date, timedelta

from bom.flowstats import History, flow_ranges, thresholds


def make_history(days: int = 2000) -> History:
    """Flows 1..days m³/s, one per day; two days at the 1.0 m 'minor' level, the rest at 0.5 m."""
    start = date(2020, 1, 1)
    mean = {start + timedelta(days=i): float(i + 1) for i in range(days)}
    level = {d: 0.5 for d in mean}
    for d, v in mean.items():
        if v in (1990.0, 1995.0):
            level[d] = 1.0
    return History(mean_flow=mean, max_flow=dict(mean), max_level=level)


def test_thresholds_from_percentiles_and_flood_days() -> None:
    t = thresholds(make_history(), [1.0, 2.0, 3.0])
    assert (t["low"], t["high"], t["very_high"], t["max"]) == (201.0, 1800.0, 1980.0, 2000.0)
    assert t["minor"] == 1992.5  # median of the two days at 1.0 m
    assert "moderate" not in t and "major" not in t  # never reached


def test_thresholds_need_a_long_enough_record() -> None:
    t = thresholds(make_history(days=400), [None, None, None])
    assert "low" not in t and t["max"] == 400.0


def test_thresholds_drop_a_flood_flow_below_the_high_percentile() -> None:
    h = make_history()
    h.max_level = {d: (1.0 if v in (10.0, 12.0) else 0.5) for d, v in h.mean_flow.items()}
    assert "minor" not in thresholds(h, [1.0, None, None])


def test_flow_ranges_full_set() -> None:
    bands = flow_ranges({"low": 10, "high": 100, "very_high": 500, "minor": 800, "major": 2000, "max": 2500})
    assert [(b["label"], b["min"], b["max"]) for b in bands] == [
        ("Low", 0, 10),
        ("Normal", 10, 100),
        ("High", 100, 500),
        ("Very High", 500, 800),
        ("Minor Flood", 800, 2000),
        ("Major Flood", 2000, 2500),
    ]


def test_flow_ranges_from_flood_flows_alone_and_non_rising_edges() -> None:
    bands = flow_ranges({"minor": 800, "moderate": 700, "major": 2000})
    assert [(b["label"], b["min"], b["max"]) for b in bands] == [
        ("Normal", 0, 800),
        ("Minor Flood", 800, 2000),
        ("Major Flood", 2000, 3000),  # no record maximum: 1.5x the top edge
    ]
    assert flow_ranges({}) == [] and flow_ranges({"max": 100}) == []
