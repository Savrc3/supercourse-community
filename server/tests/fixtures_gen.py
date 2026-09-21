"""用 xlwt 生成覆盖边界 case 的脱敏样本 .xls（无真实姓名/学号）。

供 tests/test_xls.py 与 tests/test_import_api.py 使用。生成到临时目录，不入库。
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

import xlwt


def build_sample_bytes(primary_room: str = "教101", include_extra: bool = True) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("课表")

    # 学期行（含学期标识 + 日期用于 start_date 推断）
    ws.write(0, 0, "山东大学 张三 学生个人课表")
    ws.write(1, 0, "学年学期：2025-2026-2 打印日期：2026-06-07")
    # 表头行：星期一..星期日 → 列 1..7
    for i, day in enumerate(
        ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"], start=1
    ):
        ws.write(2, i, day)

    # 第 1 大节（01,02小节）
    ws.write(3, 0, "第一节\n(01,02小节)")
    # 周一：正常课（含代码/教师/周次/教室）
    ws.write(
        3,
        1,
        f"高等数学\n课序号:(01)\nsd03022A80\n王教授\n第1-16周([周])[01-02节]\n{primary_room}",
    )
    # 周二：同格两门课（空行分隔）
    if include_extra:
        ws.write(
            3,
            2,
            "线性代数\n李老师\n第1-8周([周])[01-02节]\n教102\n\n概率统计\n赵老师\n第9-16周([周])[01-02节]\n教103",
        )

    # 第 2 大节（03,04小节）
    ws.write(4, 0, "第二节\n(03,04小节)")
    # 周三：三小节连堂（第3/4/5节 -> 这里放二大节 03-04，再加一节验证连排）
    if include_extra:
        ws.write(4, 3, "大学物理\n张老师\n第1-18周([周])[03-04节]\n实101")
        # 周四：只有第16周
        ws.write(4, 4, "形势与政策\n第16周([周])[03-04节]\n教105")

    # 第 3 大节（05,06小节）
    ws.write(5, 0, "第三节\n(05,06小节)")
    # 周五：单周
    if include_extra:
        ws.write(5, 5, "体育\n刘老师\n第1-16周([单周])[05-06节]\n操场")
        # 周六：双周 + 多段周次
        ws.write(5, 6, "通识选修\n第1-10周,第12-16周([周])[05-06节]\n教201")

    # 第 4 大节（07,08小节）缺教室
    ws.write(6, 0, "第四节\n(07,08小节)")
    if include_extra:
        ws.write(6, 1, "英语\n陈老师\n第1-16周([周])[07-08节]")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_sample_xlsx_bytes() -> bytes:
    """生成最小 OOXML 样本，覆盖解析器的同格多课和单双周输入。"""
    cells = {
        "A1": "山东大学 张三 学生个人课表",
        "A2": "学年学期：2025-2026-2 打印日期：2026-06-07",
        "B3": "星期一",
        "C3": "星期二",
        "A4": "第一节\n(01,02小节)",
        "B4": "高等数学\n课序号:(01)\nsd03022A80\n王教授\n第1-16周([周])[01-02节]\n教101",
        "C4": "体育\n刘老师\n第1-16周([单周])[01-02节]\n操场",
    }
    # 用显式行分组保持 XML 简单，同时保留单元格换行。
    row_cells: dict[int, list[str]] = {}
    for ref, value in cells.items():
        row = int("".join(ch for ch in ref if ch.isdigit()))
        row_cells.setdefault(row, []).append(
            f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
        )
    rows_xml = "".join(
        f'<row r="{row}">{"".join(values)}</row>' for row, values in row_cells.items()
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{rows_xml}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="课表" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


__all__ = ["build_sample_bytes", "build_sample_xlsx_bytes"]
