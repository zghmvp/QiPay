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
  attention_adjustment_count?: number;
  attention_order_count?: number;
  booked_adjustment_count?: number;
  last_calc_failures?: CalculateRiderFailure[];
  last_calc_status?: null | string;
  last_calc_status_label?: null | string;
  last_calc_status_message?: null | string;
  last_calc_success_ids?: number[];
  payrolls: PayrollSummary[];
  unbooked_adjustment_count?: number;
}

export interface PeriodQuery extends PageParams {
  month?: string;
  rider_id?: number;
  site_id?: number;
  stale?: boolean | string;
  status?: string;
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

export interface CalculateRiderFailure {
  errors: string[];
  job_no?: null | string;
  rider_id: number;
  rider_name?: null | string;
}

export interface CalculatePeriodResult {
  calc_status?: null | string;
  calc_status_label?: null | string;
  calculated: number;
  calculated_rider_ids?: number[];
  failed?: CalculateRiderFailure[];
  failed_count?: number;
  queued: boolean;
  sync_limit?: number;
  target_rider_count?: number;
  unselected_means_all?: string;
  warnings: string[];
}

export interface CalcRiderOption {
  id: number;
  job_no: string;
  name: string;
}

export interface CalcRiderPageResult {
  items: CalcRiderOption[];
  listed_count: number;
  page: number;
  size: number;
  total: number;
  truncated: boolean;
  truncated_hint?: null | string;
  unselected_means_all?: string;
}

export interface CalcPrecheckDeeplink {
  path: string;
  query?: null | Record<string, string>;
}

export interface CalcPrecheckBlocker {
  code: string;
  deeplink?: CalcPrecheckDeeplink | null;
  job_no?: null | string;
  messages: string[];
  rider_id: number;
  rider_name?: null | string;
}

export interface CalcPrecheckWarning {
  code: string;
  deeplink?: CalcPrecheckDeeplink | null;
  messages: string[];
}

export interface CalcPrecheckResult {
  attention_order_count?: number;
  blockers: CalcPrecheckBlocker[];
  calc_status?: null | string;
  calc_status_label?: null | string;
  calc_status_message?: null | string;
  can_run: boolean;
  eligible_rider_count: number;
  period_id: number;
  stale_count: number;
  sync_limit?: number;
  unselected_means_all?: string;
  warnings: CalcPrecheckWarning[];
}

export interface LockPreviewResult {
  adjustment_count?: number;
  lock_adjustment_count?: number;
  lock_order_count?: number;
  lock_payroll_count?: number;
  lock_rider_count?: number;
  order_count?: number;
  payroll_count?: number;
  rider_level_skip_count?: number;
  skip_rider_count?: number;
  skipped_rider_count?: number;
  skipped_rider_level_count?: number;
  will_lock_adjustment_count?: number;
  will_lock_order_count?: number;
  will_lock_payroll_count?: number;
  will_lock_rider_count?: number;
}

export interface ReversePeriodResult {
  reversal_count: number;
  reversal_net_total: MoneyValue;
}
