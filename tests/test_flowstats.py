from datetime import date, timedelta

from bom.flowstats import History, flow_ranges, thresholds


def make_history(days: int = 2000) -> History:
    """Flows 1..days m³/s, one per day."""
    start = date(2020, 1, 1)
    return History(mean_flow={start + timedelta(days=i): float(i + 1) for i in range(days)})


def test_thresholds_from_percentiles() -> None:
    assert thresholds(make_history()) == {"low": 501.0, "high": 1500.0}


def test_thresholds_need_a_long_enough_record() -> None:
    assert thresholds(make_history(days=400)) == {}


def test_flow_ranges_stop_at_high_closed_above_its_own_edge() -> None:
    bands = flow_ranges({"low": 10, "high": 100})
    assert [(b["label"], b["min"], b["max"]) for b in bands] == [
        ("Low", 0, 10),
        ("Normal", 10, 100),
        ("High", 100, 150),  # 1.5x the edge, never the record maximum
    ]


def test_flow_ranges_from_a_high_edge_alone_and_non_rising_edges() -> None:
    assert [(b["label"], b["min"], b["max"]) for b in flow_ranges({"high": 800})] == [
        ("Normal", 0, 800),
        ("High", 800, 1200),
    ]
    # A high edge at or below the low edge is dropped, so only Low / Normal remain.
    assert [b["label"] for b in flow_ranges({"low": 100, "high": 100})] == ["Low", "Normal"]
    assert flow_ranges({}) == []
