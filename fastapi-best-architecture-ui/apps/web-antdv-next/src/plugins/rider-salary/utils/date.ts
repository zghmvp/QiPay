import type { Dayjs } from 'dayjs';

import dayjs from 'dayjs';

export function toDateString(value: Date | Dayjs | null | string | undefined) {
  if (!value) return undefined;
  const d = dayjs(value);
  return d.isValid() ? d.format('YYYY-MM-DD') : undefined;
}

export function toDateTimeString(
  value: Date | Dayjs | null | string | undefined,
) {
  if (!value) return undefined;
  const d = dayjs(value);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : undefined;
}

export function monthRange(month: string): [string, string] {
  const start = dayjs(`${month}-01`);
  return [start.format('YYYY-MM-DD'), start.endOf('month').format('YYYY-MM-DD')];
}

export function currentMonth(): string {
  return dayjs().format('YYYY-MM');
}

/** 周一起始的 6×7 月历矩阵，含上月末/下月初补齐格 */
export function buildMonthMatrix(month: string): Dayjs[][] {
  const start = dayjs(`${month}-01`);
  const weekday = start.day();
  const mondayOffset = weekday === 0 ? 6 : weekday - 1;
  const first = start.subtract(mondayOffset, 'day');
  const weeks: Dayjs[][] = [];
  for (let w = 0; w < 6; w += 1) {
    const week: Dayjs[] = [];
    for (let d = 0; d < 7; d += 1) {
      week.push(first.add(w * 7 + d, 'day'));
    }
    weeks.push(week);
  }
  return weeks;
}

export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'];

export function formatCycleSummary(
  settleCycle: null | string | undefined,
  cycleConfig?: null | Record<string, unknown>,
): string {
  if (settleCycle === 'month') return '自然月';
  if (settleCycle === 'half_month') return '1–15 / 16–月末';
  if (settleCycle === 'custom') {
    const day = cycleConfig?.anchor_day;
    return day === null || day === undefined ? '自定义' : `每月 ${day} 日起`;
  }
  return settleCycle || '—';
}
