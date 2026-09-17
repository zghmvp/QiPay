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
}

export interface CalculatePeriodResult {
  calculated: number;
  failed?: CalculateRiderFailure[];
  queued: boolean;
  warnings: string[];
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
  blockers: CalcPrecheckBlocker[];
  can_run: boolean;
  eligible_rider_count: number;
  period_id: number;
  stale_count: number;
  warnings: CalcPrecheckWarning[];
}

export interface ReversePeriodResult {
  reversal_count: number;
  reversal_net_total: MoneyValue;
}
