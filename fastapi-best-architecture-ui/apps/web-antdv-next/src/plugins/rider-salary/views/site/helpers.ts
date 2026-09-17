/** 空 / 未填 / 非数字 → 1；0 表示本站禁止预支，不得改写成 1。 */
export function normalizeMonthlyAdvanceLimit(value: unknown): number {
  if (value === null || value === undefined) return 1;
  if (typeof value === 'string' && value.trim() === '') return 1;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.max(0, Math.trunc(n));
}

/** 列表展示：接口未返回时「—」；0 标明禁止预支，不与金额上限混写。 */
export function formatMonthlyAdvanceLimit(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '—';
  if (n === 0) return '0（本站禁止预支）';
  return String(Math.trunc(n));
}
