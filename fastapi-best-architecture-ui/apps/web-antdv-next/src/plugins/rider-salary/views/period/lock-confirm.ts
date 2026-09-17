export interface LockPreviewCounts {
  adjustment_count?: number;
  lock_adjustment_count?: number;
  lock_order_count?: number;
  lock_payroll_count?: number;
  lock_rider_count?: number;
  order_count?: number;
  payroll_count?: number;
  rider_level_skip_count?: number;
  skip_rider_count?: number;
  skipped_rider_count?: number;
  skipped_rider_level_count?: number;
  will_lock_adjustment_count?: number;
  will_lock_order_count?: number;
  will_lock_payroll_count?: number;
  will_lock_rider_count?: number;
}

function pickCount(
  preview: LockPreviewCounts,
  keys: (keyof LockPreviewCounts)[],
): number | undefined {
  for (const key of keys) {
    const raw = preview[key];
    if (raw === null || raw === undefined || raw === ('' as never)) continue;
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

export function isSiteLevelPeriod(row: { rider_id?: null | number }): boolean {
  return !row.rider_id;
}

/** 数字必须来自后端预检。缺跳过人数则不算交付。 */
export function buildLockConfirmHint(preview: LockPreviewCounts): string {
  const orders = pickCount(preview, [
    'will_lock_order_count',
    'lock_order_count',
    'order_count',
  ]);
  const adjustments = pickCount(preview, [
    'will_lock_adjustment_count',
    'lock_adjustment_count',
    'adjustment_count',
  ]);
  const payrolls = pickCount(preview, [
    'will_lock_payroll_count',
    'lock_payroll_count',
    'payroll_count',
  ]);
  const lockRiders = pickCount(preview, [
    'will_lock_rider_count',
    'lock_rider_count',
  ]);
  const skipped = pickCount(preview, [
    'skipped_rider_level_count',
    'skipped_rider_count',
    'rider_level_skip_count',
    'skip_rider_count',
  ]);

  const parts: string[] = [];
  if (orders !== undefined || adjustments !== undefined || payrolls !== undefined) {
    parts.push(
      `本锁将冻结订单 ${orders ?? '—'}、奖惩 ${adjustments ?? '—'}、薪资单 ${payrolls ?? '—'}。`,
    );
  }
  if (lockRiders !== undefined) {
    parts.push(`将锁骑手 ${lockRiders} 人（已扣除骑手级覆盖）。`);
  }
  if (skipped !== undefined) {
    parts.push(`跳过骑手级覆盖 ${skipped} 人。`);
  } else {
    parts.push('跳过骑手级覆盖人数未返回。');
  }
  return parts.join('');
}

export const SITE_LEVEL_LOCK_PREVIEW_FALLBACK =
  '站点级锁将跳过骑手级已覆盖的骑手。预检未返回将冻结订单、奖惩、薪资单与跳过人数，请稍后重试。不得把窗内全量骑手数当成将锁人数。';
