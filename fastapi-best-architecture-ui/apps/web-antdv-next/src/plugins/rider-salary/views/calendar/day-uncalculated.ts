import type { CalendarDayDetail } from '../../types/calendar';
import type { MoneyValue } from '../../types/common';

export const DAY_UNCALCULATED_HINT = '未算薪，不是今日提成为 0';
export const DAY_UNCALCULATED_HIT_HINT = '无命中项（尚未进本次算薪）';
export const DAY_UNCALCULATED_DEDUCT_HINT = '代扣不进日手工，对账看条';

export function isZeroMoney(value?: MoneyValue): boolean {
  if (value === null || value === undefined || value === '') return true;
  const n = Number(value);
  return Number.isFinite(n) && Math.abs(n) < 0.005;
}

function completedOrders(detail?: null | Pick<CalendarDayDetail, 'orders'>) {
  return (detail?.orders ?? []).filter((row) => row.status === 'completed');
}

/**
 * 有完成单、尚无 daily cache：不能把 0.00 读成今日没提成。
 * 显式 has_daily_cache 优先；否则用「无命中 + 无按日项 + 公式为 0」推断。
 */
export function isUncalculatedDay(
  detail?: null | (CalendarDayDetail & { has_daily_cache?: boolean }),
): boolean {
  if (!detail) return false;
  const completed = completedOrders(detail);
  if (!completed.length) return false;
  if (detail.has_daily_cache === true) return false;
  if (detail.has_daily_cache === false) return true;
  const hasHits = (detail.orders ?? []).some(
    (row) => (row.details ?? []).length > 0,
  );
  const hasDaily = (detail.daily_items ?? []).length > 0;
  return !hasHits && !hasDaily && isZeroMoney(detail.totals?.formula_amount);
}

export function dayFormulaMainText(
  detail?: null | (CalendarDayDetail & { has_daily_cache?: boolean }),
): string {
  if (isUncalculatedDay(detail)) return '—';
  const n = Number(detail?.totals?.formula_amount);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

export function orderHitEmptyText(
  detail?: null | (CalendarDayDetail & { has_daily_cache?: boolean }),
): string {
  if (isUncalculatedDay(detail)) return DAY_UNCALCULATED_HIT_HINT;
  return '无命中项';
}
