#!/usr/bin/env bash
# 在临时库上演练「备份 → 恢复」。库名固定为 qipay_p403_src / qipay_p403_dst，不会使用 fba。
# 连接参数沿用现场的 PGHOST / PGPORT / PGUSER / PGPASSWORD，缺省为本机开发实例的管理员账号，
# 但目标库名仍然不是 fba。演练结束会删掉这两个临时库。
set -euo pipefail

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-root}"
export PGPASSWORD="${PGPASSWORD:-postgres}"

SRC="qipay_p403_src"
DST="qipay_p403_dst"
HERE="$(cd "$(dirname "$0")" && pwd)"

for name in "$SRC" "$DST"; do
  if [[ "$name" == "fba" || ! "$name" =~ ^qipay_p403_[a-z]+$ ]]; then
    echo "拒绝：演练库名不允许：${name}" >&2
    exit 1
  fi
done

cleanup() {
  psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${SRC};" >/dev/null || true
  psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${DST};" >/dev/null || true
}
trap cleanup EXIT

echo "维护连接："
psql -d postgres -v ON_ERROR_STOP=1 -c 'SELECT current_database() AS current_database;'
maint="$(psql -d postgres -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
if [[ "$maint" != "postgres" ]]; then
  echo "拒绝：当前库是 ${maint}，演练必须从 postgres 维护库建临时库" >&2
  exit 1
fi

psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${SRC};"
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${DST};"
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${SRC};"
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DST};"

src_current="$(psql -d "$SRC" -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
echo "源库 current_database=${src_current}"
if [[ "$src_current" != "$SRC" ]]; then
  echo "拒绝：源库实际是 ${src_current}" >&2
  exit 1
fi

psql -d "$SRC" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE qipay_drill_marker (
    id integer PRIMARY KEY,
    note text NOT NULL
);
INSERT INTO qipay_drill_marker (id, note) VALUES (1, 'p403-backup-ok');
SQL

export PGDATABASE="$SRC"
export QIPAY_BACKUP_DIR="${QIPAY_BACKUP_DIR:-/tmp/qipay-p403-backups}"
export QIPAY_BACKUP_KEEP_DAYS=1
mkdir -p "$QIPAY_BACKUP_DIR"
"$HERE/backup.sh"

dump="$(find "$QIPAY_BACKUP_DIR" -type f -name "qipay-${SRC}-*.dump" | sort | tail -1)"
if [[ -z "$dump" ]]; then
  echo "拒绝：没有找到演练备份文件" >&2
  exit 1
fi

"$HERE/restore.sh" "$dump" "$DST"
note="$(psql -d "$DST" -v ON_ERROR_STOP=1 -tA -c 'SELECT note FROM qipay_drill_marker WHERE id = 1;')"
dst_current="$(psql -d "$DST" -v ON_ERROR_STOP=1 -tA -c 'SELECT current_database();')"
echo "恢复库 current_database=${dst_current} note=${note}"
if [[ "$dst_current" != "$DST" || "$note" != "p403-backup-ok" ]]; then
  echo "演练失败" >&2
  exit 1
fi
echo "演练成功"
