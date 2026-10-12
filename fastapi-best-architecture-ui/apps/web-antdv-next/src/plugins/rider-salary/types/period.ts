import type { MoneyValue, PageParams } from './common';
import type { PayrollSummary } from './payroll';

export interface PeriodResult {
  created_time?: null | string;
  cycle_type: string;
  cycle_type_label?: string;
  end_date: string;
  gross_total?: MoneyValue;
  id: number;
  kind_counts?: Record<string, number>;
  locked_by?: null | number;
  locked_time?: null | string;
  net_total?: MoneyValue;
  paid_by?: null | number;
  paid_time?: null | string;
  payroll_count?: number;
  remark?: null | string;
  reopened_by?: null | number;
  reopened_time?: null | string;
  rider_count?: number;
  rider_id: number;
  rider_job_no?: null | string;
  rider_name?: null | string;
  site_code?: null | string;
  site_id: number;
  site_name?: null | string;
  stale_count?: number;
  start_date: string;
  status: string;
  status_label?: string;
  updated_time?: null | string;
}

export interface PeriodWithPayrolls extends PeriodResult {
  payrolls: PayrollSummary[];
}

export interface PeriodQuery extends PageParams {
  month?: string;
  rider_id?: number;
  site_id?: number;
  /** 单个状态，或多个状态用英文逗号分隔 */
  status?: string;
  /** 为 true 时只返回存在需重算草稿的周期 */
  stale?: boolean;
}

export interface GeneratePeriodParam {
  month: string;
  site_id: number;
}

export interface GeneratedPeriodItem {
  created: boolean;
  cycle_type: string;
  end_date: string;
  id: number;
  rider_id: number;
  site_id: number;
  start_date: string;
  status: string;
}

export interface GeneratePeriodResult {
  created_count: number;
  items: GeneratedPeriodItem[];
  month: string;
  site_id: number;
  skipped_count: number;
}

export interface CalculatePeriodParam {
  rider_ids?: null | number[];
}

export interface CalculatePeriodResult {
  calculated: number;
  job_id?: null | number;
  queued: boolean;
  warnings: string[];
}

export interface CalcJobFailure {
  job_no: string;
  reason: string;
  rider_id: number;
}

export interface CalcJobDetail {
  done_count: number;
  error_message?: null | string;
  failed_count: number;
  failures: CalcJobFailure[];
  finished_time?: null | string;
  id: number;
  period_id: number;
  site_id: number;
  started_time?: null | string;
  status: string;
  status_label: string;
  success_count: number;
  total_count: number;
  warnings: string[];
}

export interface ReversePeriodResult {
  reversal_count: number;
  reversal_net_total: MoneyValue;
}

export interface LockCheckRiderItem {
  job_no: string;
  rider_id: number;
  rider_name?: null | string;
}

export interface LockCheckResult {
  can_lock: boolean;
  empty: boolean;
  message?: null | string;
  missing_supplement?: LockCheckRiderItem[];
  needs_recalc: LockCheckRiderItem[];
  uncalculated: LockCheckRiderItem[];
}

export interface CarryForwardParam {
  reason?: string;
  rider_ids?: number[];
}

export interface CarryForwardResult {
  created_count: number;
  net_total: MoneyValue;
  rider_ids: number[];
}

export interface MarkPaidPeriodResult {
  warning?: null | string;
}
