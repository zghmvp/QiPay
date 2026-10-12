export interface RiderResult {
  account_status?: null | number;
  account_status_label?: null | string;
  advance_limit?: null | number | string;
  created_time: string;
  cycle_config_override?: null | Record<string, unknown>;
  employ_type: string;
  employ_type_label?: string;
  hire_date: string;
  id: number;
  job_no: string;
  leave_date?: null | string;
  name: string;
  phone?: null | string;
  plan_color?: null | string;
  plan_short_name?: null | string;
  plan_version_id?: null | number;
  remark?: null | string;
  settle_cycle_override?: null | string;
  site_id: number;
  site_name?: null | string;
  status: string;
  status_label?: string;
  updated_time?: null | string;
  user_id?: null | number;
}

export interface RiderForm {
  advance_limit?: null | number | string;
  cycle_config_override?: null | Record<string, unknown>;
  employ_type: string;
  hire_date: string;
  job_no: string;
  name: string;
  phone?: null | string;
  reason?: null | string;
  remark?: null | string;
  settle_cycle_override?: null | string;
  site_id: number;
  status?: string;
}

/** 编辑骑手：不含用工类型、状态、离职日期 */
export interface RiderUpdateForm {
  advance_limit?: null | number | string;
  hire_date?: string;
  job_no?: string;
  name?: string;
  phone?: null | string;
  reason?: null | string;
  remark?: null | string;
  settle_cycle_override?: null | string;
  site_id?: number;
}

export interface RiderQuery {
  employ_type?: string;
  keyword?: string;
  page?: number;
  size?: number;
  site_id?: number;
  status?: string;
}

export interface PlanBindingResult {
  binding_type: string;
  binding_type_label?: string;
  created_time: string;
  end_date?: null | string;
  id: number;
  plan_color?: null | string;
  plan_short_name?: null | string;
  plan_version_id: number;
  remark?: null | string;
  rider_id: number;
  start_date: string;
  updated_time?: null | string;
}

export interface PlanBindingForm {
  binding_type: string;
  end_date?: null | string;
  plan_version_id: number;
  remark?: null | string;
  start_date: string;
}

export interface EmployHistoryResult {
  created_time: string;
  employ_type: string;
  employ_type_label?: string;
  end_date?: null | string;
  id: number;
  remark?: null | string;
  rider_id: number;
  start_date: string;
  updated_time?: null | string;
}

export interface EmployHistoryForm {
  employ_type: string;
  end_date?: null | string;
  remark?: null | string;
  start_date: string;
}

export interface RiderLeaveForm {
  leave_date: string;
  reason: string;
}

export interface RiderLeaveResult {
  hints: string[];
  rejected_advance_count: number;
  to_pay_advance_count: number;
}

export interface LeaveSettlementResult {
  created: boolean;
  end_date: string;
  hint: string;
  leave_date: string;
  period_id: number;
  remark?: null | string;
  rider_id: number;
  site_id: number;
  start_date: string;
  status: string;
}

export interface RiderAccountForm {
  password?: null | string;
  reason?: null | string;
}

export interface IssuedRiderPassword {
  initial_password?: null | string;
  username: string;
}

export interface EffectivePlanSegment {
  end: string;
  plan_color?: null | string;
  plan_short_name?: null | string;
  plan_version_id?: null | number;
  start: string;
}

export interface BatchPlanBindingForm {
  binding_type: string;
  end_date?: null | string;
  plan_version_id: number;
  remark?: null | string;
  rider_ids: number[];
  start_date: string;
}

export interface BatchBindingItem {
  binding_id: number;
  job_no: string;
  name: string;
  rider_id: number;
}

export interface BatchBindingResult {
  count: number;
  items: BatchBindingItem[];
}

export interface BatchAccountForm {
  reason?: null | string;
  rider_ids: number[];
}

export interface BatchIssuedPassword {
  initial_password: string;
  job_no: string;
  name: string;
  rider_id: number;
  username: string;
}

export interface BatchIssuedPasswordResult {
  items: BatchIssuedPassword[];
}
