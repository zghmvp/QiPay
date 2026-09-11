export interface AuditLogResult {
  action: string;
  after?: null | Record<string, unknown>;
  before?: null | Record<string, unknown>;
  created_time: string;
  description?: null | string;
  id: number;
  ip?: null | string;
  module: string;
  operate_time: string;
  operator_id: number;
  operator_name: string;
  reason?: null | string;
  target_id?: null | string;
  target_label: string;
  target_type: string;
  trace_id?: null | string;
}

export interface AuditLogQuery {
  action?: string;
  date_from?: string;
  date_to?: string;
  keyword?: string;
  module?: string;
  operator?: string;
  page?: number;
  size?: number;
  target_type?: string;
}
