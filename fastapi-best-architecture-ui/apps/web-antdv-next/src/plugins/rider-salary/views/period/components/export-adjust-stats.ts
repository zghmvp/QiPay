import type { PeriodWithPayrolls } from '../../../types/period';

import { getPeriodApi } from '../../../api/period';

import type { ExportConfirmOptions, ExportConfirmPeriod } from './export-confirm-types';

export interface ExportAdjustStats {
  attentionCount: number;
  bookedCount: number;
  periodId: number;
  range: string;
  syncDropCount: number;
  unbookedCount: number;
}

export function resolveExportPeriods(
  data: ExportConfirmOptions,
): ExportConfirmPeriod[] {
  if (data.periods?.length) return data.periods;
  if (data.periodId) {
    return [
      {
        id: data.periodId,
        range: `${data.dateFrom} ~ ${data.dateTo}`,
      },
    ];
  }
  return [];
}

export async function loadPeriodExportStats(
  period: ExportConfirmPeriod,
): Promise<ExportAdjustStats> {
  const row: PeriodWithPayrolls = await getPeriodApi(period.id);
  const range =
    period.range ||
    (row.start_date && row.end_date
      ? `${row.start_date} ~ ${row.end_date}`
      : `周期 #${period.id}`);
  return {
    attentionCount: Number(row.attention_order_count ?? 0) || 0,
    bookedCount: Number(row.booked_adjustment_count ?? 0) || 0,
    periodId: period.id,
    range,
    syncDropCount: Number(row.attention_adjustment_count ?? 0) || 0,
    unbookedCount: Number(row.unbooked_adjustment_count ?? 0) || 0,
  };
}

export async function loadExportAdjustStats(
  data: ExportConfirmOptions,
): Promise<ExportAdjustStats[]> {
  const periods = resolveExportPeriods(data);
  if (!periods.length) {
    throw new Error('缺少周期，无法统计需关注与奖惩条数');
  }
  return Promise.all(periods.map((period) => loadPeriodExportStats(period)));
}
