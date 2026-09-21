"""周次表达式解析器测试（技术方案 §7 规范）。"""

from __future__ import annotations

from app.importers.weeks import parse_weeks_expression


def test_range_week() -> None:
    spec, err = parse_weeks_expression("第1-16周([周])[01-02节]")
    assert err is None
    assert spec["ranges"] == [[1, 16]]
    assert spec["parity"] == "all"


def test_comma_list_weeks() -> None:
    spec, err = parse_weeks_expression("第1周,第3周,第5周([周])[01-02节]")
    assert err is None
    assert spec["only"] == [1, 3, 5]
    assert spec["ranges"] == []


def test_multi_ranges() -> None:
    spec, err = parse_weeks_expression("第1-10周,第12-16周([周])[05-06节]")
    assert err is None
    assert spec["ranges"] == [[1, 10], [12, 16]]


def test_odd_parity() -> None:
    spec, err = parse_weeks_expression("第1-16周([单周])[01-02节]")
    assert err is None
    assert spec["parity"] == "odd"


def test_even_parity() -> None:
    spec, err = parse_weeks_expression("第1-16周([双周])[01-02节]")
    assert err is None
    assert spec["parity"] == "even"


def test_empty_weeks() -> None:
    spec, err = parse_weeks_expression("")
    assert err is None
    assert spec["ranges"] == []


def test_only_week_16() -> None:
    spec, err = parse_weeks_expression("第16周([周])[01-02节]")
    assert err is None
    assert spec["only"] == [16]


def test_invalid_segment_errors() -> None:
    _, err = parse_weeks_expression("第1-16周,第X周([周])[01-02节]")
    assert err is not None
