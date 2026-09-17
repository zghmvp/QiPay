export interface ExportConfirmOptions {
  dateFrom: string;
  dateTo: string;
  siteId: number;
  title?: string;
}

export interface ExportConfirmResult {
  attentionCount: number;
  excludeAttention: boolean;
}
