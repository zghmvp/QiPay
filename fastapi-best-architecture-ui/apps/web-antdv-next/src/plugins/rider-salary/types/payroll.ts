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
  plan_version_id?: null | number;
  rider_id: number;
  source: string;
  stage: string;
  subject_id: number;
}

export interface PayrollSummary {
  advance_deduction: MoneyValue;
  bonus_total: MoneyValue;
  calc_by?: null | number;
  calc_time?: null | string;
  calc_version: number;
  created_time?: null | string;
  daily_total: MoneyValue;
  deduction_total: MoneyValue;
  gross: MoneyValue;
  id: number;
  job_no?: null | string;
  kind: string;
  net: MoneyValue;
  order_count: number;
  penalty_total: MoneyValue;
  period_id: number;
  period_total: MoneyValue;
  per_order_total: MoneyValue;
  plan_version_ids?: null | number[];
  reversed: boolean;
  reversed_of_id?: null | number;
  rider_id: number;
  rider_name?: null | string;
  stale: boolean;
  status: string;
  updated_time?: null | string;
  valid_order_count: number;
  warnings?: null | string[];
}

export interface PayrollGroupedDetail extends PayrollSummary {
  dailies: PayrollDailyResult[];
  details: Record<string, PayrollDetailItem[]>;
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
