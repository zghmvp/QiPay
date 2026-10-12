import type { LockCheckResult } from '../../types/period';

export interface LockConfirmInput {
  canLock?: boolean;
  carrying?: boolean;
  loadError?: boolean;
  loading?: boolean;
  needsRecalcCount?: number;
  recalculating?: boolean;
  uncalculatedCount?: number;
}

/**
 * 有未算薪或需重算时锁账按钮置灰。
 * 预检接口的 can_lock 仍负责缺补发单、状态不允许等其余原因。
 */
export function canConfirmPeriodLock(input: LockConfirmInput): boolean {
  if (
    input.loading ||
    input.loadError ||
    input.carrying ||
    input.recalculating
  ) {
    return false;
  }
  if ((input.uncalculatedCount ?? 0) > 0) return false;
  if ((input.needsRecalcCount ?? 0) > 0) return false;
  return Boolean(input.canLock);
}

/** 未算薪和需重算的骑手 ID，去重且保持名单顺序。 */
export function supplementRiderIds(
  check: Pick<LockCheckResult, 'needs_recalc' | 'uncalculated'> | null,
): number[] {
  if (!check) return [];
  const ids: number[] = [];
  const seen = new Set<number>();
  for (const item of [...check.uncalculated, ...check.needs_recalc]) {
    if (seen.has(item.rider_id)) continue;
    seen.add(item.rider_id);
    ids.push(item.rider_id);
  }
  return ids;
}
