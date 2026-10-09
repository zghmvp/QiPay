#!/usr/bin/env bash
# 每日逻辑备份。默认连 compose 映射出来的 Postgres（127.0.0.1:5433），不会去碰开发库端口 5432。
# 只读，不改库。恢复请用 restore.sh。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5433}"
export PGUSER="${PGUSER:-qipay}"
export PGDATABASE="${PGDATABASE:-fba}"
export PGPASSWORD="${PGPASSWORD:-qipay-change-me}"

BACKUP_DIR="${QIPAY_BACKUP_DIR:-$ROOT/backups}"
KEEP_DAYS="${QIPAY_BACKUP_KEEP_DAYS:-14}"

if [[ ! "$PGDATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "拒绝：数据库名不合法：${PGDATABASE}" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

echo "备份目标 ${PGHOST}:${PGPORT}/${PGDATABASE}（当前库名将在连接后打印）"
current="$(psql -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
echo "current_database=${current}"
if [[ "$current" != "$PGDATABASE" ]]; then
  echo "拒绝：连上的库是 ${current}，与 PGDATABASE=${PGDATABASE} 不一致" >&2
  exit 1
fi
if [[ "$current" == "fba" && "$PGPORT" == "5432" ]]; then
  echo "注意：这是本机 5432 上的开发库 fba，本次只做只读 pg_dump，不会改数据。" >&2
fi

stamp="$(date +%Y%m%d-%H%M%S)"
outfile="${BACKUP_DIR}/qipay-${current}-${stamp}.dump"
umask 077
pg_dump -Fc --no-owner --no-acl -f "$outfile"
sha256sum "$outfile" > "${outfile}.sha256"
echo "已写入 ${outfile}"

find "$BACKUP_DIR" -type f -name 'qipay-*.dump' -mtime +"$KEEP_DAYS" -print -delete
find "$BACKUP_DIR" -type f -name 'qipay-*.dump.sha256' -mtime +"$KEEP_DAYS" -print -delete
