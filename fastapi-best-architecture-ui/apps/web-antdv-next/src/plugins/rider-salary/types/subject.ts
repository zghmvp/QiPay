export interface SubjectResult {
  code: string;
  created_time: string;
  direction: string;
  direction_label?: string;
  entry_granularity: string;
  entry_granularity_label?: string;
  fee_mode: string;
  fee_mode_label?: string;
  fixed_amount?: null | number | string;
  id: number;
  include_in_gross: boolean;
  is_builtin: boolean;
  name: string;
  remark?: null | string;
  scope_employ_types?: null | unknown[];
  scope_sites?: null | unknown[];
  sort_order: number;
  status: string;
  status_label?: string;
  updated_time?: null | string;
}

export interface SubjectForm {
  code: string;
  direction: string;
  entry_granularity: string;
  fee_mode: string;
  fixed_amount?: null | number | string;
  include_in_gross: boolean;
  name: string;
  remark?: null | string;
  scope_employ_types?: null | string[];
  scope_sites?: null | number[];
  sort_order?: number;
  status: string;
}

export interface SubjectQuery {
  direction?: string;
  name?: string;
  page?: number;
  size?: number;
  status?: string;
}
