#!/usr/bin/env bash
# 把 pg_dump 自定义格式备份恢复到目标库。
# 用法：restore.sh <dump 文件> <目标库名>
# 拒绝恢复到本机 5432 的开发库 fba。其它名为 fba 的目标（例如 compose 映射端口上的生产库）
# 必须同时设置 QIPAY_ALLOW_FBA=yes。
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "用法：$0 <dump 文件> <目标库名>" >&2
  exit 1
fi

dump="$1"
target="$2"

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5433}"
export PGUSER="${PGUSER:-qipay}"
export PGPASSWORD="${PGPASSWORD:-qipay-change-me}"

if [[ ! "$target" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "拒绝：目标库名不合法：${target}" >&2
  exit 1
fi
if [[ ! -f "$dump" ]]; then
  echo "拒绝：找不到备份文件：${dump}" >&2
  exit 1
fi
if [[ -f "${dump}.sha256" ]]; then
  sha256sum -c "${dump}.sha256"
fi

if [[ "$target" == "fba" && "$PGPORT" == "5432" ]]; then
  echo "拒绝：不能把备份恢复到本机 5432 的开发库 fba。" >&2
  exit 1
fi
if [[ "$target" == "fba" && "${QIPAY_ALLOW_FBA:-}" != "yes" ]]; then
  echo "拒绝：目标库名是 fba。确认端口不是开发库后，设置 QIPAY_ALLOW_FBA=yes 再执行。" >&2
  exit 1
fi

echo "维护连接："
psql -d postgres -v ON_ERROR_STOP=1 -c 'SELECT current_database() AS current_database;'
maint="$(psql -d postgres -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
if [[ "$maint" != "postgres" ]]; then
  echo "拒绝：维护连接当前库是 ${maint}，期望 postgres" >&2
  exit 1
fi

echo "即将恢复到 ${PGHOST}:${PGPORT}/${target}"
exists="$(psql -d postgres -v ON_ERROR_STOP=1 -tA -c "SELECT 1 FROM pg_database WHERE datname = '${target}'")"
if [[ "$exists" != "1" ]]; then
  psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${target}"
fi

current="$(psql -d "$target" -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
echo "current_database=${current}"
if [[ "$current" != "$target" ]]; then
  echo "拒绝：连上的库是 ${current}，与目标 ${target} 不一致" >&2
  exit 1
fi

pg_restore --no-owner --no-acl --exit-on-error -d "$target" "$dump"
echo "恢复完成：${PGHOST}:${PGPORT}/${target}"
