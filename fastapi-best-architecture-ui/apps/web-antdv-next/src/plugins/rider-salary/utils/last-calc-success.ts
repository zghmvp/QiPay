const KEY_PREFIX = 'qipay:last-calc-run:';

export interface LastCalcRunRef {
  periodId: number;
  /** null = 本轮按全量骑手开算 */
  targetRiderIds: null | number[];
  successRiderIds: number[];
  ts: number;
}

function storageKey(periodId: number) {
  return `${KEY_PREFIX}${periodId}`;
}

export function rememberCalcRun(payload: LastCalcRunRef) {
  if (!payload.periodId) return;
  try {
    sessionStorage.setItem(storageKey(payload.periodId), JSON.stringify(payload));
  } catch {
    /* 无 sessionStorage 时忽略 */
  }
}

export function readCalcRun(periodId: number): LastCalcRunRef | null {
  if (!periodId) return null;
  try {
    const raw = sessionStorage.getItem(storageKey(periodId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastCalcRunRef;
    if (parsed?.periodId !== periodId) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function uniquePositiveIds(ids: null | number[] | undefined): number[] {
  return [...new Set((ids ?? []).filter((n) => Number.isFinite(n) && n > 0))];
}
