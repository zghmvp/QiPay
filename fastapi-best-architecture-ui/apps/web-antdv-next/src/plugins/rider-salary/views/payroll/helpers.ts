import type { MoneyValue } from '../../types/common';
import type {
  PayrollDetailItem,
  SubjectBreakdownItem,
} from '../../types/payroll';

export function moneyNumber(value: MoneyValue): number {
  if (value === null || value === undefined || value === '') return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** 分位比较，避免 UI 另造第四个数 */
export function moneyEquals(a: MoneyValue, b: MoneyValue): boolean {
  return Math.round(moneyNumber(a) * 100) === Math.round(moneyNumber(b) * 100);
}

export function reconciliationHolds(options: {
  advance: MoneyValue;
  deduction: MoneyValue;
  gross: MoneyValue;
  net: MoneyValue;
}): boolean {
  const expected =
    moneyNumber(options.gross) -
    moneyNumber(options.deduction) -
    moneyNumber(options.advance);
  return moneyEquals(expected, options.net);
}

export function isAdvanceDetail(row: PayrollDetailItem): boolean {
  return row.source === 'advance';
}

export function isGrossDetail(row: PayrollDetailItem): boolean {
  return Boolean(row.include_in_gross) && !isAdvanceDetail(row);
}

export function isDeductionDetail(row: PayrollDetailItem): boolean {
  return !row.include_in_gross && !isAdvanceDetail(row);
}

export function isGrossBreakdown(row: SubjectBreakdownItem): boolean {
  if ((row.sources || []).includes('advance')) return false;
  return row.include_in_gross === true;
}

export function isDeductionBreakdown(row: SubjectBreakdownItem): boolean {
  if ((row.sources || []).includes('advance')) return false;
  return row.include_in_gross === false;
}

function traceRemark(trace?: null | Record<string, unknown>): string {
  if (!trace) return '';
  const direct = trace['备注'] ?? trace['说明'];
  if (direct !== undefined && direct !== null && String(direct).trim()) {
    return String(direct).trim();
  }
  const vars = trace['变量'];
  if (vars && typeof vars === 'object') {
    const rec = vars as Record<string, unknown>;
    const nested = rec['备注'] ?? rec['说明'] ?? rec['remark'];
    if (nested !== undefined && nested !== null && String(nested).trim()) {
      return String(nested).trim();
    }
  }
  return '';
}

/** 空备注展示「无说明」，不另造录入必填 */
export function detailRemark(row: {
  calc_trace?: null | Record<string, unknown>;
  remark?: null | string;
}): string {
  const explicit = row.remark?.trim();
  if (explicit) return explicit;
  return traceRemark(row.calc_trace) || '无说明';
}
