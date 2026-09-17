export interface ExportConfirmPeriod {
  id: number;
  range?: string;
}

export interface ExportConfirmOptions {
  dateFrom: string;
  dateTo: string;
  periodId?: number;
  periods?: ExportConfirmPeriod[];
  siteId: number;
  source?: 'calendar' | 'period';
  title?: string;
}

export interface ExportConfirmResult {
  attentionCount: number;
  bookedAdjustmentCount: number;
  excludeAttention: boolean;
  excludeAttentionAdjustments: boolean;
  periodIds: number[];
  syncDropCount: number;
  unbookedAdjustmentCount: number;
}
