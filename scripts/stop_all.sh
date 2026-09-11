#!/usr/bin/env bash
# 停止由 start_all.sh 拉起的 FBA 后端与前端（默认不停 PostgreSQL / Redis）。
# 设置 STOP_POSTGRES=1 时额外停止 FlyEnv 数据目录中的 PostgreSQL。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$ROOT/.runtime"
PGDATA="${PGDATA:-$HOME/Library/FlyEnv/server/postgresql/postgresql18}"
PGCTL="${PGCTL:-/opt/homebrew/opt/postgresql@18/bin/pg_ctl}"
BACKEND="$ROOT/fastapi-best-architecture"
FRONTEND="$ROOT/fastapi-best-architecture-ui"

kill_tree() {
  local pid="${1:-}"
  [[ -z "$pid" ]] && return 0
  kill -0 "$pid" 2>/dev/null || return 0
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

stop_pidfile() {
  local file="$1"
  local name="$2"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(tr -d '[:space:]' < "$file" || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "==> 停止 $name pid=$pid"
      kill_tree "$pid"
    else
      echo "[skip] $name pid 文件存在但进程不在：$file"
    fi
  fi
}

echo "==> 停止后端"
stop_pidfile "$RUNTIME/backend.pid" "后端"
# 兜底：只匹配本仓库 fba 进程，避免误杀其它 Python 服务
pkill -f "$BACKEND/.venv/bin/fba run" 2>/dev/null || true
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -nP -iTCP:8000 -sTCP:LISTEN | awk 'NR>1 {print $2}' | sort -u | while read -r pid; do
    echo "==> 释放 8000 pid=$pid"
    kill_tree "$pid"
  done
fi

echo "==> 停止前端"
stop_pidfile "$RUNTIME/frontend.pid" "前端"
stop_pidfile "$RUNTIME/frontend-shell.pid" "前端 shell"
# 兜底：只匹配本仓库 web-antdv-next / 该目录下的 vite development
pkill -f "$FRONTEND/node_modules/.bin/../vite/bin/vite.js --mode development" 2>/dev/null || true
pkill -f "pnpm -F @vben/web-antdv-next run dev" 2>/dev/null || true
if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -nP -iTCP:5173 -sTCP:LISTEN | awk 'NR>1 {print $2}' | sort -u | while read -r pid; do
    echo "==> 释放 5173 pid=$pid"
    kill_tree "$pid"
  done
fi

echo "==> 停止骑手 H5"
stop_pidfile "$RUNTIME/rider-h5.pid" "骑手 H5"
pkill -f "$ROOT/rider-h5/node_modules/.bin/vite" 2>/dev/null || true
if lsof -nP -iTCP:5174 -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -nP -iTCP:5174 -sTCP:LISTEN | awk 'NR>1 {print $2}' | sort -u | while read -r pid; do
    echo "==> 释放 5174 pid=$pid"
    kill_tree "$pid"
  done
fi

if [[ "${STOP_POSTGRES:-0}" == "1" ]]; then
  echo "==> 停止 PostgreSQL"
  if [[ -x "$PGCTL" && -d "$PGDATA" ]]; then
    "$PGCTL" -D "$PGDATA" stop -m fast || true
  fi
else
  echo "[skip] 未停止 PostgreSQL / Redis（共享服务）。如需停库：STOP_POSTGRES=1 $0"
fi

sleep 1
echo
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[warn] 8000 仍被占用"
else
  echo "[ok] 8000 已释放"
fi
if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[warn] 5173 仍被占用"
else
  echo "[ok] 5173 已释放"
fi
if lsof -nP -iTCP:5174 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[warn] 5174 仍被占用"
else
  echo "[ok] 5174 已释放"
fi
