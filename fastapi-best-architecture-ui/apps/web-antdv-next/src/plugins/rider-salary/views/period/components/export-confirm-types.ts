export interface ExportConfirmOptions {
  dateFrom: string;
  dateTo: string;
  periodId?: number;
  siteId: number;
  title?: string;
}

export interface ExportConfirmResult {
  attentionCount: number;
  excludeAttention: boolean;
}
