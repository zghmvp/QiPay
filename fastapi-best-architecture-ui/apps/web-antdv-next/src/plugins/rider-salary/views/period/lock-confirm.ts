export interface LockPreflightResult {
  confirm_hint: string;
  freeze_adjustment_count: number;
  freeze_order_count: number;
  freeze_payroll_count: number;
  is_site_level: boolean;
  lock_rider_count: number;
  skip_hint: string;
  skip_rider_count: number;
}

export function isSiteLevelPeriod(row: { rider_id?: null | number }): boolean {
  return !row.rider_id;
}

/** extraHint 吃后端 confirm_hint；缺省时用冻结数 + skip_hint。 */
export function buildLockConfirmHint(preflight: LockPreflightResult): string {
  const fromBackend = preflight.confirm_hint?.trim();
  if (fromBackend) return fromBackend;
  const skip =
    preflight.skip_hint?.trim() ||
    `跳过骑手级覆盖 ${preflight.skip_rider_count} 人`;
  return (
    `将冻结订单 ${preflight.freeze_order_count} 笔、奖惩 ${preflight.freeze_adjustment_count} 笔、` +
    `薪资单 ${preflight.freeze_payroll_count} 张；将锁骑手 ${preflight.lock_rider_count} 人；${skip}`
  );
}

export const SITE_LEVEL_LOCK_PREFLIGHT_FALLBACK =
  '站点级锁将跳过骑手级已覆盖的骑手。预检未返回将冻结订单、奖惩、薪资单与跳过人数，请稍后重试。不得把窗内全量骑手数当成将锁人数。';
