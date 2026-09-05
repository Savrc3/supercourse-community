"""教务课表解析器（技术方案 §7 规范，纯函数 + xls/xlsx 读取层）。

真 OLE2/BIFF .xls 使用 xlrd；OOXML .xlsx 使用标准库 zipfile/XML 读取。

单元格内每个课程块按行解析（技术方案 §7）：
  1. 第 1 行 = 课程名
  2. `课序号:(n)` 记录后跳过
  3. 匹配 `^[a-z]+[0-9A-Za-z]+$` = 课程代码
  4. 位于「第…周」之前且不属上述两类 = 教师（可能逗号分隔长列表）
  5. 周次式（形如 `第1-16周([周])[01-02节]`）：拆为周次 + 奇偶 + 起止小节
  6. 剩余最后一行 = 教室
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

import xlrd

from app.importers.weeks import parse_weeks_expression, weeks_to_json


@dataclass
class ParsedCell:
    """一个课程格解析结果：可含一门或多门课（同格多门以空行分隔）。"""

    weekday: int
    big_period_lessons: list[int]
    courses: list[dict[str, Any]] = field(default_factory=list)
    slots: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_CODE_RE = re.compile(r"^[a-z]+[0-9A-Za-z]+$", re.IGNORECASE)
_LESSON_NO_RE = re.compile(r"^第.+?节\s*[\(（]\s*(\d+)(?:,|\s|\)|）|\d+)*")
_WEEK_RE = re.compile(r"第\s*\d+.*周")
_SEQ_RE = re.compile(r"课序号")
_BIG_LABEL_RE = re.compile(r"第(一|二|三|四|五|六|七|八|九|十)节")


_CN_NUM = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_big_period_label(label: str) -> list[int]:
    """从行首大节标签提取小节号列表。

    例：「第一节 ⏎ (01,02小节)」→ [1,2]；「第五节 ⏎ (09,10,11小节)」→ [9,10,11]。
    无括号或解析失败 → 用大节序号推默认（第一节=[1], 第二节=[3], ...）。
    """
    text = (label or "").strip()
    m = re.search(r"[\(（]\s*([0-9,，\s]+)\s*小节?[\)）]", text)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if nums:
            return nums
    # 从「第X节」取中文序号回退
    big = re.search(r"第([一二三四五六七八九十]+)节", text)
    if big and big.group(1) in _CN_NUM:
        n = _CN_NUM[big.group(1)]
        # 回退默认：n 大节 = [2n-1, 2n]（连排节点会显式给出）
        return [(n - 1) * 2 + 1, (n - 1) * 2 + 2]
    return []


def parse_cell_block(
    lines: list[str],
    *,
    weekday: int,
    big_period_lessons: list[int],
) -> ParsedCell:
    """解析单个课程格（可能含多门课，块间以空行分隔）。

    返回 ParsedCell。errors 表示该块无法解析（标红不阻断），warnings 表示可继续但需留意。
    """
    cell = ParsedCell(weekday=weekday, big_period_lessons=big_period_lessons)
    if not lines:
        cell.errors.append("空课程格")
        return cell

    # 按空行把多门课切成若干 block（课程格可能含多门课）
    blocks = _split_on_blank(lines)
    for block in blocks:
        _parse_one_block(cell, block, weekday, big_period_lessons)
    return cell


def _split_on_blank(lines: list[str]) -> list[list[str]]:
    raw_blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if not ln.strip():
            if cur:
                raw_blocks.append(cur)
                cur = []
        else:
            cur.append(ln.strip())
    if cur:
        raw_blocks.append(cur)

    # 有些教务表在“教师为空”时会额外保留一个空行。
    # 这行位于课程代码和周次之间，不能把后面的周次误判成新课程名。
    blocks: list[list[str]] = []
    for block in raw_blocks:
        if blocks and block and _WEEK_RE.search(block[0]):
            blocks[-1].extend(block)
        else:
            blocks.append(block)
    return blocks


def _parse_one_block(
    cell: ParsedCell,
    block: list[str],
    weekday: int,
    big_period_lessons: list[int],
) -> None:
    if not block:
        return
    name = block[0]
    if not name or _SEQ_RE.search(name) or _BIG_LABEL_RE.search(name):
        # 首行是课序号/大节标签，视为无课程名 → error
        cell.errors.append(f"无法识别课程名: {name!r}")
        return

    teacher: str | None = None
    code: str | None = None
    room: str | None = None
    weeks_raw: str | None = None
    weeks_spec: dict[str, Any] = {"ranges": [], "only": [], "except": [], "parity": "all"}
    lesson_range: tuple[int, int] | None = None

    # 教师行：位于周次行之前、非课程名、非代码、非课序号
    teacher_lines: list[str] = []
    for ln in block[1:]:
        if _WEEK_RE.search(ln):
            weeks_raw = ln
            break
        if _SEQ_RE.search(ln):
            continue
        if _CODE_RE.match(ln):
            code = ln
            continue
        teacher_lines.append(ln)

    if weeks_raw:
        weeks_spec, werr = parse_weeks_expression(weeks_raw)
        if werr:
            cell.errors.append(f"周次解析失败: {werr}")
        lesson_range = _extract_lesson_range(weeks_raw, big_period_lessons)
        # 周次行之后最后一行是教室
        idx = block.index(weeks_raw)
        tail = block[idx + 1 :]
        if tail:
            room = tail[-1]
            # 教室前面的可能是教师或其它，已并入 teacher_lines？
            for t in tail[:-1]:
                if t and not t.startswith("课序号"):
                    teacher_lines.append(t)
    else:
        # 无周次行：剩余全是教室（最后一行）或教室+教师混合，保守都当教室提示 warning
        remaining = block[1:]
        if remaining:
            room = remaining[-1]
            for t in remaining[:-1]:
                if t and t != code and not _SEQ_RE.search(t):
                    teacher_lines.append(t)
        cell.warnings.append(f"缺少周次（{name}），默认全部周")

    if teacher_lines:
        # 教师可能被拆在多行，逗号合并
        teacher = ",".join(teacher_lines).replace("\n", ",")
    if not name:
        cell.errors.append("缺少课程名")
    if teacher is None:
        cell.warnings.append(f"缺少教师（{name}）")
    if weeks_raw is None:
        cell.warnings.append(f"缺少周次（{name}），默认全部周")
    if room is None:
        cell.warnings.append(f"缺少教室（{name}）")

    # lesson_range：优先取周次里的 [01-02节]，回退到大节默认小节
    if lesson_range is None:
        if big_period_lessons:
            lesson_range = (big_period_lessons[0], big_period_lessons[-1])
        else:
            lesson_range = (1, 2)

    course_payload = {
        "name": name,
        "teacher": teacher,
        "code": code,
        "color": None,
    }
    cell.courses.append(course_payload)
    cell.slots.append(
        {
            "course_name": name,
            "code": code,
            "weekday": weekday,
            "start_lesson": lesson_range[0],
            "end_lesson": lesson_range[1],
            "room": room,
            "weeks": weeks_to_json(weeks_spec),
        }
    )


def _extract_lesson_range(
    weeks_raw: str,
    big_period_lessons: list[int],
) -> tuple[int, int] | None:
    """从周次式尾部的 [01-02节] 提取起止小节。"""
    m = re.search(r"\[([0-9,\-\s]+)节\]", weeks_raw)
    if m:
        nums = re.findall(r"\d+", m.group(1))
        if nums:
            return (int(nums[0]), int(nums[-1]))
    if big_period_lessons:
        return (big_period_lessons[0], big_period_lessons[-1])
    return None


@dataclass
class XlsParseResult:
    semester: str | None
    start_date: str | None
    courses: list[dict[str, Any]]
    slots: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]


def _cell_text(cell: Any) -> str:
    """把 xlrd cell 转成文本（字符串/数字→str，统一保留换行）。"""
    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return ""
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return str(int(cell.value)) if float(cell.value).is_integer() else str(cell.value)
    return str(cell.value or "")


def _find_weekday_header(sheet: Any) -> dict[int, int] | None:
    """找表头行「星期一…星期日」，返回 {列序号: weekday 1..7}。"""
    for r in range(min(sheet.nrows, 6)):
        header: dict[int, int] = {}
        for c in range(sheet.ncols):
            t = _cell_text(sheet.cell(r, c))
            for wd, wname in enumerate(
                ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"], start=1
            ):
                if wname in t:
                    header[c] = wd
                    break
        if header:
            return header
    return None


def _parse_semester_line(text: str) -> tuple[str | None, str | None]:
    """解析学期标识；只接受明确的开学日期，不把打印日期当开学日期。"""
    m = re.search(r"学年学期[:：]\s*([0-9]{4}-[0-9]{4}-[0-9])", text)
    semester = m.group(1) if m else None
    d = re.search(
        r"(?:开学日期|第一周周一|第一周星期一|起始日期)[:：\s]*(\d{4}-\d{2}-\d{2})",
        text,
    )
    start_date = d.group(1) if d else None
    return semester, start_date


@dataclass(frozen=True)
class _TextCell:
    value: str
    ctype: int = xlrd.XL_CELL_TEXT


class _XlsxSheet:
    """把 OOXML 第一张工作表适配成当前解析器所需的最小 xlrd-like 接口。"""

    def __init__(self, rows: dict[int, dict[int, _TextCell]]) -> None:
        self._rows = rows
        self.nrows = max(rows, default=-1) + 1
        self.ncols = max((max(row, default=-1) for row in rows.values()), default=-1) + 1

    def cell(self, row: int, col: int) -> _TextCell:
        return self._rows.get(row, {}).get(col, _TextCell("", xlrd.XL_CELL_EMPTY))


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx_col_index(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref)
    if not letters:
        return 0
    result = 0
    for char in letters.group(0).upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _xlsx_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(part.text or "" for part in element.iter(f"{{{_MAIN_NS}}}t"))


def _read_xlsx_sheet(file_bytes: bytes) -> _XlsxSheet:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [_xlsx_text(si) for si in root.findall(f"{{{_MAIN_NS}}}si")]

        sheet_name = next(
            (
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            ),
            None,
        )
        if sheet_name is None:
            raise ValueError("xlsx 没有工作表")
        root = ET.fromstring(archive.read(sheet_name))
        rows: dict[int, dict[int, _TextCell]] = {}
        for row in root.findall(f".//{{{_MAIN_NS}}}row"):
            row_no = int(row.attrib.get("r", "1")) - 1
            cells: dict[int, _TextCell] = {}
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                col_no = _xlsx_col_index(cell.attrib.get("r", "A1"))
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    value = _xlsx_text(cell.find(f"{{{_MAIN_NS}}}is"))
                elif kind == "s":
                    index = int(_xlsx_text(cell.find(f"{{{_MAIN_NS}}}v")) or "-1")
                    value = shared_strings[index] if 0 <= index < len(shared_strings) else ""
                else:
                    value = _xlsx_text(cell.find(f"{{{_MAIN_NS}}}v"))
                cells[col_no] = _TextCell(value)
            rows[row_no] = cells
        return _XlsxSheet(rows)


def _course_key(course: dict[str, Any]) -> tuple[str, str]:
    return (
        str(course.get("name") or "").strip(),
        str(course.get("code") or "").strip().lower(),
    )


def _parse_sheet(sheet: Any) -> XlsParseResult:
    """解析已适配的工作表，不产生数据库写入。"""
    if sheet.nrows == 0:
        return XlsParseResult(None, None, [], [], [], ["课表没有行"])

    header_map = _find_weekday_header(sheet)
    warnings: list[str] = []
    errors: list[str] = []
    semester: str | None = None
    start_date: str | None = None
    courses: list[dict[str, Any]] = []
    course_keys: set[tuple[str, str]] = set()
    slots: list[dict[str, Any]] = []

    for r in range(min(sheet.nrows, 8)):
        t = _cell_text(sheet.cell(r, 0))
        sem, sd = _parse_semester_line(t)
        if sem:
            semester = sem
        if sd:
            start_date = sd

    if header_map is None:
        return XlsParseResult(
            semester,
            start_date,
            [],
            [],
            warnings + ["未找到「星期一…星期日」表头行，视为空课表"],
            errors,
        )

    for r in range(sheet.nrows):
        label = _cell_text(sheet.cell(r, 0))
        big_lessons = parse_big_period_label(label)
        if not big_lessons:
            continue
        for c, weekday in header_map.items():
            cell_text = _cell_text(sheet.cell(r, c))
            if not cell_text.strip():
                continue
            parsed = parse_cell_block(
                cell_text.split("\n"),
                weekday=weekday,
                big_period_lessons=big_lessons,
            )
            warnings.extend(f"[{weekday}大节{big_lessons}] {w}" for w in parsed.warnings)
            errors.extend(f"[{weekday}大节] {e}" for e in parsed.errors)
            for course in parsed.courses:
                key = _course_key(course)
                if key[0] and key not in course_keys:
                    course_keys.add(key)
                    courses.append(course)
            slots.extend(parsed.slots)

    return XlsParseResult(semester, start_date, courses, slots, warnings, errors)


def parse_xls(file_bytes: bytes) -> XlsParseResult:
    """读取真实 .xls（OLE2/BIFF），返回规范化结果。不写库。"""
    try:
        book = xlrd.open_workbook(file_contents=file_bytes)
    except Exception as e:  # noqa: BLE001
        return XlsParseResult(None, None, [], [], [], [f"无法打开 .xls 文件: {e}"])

    if book.nsheets == 0:
        return XlsParseResult(None, None, [], [], [], ["xls 没有 Sheet"])
    return _parse_sheet(book.sheet_by_index(0))


def parse_xlsx(file_bytes: bytes) -> XlsParseResult:
    """读取 OOXML .xlsx，返回与 .xls 相同的规范化结果。不写库。"""
    try:
        return _parse_sheet(_read_xlsx_sheet(file_bytes))
    except (ValueError, zipfile.BadZipFile, ET.ParseError, IndexError) as e:
        return XlsParseResult(None, None, [], [], [], [f"无法打开 .xlsx 文件: {e}"])


def parse_schedule_file(file_bytes: bytes, filename: str | None = None) -> XlsParseResult:
    """根据文件魔数/扩展名选择 .xls 或 .xlsx 解析器。"""
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if file_bytes.startswith(b"PK") or suffix == "xlsx":
        return parse_xlsx(file_bytes)
    if file_bytes.startswith(b"\xd0\xcf\x11\xe0") or suffix == "xls":
        return parse_xls(file_bytes)
    return XlsParseResult(None, None, [], [], [], ["unsupported_format: 仅支持 .xls 或 .xlsx"])


__all__ = [
    "ParsedCell",
    "parse_big_period_label",
    "parse_cell_block",
    "parse_xls",
    "parse_xlsx",
    "parse_schedule_file",
    "XlsParseResult",
]
