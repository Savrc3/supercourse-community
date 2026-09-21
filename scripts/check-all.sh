#!/usr/bin/env bash
# 课序 · Linux/WSL 质量门禁（对应 scripts/check-all.ps1）
# 用法: bash scripts/check-all.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FAILED=0

run() { # name cmd...
  local name="$1"; shift
  echo
  echo ">>> $name"
  if "$@"; then
    echo "<<< $name OK"
  else
    echo "<<< $name FAILED"
    FAILED=1
  fi
}

PY="$ROOT/server/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "缺少后端虚拟环境，请先: cd server && uv sync" >&2
  exit 1
fi

# --- 后端 ---
cd "$ROOT/server"
run "ruff check"       "$PY" -m ruff check .
run "ruff format"      "$PY" -m ruff format --check .
run "mypy"             "$PY" -m mypy app
run "pytest"           "$PY" -m pytest -q --basetemp=.pytest-now

# --- 前端 ---
cd "$ROOT"
run "eslint"           npm run lint      --workspace @supercourse/web
run "vue-tsc"          npm run typecheck --workspace @supercourse/web
run "vitest"           npm run test      --workspace @supercourse/web
run "frontend build"   npm run build     --workspace @supercourse/web
run "desktop test"     npm run test      --workspace @supercourse/desktop

# --- 敏感信息扫描（可选，脚本不存在则跳过）---
SCAN="$HOME/.codex/skills/sensitive-scan/scripts/sensitive-scan.py"
if [ -f "$SCAN" ]; then
  run "sensitive scan" python3 "$SCAN" "$ROOT" --exclude node_modules,dist
else
  echo
  echo ">>> sensitive scan（跳过：未找到 $SCAN）"
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "❌ check-all failed"
  exit 1
fi
echo "✅ check-all passed"
