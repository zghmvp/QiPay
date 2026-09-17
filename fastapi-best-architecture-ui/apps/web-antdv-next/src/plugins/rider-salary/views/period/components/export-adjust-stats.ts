import type { PeriodWithPayrolls } from '../../../types/period';

import { getPeriodApi } from '../../../api/period';

import type { ExportConfirmOptions } from './export-confirm-types';

export interface ExportAdjustStats {
  attentionCount: number;
  bookedCount: number;
  syncDropCount: number;
  unbookedCount: number;
}

export async function loadExportAdjustStats(
  data: ExportConfirmOptions,
): Promise<ExportAdjustStats> {
  if (!data.periodId) {
    return {
      attentionCount: 0,
      bookedCount: 0,
      syncDropCount: 0,
      unbookedCount: 0,
    };
  }
  const period: PeriodWithPayrolls = await getPeriodApi(data.periodId);
  return {
    attentionCount: Number(period.attention_order_count ?? 0) || 0,
    bookedCount: Number(period.booked_adjustment_count ?? 0) || 0,
    syncDropCount: Number(period.attention_adjustment_count ?? 0) || 0,
    unbookedCount: Number(period.unbooked_adjustment_count ?? 0) || 0,
  };
}
