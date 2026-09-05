"""教务周次表达式 → weeks JSON 的纯函数解析器（技术方案 §7）。

支持输入形如：
  "第1-16周([周])[01-02节]"
  "第1周,第3周,第5周([周])[01-02节]"
  "第1-10周,第12-16周([双周])[05-06节]"
  "第1-16周([单周])[01-02节]"
输出 {"ranges":[[1,16]],"only":[],"except":[],"parity":"all|odd|even"}
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_weeks_expression(raw: str) -> tuple[dict[str, Any], str | None]:
    """解析周次表达式。

    返回 (weeks_json_dict, error)。error 非空表示无法解析（调用方标红）。
    空字符串或无周次 → 返回空规则且无错误（表示"全部周"，调用方自行决定）。
    """
    text = (raw or "").strip().replace("，", ",").replace("、", ",")
    if not text:
        return {"ranges": [], "only": [], "except": [], "parity": "all"}, None

    # 提取紧跟在周次部分之后的奇偶标记：([周]) all、([单周]) odd、([双周]) even。
    parity = "all"
    if "单周" in text:
        parity = "odd"
    elif "双周" in text:
        parity = "even"

    # 先提取“第 N 周除外”和“除第 N 周”表达式，再去掉括号与小节标记。
    except_weeks: list[int] = []
    except_patterns = [
        r"第\s*([\d,\-\s]+)周\s*(?:除外|除去)",
        r"除\s*第\s*([\d,\-\s]+)周?",
    ]
    for pattern in except_patterns:
        for match in re.finditer(pattern, text):
            for part in match.group(1).split(","):
                part = part.strip()
                if "-" in part:
                    start, end = (int(x) for x in part.split("-", 1))
                    except_weeks.extend(range(min(start, end), max(start, end) + 1))
                elif part.isdigit():
                    except_weeks.append(int(part))
        text = re.sub(pattern, "", text)

    # 去掉小节标记与奇偶括号，只保留“第...周”主体部分。
    body = re.sub(r"\[([0-9,\-]+节)\]", "", text)
    body = re.sub(r"\([^)]*\)|（[^）]*）", "", body)
    body = body.replace("第", "").replace("周", "")

    # 按逗号切分若干段，每段可是 "1-16" 或 "3"。
    if not body.strip():
        return {
            "ranges": [],
            "only": [],
            "except": sorted(set(except_weeks)),
            "parity": parity,
        }, None

    ranges: list[list[int]] = []
    only: list[int] = []
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start > end:
                start, end = end, start
            ranges.append([start, end])
        elif part.isdigit():
            only.append(int(part))
        else:
            return {
                "ranges": [],
                "only": [],
                "except": sorted(set(except_weeks)),
                "parity": parity,
            }, f"无法解析周次片段: {part}"

    return {
        "ranges": ranges,
        "only": only,
        "except": sorted(set(except_weeks)),
        "parity": parity,
    }, None


def weeks_to_json(spec: dict[str, Any]) -> str:
    """把 weeks spec 序列化为 JSON 字符串（供 course_slot.weeks 存储）。"""
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":"))


__all__ = ["parse_weeks_expression", "weeks_to_json"]
