#!/usr/bin/env bash
# 启动 QiPay 本地开发环境（macOS / Linux，可重复执行）。
#
# 用法（相对仓库根目录）：
#   scripts/start_all.sh
#   scripts/stop_all.sh
#
# 环境前置（本脚本只检测，不安装，也不拉起数据库和缓存）：
#   - bash（macOS 自带 3.2，或 Linux bash 4+）
#   - python3（运行本目录的 dev_runtime.py）
#   - Python 3.12（后端：uv run --python 3.12）
#   - uv
#   - Node.js ^22.18.0 或 ^24.0.0（管理端 engines）
#   - pnpm >= 11（仓库锁定 pnpm@11.7.0）
#   - PostgreSQL 已在 127.0.0.1:5432 监听
#   - Redis 已在 127.0.0.1:6379 监听
#
# 端口检测使用 /proc/net/tcp、ss 或 TCP 连接，不依赖 lsof。
# 某个服务的 pidfile 会记录 cmdline、cwd、启动时间；stop_all.sh 只结束校验通过的进程。
# 端口已被其他进程占用时，本脚本以非 0 退出，并且不会结束那个进程。
# 健康检查失败时同样以非 0 退出，不再打印“已就绪”。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
HELPER="$SCRIPTS/dev_runtime.py"
RUNTIME="$ROOT/.runtime"
LOGDIR="$RUNTIME/logs"
BACKEND="$ROOT/fastapi-best-architecture"
FRONTEND="$ROOT/fastapi-best-architecture-ui"
H5="$ROOT/rider-h5"

append_path() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  case ":${PATH}:" in
    *":${dir}:"*) ;;
    *) PATH="${PATH}:${dir}" ;;
  esac
}

# 用户 PATH 优先。下面只是常见安装位置的后备，目录不存在就跳过。
append_path "${HOME}/.local/bin"
append_path "/opt/homebrew/bin"
append_path "/usr/local/bin"
export PATH

export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export PYTHONUNBUFFERED=1

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  echo "[error] 未找到 python3。启停脚本需要 Python 3，后端运行需要 Python 3.12（由 uv 提供）。" >&2
  exit 1
fi

# 默认 node 低于管理端 engines 时，改用 nvm 里已安装且符合要求的版本。macOS 没有 nvm 则保持原 PATH。
NODE_BIN="$("$PY" "$HELPER" suggest-node-bin || true)"
if [[ -n "$NODE_BIN" ]]; then
  PATH="${NODE_BIN}:${PATH}"
  export PATH
  echo "[info] 已改用符合管理端 engines 的 Node：$("$NODE_BIN/node" --version) (${NODE_BIN}/node)"
fi

mkdir -p "$LOGDIR"

echo "==> 检查工具"
"$PY" "$HELPER" check-tools --frontend "$FRONTEND"

echo "==> 检查 PostgreSQL / Redis（只检测，不拉起）"
"$PY" "$HELPER" check-deps

UV="${UV:-$(command -v uv || true)}"
PNPM="${PNPM:-$(command -v pnpm || true)}"
if [[ -z "$UV" || -z "$PNPM" ]]; then
  echo "[error] 未找到 uv 或 pnpm。" >&2
  exit 1
fi

if [[ ! -d "$BACKEND/.venv" ]]; then
  echo "[error] 未找到 fastapi-best-architecture/.venv。请在该目录执行：uv sync --group dev --python 3.12" >&2
  exit 1
fi
if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "[error] 未找到 fastapi-best-architecture-ui/node_modules。请在该目录执行：CI=true pnpm install" >&2
  exit 1
fi
if [[ -d "$H5" && ! -d "$H5/node_modules" ]]; then
  echo "[error] 未找到 rider-h5/node_modules。请在该目录执行：pnpm install" >&2
  exit 1
fi

start_one() {
  local name="$1"
  local port="$2"
  local pidfile="$3"
  local logfile="$4"
  local cwd="$5"
  local url="$6"
  shift 6
  echo "==> $name"
  "$PY" "$HELPER" ensure-started \
    --name "$name" \
    --port "$port" \
    --pidfile "$pidfile" \
    --logfile "$logfile" \
    --cwd "$cwd" \
    --max-bytes "${QIPAY_LOG_MAX_BYTES:-10485760}" \
    --keep "${QIPAY_LOG_KEEP:-5}" \
    -- \
    "$@"
  if ! "$PY" "$HELPER" wait-http --url "$url" --name "$name" --tries "${QIPAY_WAIT_TRIES:-90}"; then
    echo "[error] ${name}未就绪。日志：${logfile}" >&2
    echo "[error] 可执行 scripts/stop_all.sh，它只会停止 pidfile 校验通过的进程。" >&2
    if [[ -f "$logfile" ]]; then
      echo "[error] 日志末尾：" >&2
      tail -n 40 "$logfile" >&2 || true
    fi
    exit 1
  fi
}

start_one "后端" 8000 "$RUNTIME/backend.pid" "$LOGDIR/backend.log" "$BACKEND" \
  "http://127.0.0.1:8000/docs" \
  "$UV" run --python 3.12 fba run --no-reload

start_one "前端" 5173 "$RUNTIME/frontend.pid" "$LOGDIR/frontend.log" "$FRONTEND" \
  "http://127.0.0.1:5173/" \
  "$PNPM" -F @vben/web-antdv-next run dev

if [[ ! -d "$H5" ]]; then
  echo "[skip] 未找到 rider-h5，跳过骑手 H5"
else
  start_one "骑手 H5" 5174 "$RUNTIME/rider-h5.pid" "$LOGDIR/rider-h5.log" "$H5" \
    "http://127.0.0.1:5174/" \
    "$PNPM" run dev
fi

echo
echo "访问地址："
echo "  后端 Swagger  http://127.0.0.1:8000/docs"
echo "  前端          http://127.0.0.1:5173/"
echo "  骑手 H5       http://127.0.0.1:5174/"
echo "日志目录：.runtime/logs/（超过 10MiB 会按大小轮转）"
echo "停止：scripts/stop_all.sh"
