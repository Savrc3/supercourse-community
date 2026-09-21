#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前敏感扫描：扫出真实 IP、邮箱、手机号、密钥、家目录路径等，命中即报错。

用法:
  python3 scripts/sensitive-scan.py [路径] [--values "v1,v2"] [--exclude 目录名,目录名]
                                  [--skip-private] [--no-fail]

- 默认扫描当前目录；只读文本类文件。
- `--values` 补精确值（如 QQ 号、群号、姓名）；`--exclude` 追加跳过的目录名。
- `--skip-private` 跳过本仓库里**按发布边界本就私有**的文件（`docs/`、`server/scripts/`、
  `AGENTS.md`/`CLAUDE.md`/`.cursorrules`/`CHANGELOG.md`），供私有仓内部门禁使用；
  对外发布物检查不要加这个开关。
- `--no-fail` 只报告不返回非零（默认命中即退出码 1）。

对回环/私有网段/文档保留网段（192.0.2.0/24、198.51.100.0/24、203.0.113.0/24）与
示例域名邮箱不报，避免把正常的开发配置和测试数据当成敏感值。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".py", ".sh", ".ps1", ".mjs", ".js",
    ".ts", ".vue", ".cjs", ".conf", ".html", ".htm", ".xml", ".ini", ".cfg", ".env",
    ".example", ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore", ".properties",
}

DEFAULT_EXCLUDES = {
    ".git", "node_modules", "dist", "data", ".venv", "__pycache__", ".pytest_cache",
    ".pytest-tmp", ".pytest-now", ".mypy_cache", ".ruff_cache", ".hypothesis",
    "playwright-report", "test-results", "coverage", "logs", "build", ".gradle", "android",
}

# 发布边界内本就私有的文件：只有 --skip-private 时才跳过
PRIVATE_PREFIXES = ("docs/", "server/scripts/")
PRIVATE_FILES = {
    "AGENTS.md", "CLAUDE.md", ".cursorrules", "CHANGELOG.md",
    "scripts/tools-env.sh", "scripts/tools-env.ps1",  # 由 setup-env 生成，含本机绝对路径
    "apps/web/e2e/real-data.spec.ts", "apps/web/playwright.real.config.ts",
    "scripts/sensitive-scan.py",  # 本脚本自身的规则字面量
}

