export interface ExportConfirmOptions {
  dateFrom: string;
  dateTo: string;
  periodId?: number;
  siteId: number;
  title?: string;
}

export interface ExportConfirmResult {
  attentionCount: number;
  bookedAdjustmentCount: number;
  excludeAttention: boolean;
  excludeAttentionAdjustments: boolean;
  syncDropCount: number;
  unbookedAdjustmentCount: number;
}
