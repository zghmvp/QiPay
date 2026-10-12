/** 删除周期按钮只认这个权限码，不认生成周期。 */
export const PERIOD_DELETE_PERM = 'rs:period:delete';

export interface PeriodDeleteRow {
  payroll_count?: null | number;
  status: string;
}

/** 开放且还没有薪资结果的周期才允许删除。 */
export function canDeletePeriod(row: PeriodDeleteRow): boolean {
  return row.status === 'open' && !(row.payroll_count ?? 0);
}

/** 只有 rs:period:delete 且周期可删时才显示删除按钮。 */
export function showPeriodDelete(
  hasDeletePerm: boolean,
  row: PeriodDeleteRow,
): boolean {
  return hasDeletePerm && canDeletePeriod(row);
}
