import type { MoneyValue, PageParams } from './common';

export interface OrderResult {
  amount?: MoneyValue;
  biz_date: string;
  created_time: string;
  deliver_time?: null | string;
  distance_km: MoneyValue;
  id: number;
  import_batch_id?: null | number;
  is_locked: boolean;
  order_no: string;
  order_time: string;
  remark?: null | string;
  rider_id: number;
  rider_job_no?: string;
  rider_name?: string;
  site_id: number;
  site_name?: string;
  source: string;
  source_label?: string;
  status: string;
  status_label?: string;
  updated_time?: null | string;
  weight_jin: MoneyValue;
}

export interface OrderForm {
  amount?: MoneyValue;
  deliver_time?: null | string;
  distance_km: MoneyValue;
  order_no: string;
  order_time: string;
  remark?: null | string;
  rider_id: number;
  site_id: number;
  status: string;
  weight_jin: MoneyValue;
}

export interface OrderQuery extends PageParams {
  attention?: boolean;
  date_from?: string;
  date_to?: string;
  import_batch_id?: number;
  is_locked?: boolean;
  missing_delivery?: boolean;
  order_no?: string;
  rider_id?: number;
  site_id?: number;
  status?: string;
}

export interface ImportErrorItem {
  order_no?: null | string;
  reason: string;
  row: number;
}

export interface ImportResult {
  batch_id?: null | number;
  errors: ImportErrorItem[];
  failed_rows: number;
  recalc_job_id?: null | number;
  status: string;
  success_rows: number;
  total_rows: number;
}

export interface ImportBatchResult {
  created_time: string;
  date_from?: null | string;
  date_to?: null | string;
  error_report?: null | unknown;
  failed_rows: number;
  file_name: string;
  id: number;
  operator_id: number;
  remark?: null | string;
  site_id: number;
  site_name?: string;
  status: string;
  status_label?: string;
  success_rows: number;
  total_rows: number;
  updated_time?: null | string;
}

export interface ImportBatchQuery extends PageParams {
  site_id?: number;
  status?: string;
}