ALLOWED_IP_PREFIXES = ("127.", "10.", "192.168.", "169.254.", "0.0.0.0")
ALLOWED_IP_PREFIXES_172 = tuple(f"172.{n}." for n in range(16, 32))
DOC_IP_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "izs.me", "localhost")
ALLOWED_EMAIL_LOCAL = ("noreply", "no-reply", "you", "user", "your")

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
KEY_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b")
SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b[A-Za-z0-9_]{0,16}?(?:api[_-]?key|access[_-]?token|auth(?:orization)?[_-]?code|app[_-]?secret"
    r"|client[_-]?secret|secret|token|password|passwd|passphrase)\b\s*[:=]\s*['\"]?([A-Za-z0-9_-]{12,})['\"]?"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")
HOME_PATH_RE = re.compile(r"(?:/home/(?!<)[A-Za-z0-9_.-]+|/mnt/[a-z]/Users/[A-Za-z0-9_.-]+|C:\\+Users\\+[A-Za-z0-9_.-]+)")
QQ_RE = re.compile(r"(?i)(?:\bqq\b|群号?|群\s*[:：]?)\D{0,6}\d{5,12}")


def secret_assign_hits(line: str) -> bool:
    """赋值形式只认“随机串”值：至少 12 位、同时含字母与数字，避免误报路径/变量名。"""
    for match in SECRET_ASSIGN_RE.finditer(line):
        value = match.group(1)
        if any(ch.isdigit() for ch in value) and any(ch.isalpha() for ch in value):
            return True
    return False


def ip_hits(line: str) -> bool:
    for match in IPV4_RE.finditer(line):
        ip = match.group(0)
        parts = ip.split(".")
        if any(int(p) > 255 for p in parts):
            continue
        if ip.startswith(ALLOWED_IP_PREFIXES) or ip.startswith(ALLOWED_IP_PREFIXES_172):
            continue
        if ip.startswith(DOC_IP_PREFIXES):
            continue
        return True
    return False


def email_hits(line: str) -> bool:
    for match in EMAIL_RE.finditer(line):
        address = match.group(0)
        local, _, domain = address.partition("@")
        if domain.lower() in ALLOWED_EMAIL_DOMAINS:
            continue
        if local.lower() in ALLOWED_EMAIL_LOCAL:
            continue
        return True
    return False


PATTERNS = [
    (ip_hits, "<SERVER_IP>"),
    (email_hits, "<EMAIL>"),
    (lambda line: PHONE_RE.search(line) is not None, "<PHONE>"),
    (lambda line: KEY_RE.search(line) is not None, "<API_KEY>"),
    (secret_assign_hits, "<API_KEY>"),
    (lambda line: PRIVATE_KEY_RE.search(line) is not None, "<PRIVATE_KEY>"),
    (lambda line: HOME_PATH_RE.search(line) is not None, "<HOME>"),
    (lambda line: QQ_RE.search(line) is not None, "<BOT_QQ>/<GROUP_ID_n>"),
]


def is_private(rel_path: str) -> bool:
    return rel_path.startswith(PRIVATE_PREFIXES) or rel_path in PRIVATE_FILES


def iter_files(path: str, excludes: set[str], skip_private: bool, root: str):
    if os.path.isfile(path):
        yield path
        return
    for current, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in excludes and not d.startswith(".")]
        for name in files:
            full = os.path.join(current, name)
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXTENSIONS and name not in TEXT_EXTENSIONS:
                continue
            if "_previous" in name or ".previous" in name or "previous-" in full:
                continue
            if skip_private and is_private(os.path.relpath(full, root).replace(os.sep, "/")):
                continue
            yield full


def scan_file(path: str, values: list[str]):
    hits = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for lineno, line in enumerate(handle, 1):
                for matcher, placeholder in PATTERNS:
                    if matcher(line):
                        hits.append((path, lineno, line.rstrip(), placeholder))
                        break
                else:
                    for value in values:
                        if value and value in line:
                            hits.append((path, lineno, line.rstrip(), "<EXACT_VALUE>"))
                            break
    except OSError:
        pass
    return hits


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，强制 UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="发布前敏感扫描")
    parser.add_argument("path", nargs="?", default=".", help="文件或目录，默认当前目录")
    parser.add_argument("--values", default="", help="额外精确敏感值，逗号分隔（QQ 号、群号、姓名）")
    parser.add_argument("--exclude", default="", help="追加跳过的目录名，逗号分隔")
    parser.add_argument("--skip-private", action="store_true", help="跳过仓库内本就私有的文件")
    parser.add_argument("--no-fail", action="store_true", help="命中只报告，不返回非零")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"错误：路径不存在 {args.path}")
        return 2

    root = os.path.abspath(args.path)
    values = [v.strip() for v in args.values.split(",") if v.strip()]
    excludes = set(DEFAULT_EXCLUDES) | {d.strip() for d in args.exclude.split(",") if d.strip()}

    hits = []
    for target in iter_files(root, excludes, args.skip_private, root):
        hits.extend(scan_file(target, values))

    if hits:
        print(f"发现 {len(hits)} 处敏感命中（对外发布前必须清零）：")
        for path, lineno, line, placeholder in hits:
            print(f"  {os.path.relpath(path, root)}:{lineno} -> 建议替换为 {placeholder} | {line.strip()[:80]}")
        return 0 if args.no_fail else 1

    label = os.path.relpath(root, os.getcwd()) or "."
    print(f"OK：{label} 敏感扫描零命中，可发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
