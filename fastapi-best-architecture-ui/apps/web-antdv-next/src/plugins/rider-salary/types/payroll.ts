import type { MoneyValue, PageParams } from './common';

export interface PayrollDailyResult {
  biz_date: string;
  day_status: string;
  formula_amount: MoneyValue;
  id?: null | number;
  manual_bonus: MoneyValue;
  manual_penalty: MoneyValue;
  net_adjust: MoneyValue;
  order_count: number;
  period_id?: null | number;
  plan_version_id?: null | number;
  rider_id: number;
  valid_order_count: number;
}

export interface PayrollDetailItem {
  adjustment_id?: null | number;
  advance_id?: null | number;
  amount: MoneyValue;
  biz_date?: null | string;
  calc_trace?: null | Record<string, unknown>;
  id?: null | number;
  include_in_gross: boolean;
  name?: null | string;
  order_id?: null | number;
  order_no?: null | string;
  payroll_id?: null | number;
  plan_item_id?: null | number;
  plan_item_name?: null | string;
  plan_version_id?: null | number;
  plan_version_name?: null | string;
  rider_id: number;
  source: string;
  stage: string;
  subject_code?: null | string;
  subject_id: number;
  subject_name?: null | string;
}

export interface SubjectBreakdownItem {
  amount_sum: MoneyValue;
  direction?: null | string;
  include_in_gross?: boolean | null;
  line_count: number;
  sources: string[];
  subject_code?: null | string;
  subject_id?: null | number;
  subject_name?: null | string;
}

export interface AdvanceLineItem {
  advance_id: number;
  amount: MoneyValue;
  calc_trace?: null | Record<string, unknown>;
  deduct_status?: null | string;
  remaining_after?: MoneyValue | null;
}

export interface PlanVersionLabel {
  code?: null | string;
  id: number;
  name?: null | string;
}

export interface PayrollSummary {
  advance_deduction: MoneyValue;
  bonus_total: MoneyValue;
  calc_by?: null | number;
  calc_time?: null | string;
  calc_version: number;
  created_time?: null | string;
  cycle_type?: null | string;
  daily_total: MoneyValue;
  deduction_total: MoneyValue;
  gross: MoneyValue;
  id: number;
  job_no?: null | string;
  kind: string;
  net: MoneyValue;
  order_count: number;
  penalty_total: MoneyValue;
  period_end?: null | string;
  period_id: number;
  period_start?: null | string;
  period_status?: null | string;
  period_total: MoneyValue;
  per_order_total: MoneyValue;
  plan_version_ids?: null | number[];
  reversed: boolean;
  reversed_of_id?: null | number;
  rider_id: number;
  rider_job_no?: null | string;
  rider_name?: null | string;
  site_id?: null | number;
  site_name?: null | string;
  stale: boolean;
  status: string;
  updated_time?: null | string;
  valid_order_count: number;
  warnings?: null | string[];
}

export interface PayrollGroupedDetail extends PayrollSummary {
  advance_lines: AdvanceLineItem[];
  dailies: PayrollDailyResult[];
  details: Record<string, PayrollDetailItem[]>;
  plan_version_labels: PlanVersionLabel[];
  subject_breakdown: SubjectBreakdownItem[];
}

export interface PayrollQuery extends PageParams {
  kind?: string;
  period_id?: number;
  rider_id?: number;
  site_id?: number;
  stale?: boolean;
  status?: string;
}

export interface PayrollDetailQuery extends PageParams {
  biz_date?: string;
  order_id?: number;
  stage?: string;
  subject_id?: number;
}
