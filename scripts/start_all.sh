#!/usr/bin/env bash
# 启动 QiPay / FBA 本地开发环境（可重复执行：已在跑则跳过）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$ROOT/.runtime"
LOGDIR="$RUNTIME/logs"
BACKEND="$ROOT/fastapi-best-architecture"
FRONTEND="$ROOT/fastapi-best-architecture-ui"
PGDATA="${PGDATA:-$HOME/Library/FlyEnv/server/postgresql/postgresql18}"
PGCTL="${PGCTL:-/opt/homebrew/opt/postgresql@18/bin/pg_ctl}"
PGISREADY="${PGISREADY:-/opt/homebrew/opt/postgresql@18/bin/pg_isready}"
UV="${UV:-/opt/homebrew/bin/uv}"
PNPM="${PNPM:-/opt/homebrew/bin/pnpm}"

export PATH="/opt/homebrew/bin:/opt/homebrew/opt/postgresql@18/bin:${PATH:-/usr/bin:/bin}"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export PYTHONUNBUFFERED=1

mkdir -p "$LOGDIR"

port_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

daemonize() {
  local pidfile="$1"
  local logfile="$2"
  local cwd="$3"
  shift 3
  /usr/bin/python3 - "$pidfile" "$logfile" "$cwd" "$@" <<'PY'
import os, subprocess, sys

pidfile, logfile, cwd, *cmd = sys.argv[1:]
os.makedirs(os.path.dirname(os.path.abspath(pidfile)), exist_ok=True)
os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)
log = open(logfile, "ab", buffering=0)
env = os.environ.copy()
p = subprocess.Popen(
    cmd,
    cwd=cwd or None,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    env=env,
)
with open(pidfile, "w", encoding="utf-8") as f:
    f.write(str(p.pid))
print(p.pid)
PY
}

wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-60}"
  local i
  for i in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null "$url"; then
      echo "[ok] $name 已就绪：$url"
      return 0
    fi
    sleep 1
  done
  echo "[warn] 等待 $name 超时：$url" >&2
  return 1
}

echo "==> PostgreSQL"
if "$PGISREADY" -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  echo "[skip] PostgreSQL 已在 5432 监听"
else
  if [[ ! -x "$PGCTL" || ! -d "$PGDATA" ]]; then
    echo "[error] 未找到本机 PostgreSQL 数据目录或 pg_ctl：$PGDATA" >&2
    exit 1
  fi
  # macOS + PG18：无效 locale 会导致 postmaster 启动期多线程而失败
  "$PGCTL" -D "$PGDATA" -l "$LOGDIR/postgres.log" start
  sleep 1
  "$PGISREADY" -h 127.0.0.1 -p 5432 >/dev/null
  echo "[ok] PostgreSQL 已启动"
fi
if [[ -f "$PGDATA/postmaster.pid" ]]; then
  head -n 1 "$PGDATA/postmaster.pid" > "$RUNTIME/postgres.pid"
fi

echo "==> Redis"
if redis-cli ping 2>/dev/null | grep -q PONG; then
  echo "[skip] Redis 已运行"
else
  if command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes
    sleep 1
  fi
  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[error] Redis 未运行且无法自动拉起，请先启动 Redis" >&2
    exit 1
  fi
  echo "[ok] Redis 已启动"
fi

echo "==> 后端 fba"
if port_listening 8000; then
  echo "[skip] 后端已在 8000 监听"
  lsof -nP -iTCP:8000 -sTCP:LISTEN | awk 'NR==2 {print $2}' > "$RUNTIME/backend.pid" || true
else
  if [[ ! -d "$BACKEND/.venv" ]]; then
    echo "[error] 未找到 $BACKEND/.venv，请先在该目录执行：uv sync --group dev --python 3.12" >&2
    exit 1
  fi
  daemonize "$RUNTIME/backend.pid" "$LOGDIR/backend.log" "$BACKEND" \
    "$UV" run --python 3.12 fba run --no-reload
  echo "[ok] 后端已后台启动 pid=$(cat "$RUNTIME/backend.pid")"
fi
wait_http "http://127.0.0.1:8000/docs" "后端 /docs" 90 || true

echo "==> 前端 web-antdv-next"
if port_listening 5173; then
  echo "[skip] 前端已在 5173 监听"
  lsof -nP -iTCP:5173 -sTCP:LISTEN | awk 'NR==2 {print $2}' > "$RUNTIME/frontend.pid" || true
else
  if [[ ! -d "$FRONTEND/node_modules" ]]; then
    echo "[error] 未找到 $FRONTEND/node_modules，请先在该目录执行：CI=true pnpm install" >&2
    exit 1
  fi
  daemonize "$RUNTIME/frontend.pid" "$LOGDIR/frontend.log" "$FRONTEND" \
    "$PNPM" -F @vben/web-antdv-next run dev
  echo "[ok] 前端已后台启动 pid=$(cat "$RUNTIME/frontend.pid")"
fi
wait_http "http://127.0.0.1:5173/" "前端首页" 90 || true

echo "==> 骑手 H5 rider-h5"
RIDER_H5="$ROOT/rider-h5"
if port_listening 5174; then
  echo "[skip] 骑手 H5 已在 5174 监听"
  lsof -nP -iTCP:5174 -sTCP:LISTEN | awk 'NR==2 {print $2}' > "$RUNTIME/rider-h5.pid" || true
elif [[ ! -d "$RIDER_H5" ]]; then
  echo "[skip] 未找到 $RIDER_H5"
elif [[ ! -d "$RIDER_H5/node_modules" ]]; then
  echo "[warn] 未找到 $RIDER_H5/node_modules，跳过骑手 H5。请先在该目录执行：pnpm install"
else
  daemonize "$RUNTIME/rider-h5.pid" "$LOGDIR/rider-h5.log" "$RIDER_H5" \
    "$PNPM" run dev
  echo "[ok] 骑手 H5 已后台启动 pid=$(cat "$RUNTIME/rider-h5.pid")"
fi
if port_listening 5174 || [[ -d "$RIDER_H5/node_modules" ]]; then
  wait_http "http://127.0.0.1:5174/" "骑手 H5" 90 || true
fi

echo
echo "访问地址："
echo "  后端 Swagger  http://127.0.0.1:8000/docs"
echo "  前端          http://127.0.0.1:5173/"
echo "  骑手 H5       http://localhost:5174/"
echo "  管理员        admin / 123456"
echo "PID / 日志：$RUNTIME"
