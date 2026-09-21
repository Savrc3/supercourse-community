#!/usr/bin/env bash
# 课序 · Linux/WSL 版开发启动脚本（对应 scripts/dev.ps1）
# 用法: bash scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8090}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

PY="$ROOT/server/.venv/bin/python"
VITE="$ROOT/node_modules/.bin/vite"

if [ ! -x "$PY" ]; then
  echo "❌ 缺少后端虚拟环境，请先执行: cd server && uv sync" >&2
  exit 1
fi
if [ ! -x "$VITE" ]; then
  echo "❌ 缺少前端依赖，请先在项目根目录执行: npm ci" >&2
  exit 1
fi

BACK_PID=""
FRONT_PID=""
cleanup() {
  echo
  echo "正在停止开发服务..."
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting backend  http://127.0.0.1:${BACKEND_PORT}"
(
  cd "$ROOT/server"
  exec "$PY" -m uvicorn app.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" \
    --reload --reload-dir app
) &
BACK_PID=$!

echo "Starting frontend http://127.0.0.1:${FRONTEND_PORT}"
(
  cd "$ROOT/apps/web"
  exec "$VITE" --host --port "$FRONTEND_PORT"
) &
FRONT_PID=$!

# 等待后端健康检查通过（最多 30 秒）
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    echo "Backend ready, open http://127.0.0.1:${FRONTEND_PORT}"
    break
  fi
  sleep 0.5
done

echo "Dev servers started (backend PID ${BACK_PID} / frontend PID ${FRONT_PID}). Press Ctrl+C to stop."
wait
