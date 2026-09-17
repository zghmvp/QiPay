import dayjs from 'dayjs';

export const LOCK_COUNTDOWN_TITLE = '锁账倒计时';
export const LOCK_COUNTDOWN_HORIZON_DAYS = 3;

export function daysLeftOf(
  record: { days_left?: unknown; end_date?: unknown },
  today = dayjs(),
): null | number {
  const raw = record.days_left;
  if (raw !== null && raw !== undefined && raw !== '') {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  const end = String(record.end_date ?? '');
  if (!end) return null;
  const endDay = dayjs(end);
  if (!endDay.isValid()) return null;
  return endDay.startOf('day').diff(today.startOf('day'), 'day');
}

/** 3 天内到期，或已过期仍未锁。+10 天远周期不占待办。 */
export function isDueCountdownItem(daysLeft: null | number): boolean {
  if (daysLeft === null) return false;
  return daysLeft <= LOCK_COUNTDOWN_HORIZON_DAYS;
}

export function isOverdueUnlocked(daysLeft: null | number): boolean {
  return daysLeft !== null && daysLeft < 0;
}

export function dueCountdownText(daysLeft: null | number): string {
  if (daysLeft === null) return '—';
  if (daysLeft < 0) return `已过期未锁 ${Math.abs(daysLeft)} 天`;
  return `剩余 ${daysLeft} 天`;
}
