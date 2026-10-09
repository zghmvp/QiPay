#!/usr/bin/env bash
# 停止由 scripts/start_all.sh 拉起的后端、管理端和骑手 H5。
#
# 只结束 .runtime 下 pidfile 中 cmdline、cwd、启动时间全部吻合的进程。
# 不按端口查找进程，也不停止 PostgreSQL / Redis。
# STOP_POSTGRES=1 会被忽略，避免误停共享数据库。
#
# 用法（相对仓库根目录）：
#   scripts/stop_all.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
HELPER="$SCRIPTS/dev_runtime.py"
RUNTIME="$ROOT/.runtime"

append_path() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  case ":${PATH}:" in
    *":${dir}:"*) ;;
    *) PATH="${PATH}:${dir}" ;;
  esac
}

append_path "${HOME}/.local/bin"
append_path "/opt/homebrew/bin"
append_path "/usr/local/bin"
export PATH

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  echo "[error] 未找到 python3。" >&2
  exit 1
fi

if [[ "${STOP_POSTGRES:-}" == "1" ]]; then
  echo "[skip] 已忽略 STOP_POSTGRES。本脚本不停止 PostgreSQL / Redis。" >&2
fi

rc=0
stop_one() {
  local name="$1"
  local pidfile="$2"
  local code=0
  "$PY" "$HELPER" stop --name "$name" --pidfile "$pidfile" --grace "${QIPAY_STOP_GRACE:-8}" || code=$?
  if [[ "$code" -eq 1 ]]; then
    rc=1
  fi
}

echo "==> 停止骑手 H5"
stop_one "骑手 H5" "$RUNTIME/rider-h5.pid"
echo "==> 停止前端"
stop_one "前端" "$RUNTIME/frontend.pid"
if [[ -f "$RUNTIME/frontend-shell.pid" ]]; then
  stop_one "前端 shell" "$RUNTIME/frontend-shell.pid"
fi
echo "==> 停止后端"
stop_one "后端" "$RUNTIME/backend.pid"

echo
"$PY" "$HELPER" report-ports --ports 8000,5173,5174 || true
echo "[skip] 未停止 PostgreSQL / Redis（共享依赖，本脚本不负责）。"
exit "$rc"
