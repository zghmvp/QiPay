export interface AdjustmentResult {
  amount: number | string;
  biz_date: string;
  created_time: string;
  direction?: null | string;
  direction_label?: null | string;
  hint?: null | string;
  id: number;
  is_locked: boolean;
  operator_id?: null | number;
  period_id?: null | number;
  remark: string;
  rider_id: number;
  rider_job_no?: null | string;
  rider_name?: null | string;
  signed_amount?: null | number | string;
  site_id: number;
  subject_id: number;
  subject_name?: null | string;
  updated_time?: null | string;
}

export interface AdjustmentForm {
  amount: number | string;
  biz_date: string;
  reason?: string;
  remark: string;
  rider_id: number;
  subject_id: number;
}

export interface AdjustmentQuery {
  date_from?: string;
  date_to?: string;
  direction?: string;
  id?: number;
  page?: number;
  rider_id?: number;
  size?: number;
  site_id?: number;
  subject_id?: number;
}

export interface BatchAdjustmentItem {
  amount: number | string;
  biz_date: string;
  remark: string;
  rider_id: number;
  subject_id: number;
}
