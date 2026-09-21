"""教务 xls 解析器测试：边界全 case（纯函数 + 读样本）。"""

from __future__ import annotations

from tests.fixtures_gen import build_sample_bytes, build_sample_xlsx_bytes

from app.importers.weeks import parse_weeks_expression
from app.importers.xls import (
    parse_big_period_label,
    parse_cell_block,
    parse_schedule_file,
    parse_xls,
)


def test_parse_big_period_label_double() -> None:
    assert parse_big_period_label("第一节 ⏎ (01,02小节)") == [1, 2]
    assert parse_big_period_label("第五节 ⏎ (09,10,11小节)") == [9, 10, 11]


def test_parse_big_period_label_fallback() -> None:
    # 无括号时按中文序号回退（第3节 → [5,6]）
    assert parse_big_period_label("第三节") == [5, 6]


def test_parse_cell_block_normal() -> None:
    parsed = parse_cell_block(
        ["高等数学", "课序号:(01)", "sd03022A80", "王教授", "第1-16周([周])[01-02节]", "教101"],
        weekday=1,
        big_period_lessons=[1, 2],
    )
    assert len(parsed.courses) == 1
    assert parsed.courses[0]["name"] == "高等数学"
    assert parsed.courses[0]["teacher"] == "王教授"
    assert parsed.courses[0]["code"] == "sd03022A80"
    slot = parsed.slots[0]
    assert slot["weekday"] == 1
    assert slot["start_lesson"] == 1
    assert slot["end_lesson"] == 2
    assert slot["room"] == "教101"
    assert '"range":' not in slot["weeks"]  # 序列化为 weeks JSON


def test_parse_cell_block_two_courses_in_one_cell() -> None:
    parsed = parse_cell_block(
        [
            "线性代数",
            "李老师",
            "第1-8周([周])[01-02节]",
            "教102",
            "",
            "概率统计",
            "赵老师",
            "第9-16周([周])[01-02节]",
            "教103",
        ],
        weekday=2,
        big_period_lessons=[1, 2],
    )
    assert len(parsed.courses) == 2
    assert len(parsed.slots) == 2


def test_parse_cell_block_single_week_only() -> None:
    parsed = parse_cell_block(
        ["形势与政策", "第16周([周])[03-04节]", "教105"],
        weekday=4,
        big_period_lessons=[3, 4],
    )
    assert parsed.slots[0]["start_lesson"] == 3
    assert parsed.slots[0]["end_lesson"] == 4


def test_parse_cell_block_missing_teacher_and_room() -> None:
    parsed = parse_cell_block(
        ["大学物理", "张老师", "第1-18周([周])[03-04节]", "实101"],
        weekday=3,
        big_period_lessons=[3, 4],
    )
    assert len(parsed.warnings) >= 0
    # 缺教室
    parsed2 = parse_cell_block(
        ["英语", "陈老师", "第1-16周([周])[07-08节]"],
        weekday=1,
        big_period_lessons=[7, 8],
    )
    assert any("缺少教室" in w for w in parsed2.warnings)


def test_parse_cell_block_missing_teacher_does_not_create_fake_course() -> None:
    parsed = parse_cell_block(
        [
            "形势与政策（3）",
            "课序号:(405)",
            "sd090101E0",
            "",
            "第7周,第9周,第11周,第13周([周])[07-08节]",
            "软件园1区303d",
        ],
        weekday=4,
        big_period_lessons=[7, 8],
    )

    assert [course["name"] for course in parsed.courses] == ["形势与政策（3）"]
    assert parsed.courses[0]["teacher"] is None
    assert parsed.slots[0]["room"] == "软件园1区303d"
    assert '"only":[7,9,11,13]' in parsed.slots[0]["weeks"]


def test_parse_cell_block_odd_even_parity() -> None:
    odd = parse_cell_block(
        ["体育", "刘老师", "第1-16周([单周])[05-06节]", "操场"],
        weekday=5,
        big_period_lessons=[5, 6],
    )
    assert '"parity":"odd"' in odd.slots[0]["weeks"]
    even = parse_cell_block(
        ["通识选修", "第1-10周,第12-16周([周])[05-06节]", "教201"],
        weekday=6,
        big_period_lessons=[5, 6],
    )
    assert '"ranges":[[1,10],[12,16]]' in even.slots[0]["weeks"]


def test_parse_xls_from_sample() -> None:
    data = build_sample_bytes()
    result = parse_xls(data)
    assert result.errors == [] or all("无法打开" not in e for e in result.errors)
    assert result.semester == "2025-2026-2"
    # 打印日期不能被误当成第一周周一，必须留给用户在预览页补齐。
    assert result.start_date is None
    assert len(result.slots) >= 6
    # 同格两门课应解析出 2 个 slot（线性代数 + 概率统计）
    names = [c["name"] for c in result.courses]
    assert "高等数学" in names
    assert "线性代数" in names
    assert "概率统计" in names
    assert "大学物理" in names
    # 单周
    assert any(c["name"] == "体育" for c in result.courses)


def test_parse_xlsx_from_sample() -> None:
    result = parse_schedule_file(build_sample_xlsx_bytes(), "sample.xlsx")
    assert result.errors == []
    assert result.semester == "2025-2026-2"
    assert result.start_date is None
    assert {c["name"] for c in result.courses} == {"高等数学", "体育"}
    assert result.slots[1]["weeks"]


def test_weeks_support_chinese_punctuation_and_except() -> None:
    spec, error = parse_weeks_expression("第1-16周（第5周除外）[01-02节]")
    assert error is None
    assert spec["ranges"] == [[1, 16]]
    assert spec["except"] == [5]

    spec, error = parse_weeks_expression("第1周、第3周、第5周([周])[01-02节]")
    assert error is None
    assert spec["only"] == [1, 3, 5]
