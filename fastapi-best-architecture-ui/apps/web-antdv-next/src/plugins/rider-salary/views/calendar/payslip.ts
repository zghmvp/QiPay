import type { RouteLocationRaw } from 'vue-router';

import { getPayrollListApi } from '../../api/payroll';

/** 该骑手 × 该周期工资条列表（已筛，不是全站周期抽屉）。 */
export function riderPeriodPayslipQuery(
  riderId: number,
  periodId: number,
): RouteLocationRaw {
  return {
    path: '/rider-salary/payroll',
    query: {
      period_id: String(periodId),
      rider_id: String(riderId),
    },
  };
}

/** 有该条则进 `/payroll/:id`，否则进已筛列表。禁止 `/period?id=` 全站抽屉。 */
export async function resolveRiderPeriodPayslip(
  riderId: number,
  periodId: number,
): Promise<RouteLocationRaw> {
  if (!(riderId > 0) || !(periodId > 0)) {
    return riderPeriodPayslipQuery(riderId, periodId);
  }
  try {
    const res = await getPayrollListApi({
      page: 1,
      period_id: periodId,
      rider_id: riderId,
      size: 5,
    });
    const items = res?.items ?? [];
    const hit =
      items.find((row) => row.kind === 'normal' && !row.reversed) ??
      items.find((row) => row.kind === 'normal') ??
      items[0];
    if (hit?.id) {
      return { path: `/rider-salary/payroll/${hit.id}` };
    }
  } catch {
    /* 列表筛该骑手该期条 */
  }
  return riderPeriodPayslipQuery(riderId, periodId);
}
