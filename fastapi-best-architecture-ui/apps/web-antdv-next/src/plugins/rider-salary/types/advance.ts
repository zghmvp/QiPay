import type { MoneyValue, PageParams } from './common';

export interface AdvanceTimelineItem {
  action: string;
  description?: null | string;
  operate_time: string;
  operator_name: string;
  reason?: null | string;
}

export interface AdvanceResult {
  amount: MoneyValue;
  approve_remark?: null | string;
  approve_time?: null | string;
  approver_id?: null | number;
  approver_name?: null | string;
  cancel_time?: null | string;
  created_time?: null | string;
  deduct_status: string;
  deduct_status_label?: string;
  deducted_amount: MoneyValue;
  id: number;
  paid_by?: null | number;
  paid_by_name?: null | string;
  paid_time?: null | string;
  reason: string;
  remaining_amount?: MoneyValue;
  rider_id: number;
  rider_job_no?: null | string;
  rider_name?: null | string;
  site_id: number;
  site_name?: null | string;
  status: string;
  status_label?: string;
  submit_time?: null | string;
  timeline?: AdvanceTimelineItem[];
  updated_time?: null | string;
}

export interface AdvanceQuery extends PageParams {
  date_from?: string;
  date_to?: string;
  id?: number;
  rider_id?: number;
  site_id?: number;
  status?: string;
}

export interface AdvanceActionParam {
  remark?: null | string;
}

export interface AdvanceReasonParam {
  reason: string;
}
