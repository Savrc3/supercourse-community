"""导入差异比对测试：新增/变更/删除。"""

from __future__ import annotations

from dataclasses import dataclass

from app.importers.diff import compute_diff


@dataclass
class Row:
    id: str
    course_id: str
    name: str
    weekday: int
    start_lesson: int
    end_lesson: int
    weeks: str
    room: str | None


def _slot(name, weekday, start, end, weeks, room):
    return {
        "course_name": name,
        "code": None,
        "weekday": weekday,
        "start_lesson": start,
        "end_lesson": end,
        "room": room,
        "weeks": weeks,
    }


def test_added_generic() -> None:
    parsed = [_slot("高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    d = compute_diff(parsed, [], {})
    assert len(d["added"]) == 1
    assert d["added"][0]["index"] == 0
    assert d["added"][0]["selected"] is True
    assert d["added"][0]["before"] is None
    assert d["removed"] == []


def test_removed_detected() -> None:
    existing = [Row("s1", "c1", "高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    d = compute_diff([], existing, {"c1": "高等数学"})
    assert len(d["removed"]) == 1
    assert d["removed"][0]["row_id"] == "s1"
    assert d["removed"][0]["selected"] is False
    assert d["removed"][0]["before"]["room"] == "教101"


def test_changed_detected() -> None:
    # 教室不同 → 变更
    existing = [Row("s1", "c1", "高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    parsed = [_slot("高等数学", 1, 1, 2, '{"p":"all"}', "教202")]
    d = compute_diff(parsed, existing, {"c1": "高等数学"})
    assert len(d["changed"]) == 1
    assert d["changed"][0]["row_id"] == "s1"
    assert d["changed"][0]["before"]["room"] == "教101"
    assert d["changed"][0]["after"]["room"] == "教202"
    assert d["added"] == []


def test_no_change() -> None:
    existing = [Row("s1", "c1", "高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    parsed = [_slot("高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    d = compute_diff(parsed, existing, {"c1": "高等数学"})
    assert d["added"] == []
    assert d["changed"] == []
    assert d["removed"] == []


def test_equivalent_week_json_is_not_changed() -> None:
    existing = [
        Row(
            "s1",
            "c1",
            "高等数学",
            1,
            1,
            2,
            '{"ranges": [[1, 16]], "only": [], "except": [], "parity": "all"}',
            "教101",
        )
    ]
    parsed = [
        _slot(
            "高等数学",
            1,
            1,
            2,
            '{"parity":"all","except":[],"only":[],"ranges":[[1,16]]}',
            "教101",
        )
    ]
    d = compute_diff(parsed, existing, {"c1": "高等数学"})
    assert d == {"added": [], "changed": [], "removed": []}


def test_duplicate_fingerprints_are_paired_without_losing_rows() -> None:
    existing = [
        Row("s1", "c1", "高等数学", 1, 1, 2, '{"p":"all"}', "教101"),
        Row("s2", "c1", "高等数学", 1, 1, 2, '{"p":"all"}', "教102"),
    ]
    parsed = [_slot("高等数学", 1, 1, 2, '{"p":"all"}', "教101")]
    d = compute_diff(parsed, existing, {"c1": "高等数学"})
    assert d["changed"] == []
    assert [item["row_id"] for item in d["removed"]] == ["s2"]
