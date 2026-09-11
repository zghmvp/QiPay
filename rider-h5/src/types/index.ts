export type MoneyValue = number | string | null | undefined

export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
}

export interface CaptchaResult {
  is_enabled: boolean
  expire_seconds: number
  uuid: string
  image: string
}

export interface LoginParams {
  username: string
  password: string
  uuid: string
  captcha: string
}

export interface LoginUser {
  id: number
  username: string
  nickname: string | null
}

export interface LoginResult {
  access_token: string
  access_token_expire_time: string
  session_uuid: string
  user: LoginUser
}

export interface MeCurrentPlan {
  version_id: number | null
  plan_name: string | null
  short_name: string | null
  version_no: number | null
  mode_tag: string | null
  start_date: string | null
  end_date: string | null
}

export interface MeProfile {
  rider_id: number
  job_no: string
  name: string
  site_id: number
  site_name: string
  employ_type: string
  employ_type_label: string
  hire_date: string
  current_plan: MeCurrentPlan | null
  advance_limit: MoneyValue
  has_in_flight_advance: boolean
}

export interface PayrollEstimate {
  period_range: string
  period_status: string
  order_count: number
  gross: MoneyValue
  deduction_total: MoneyValue
  advance_deduction_estimate: MoneyValue
  net_estimate: MoneyValue
  is_estimate: boolean
  updated_at: string | null
}

export interface CalendarPeriodChip {
  id: number
  range: string
  status: string
}

export interface CalendarMonthSummary {
  order_count: number
  valid_order_count: number
  gross: MoneyValue
  bonus: MoneyValue
  penalty: MoneyValue
  deduction_total: MoneyValue
  advance_deduction: MoneyValue
  net: MoneyValue
  periods: CalendarPeriodChip[]
  stale: boolean
}

export interface CalendarDayItem {
  date: string
  order_count: number
  valid_order_count: number
  net_adjust: MoneyValue
  subjects: string[]
  plan_version_id: number | null
  plan_short_name: string | null
  plan_color: string | null
  day_status: string
  period_id: number | null
  period_status: string | null
  is_locked: boolean
}

export interface CalendarPlanBand {
  plan_version_id: number | null
  short_name: string | null
  color: string | null
  start: string
  end: string
}

export interface CalendarMonth {
  month: string
  summary: CalendarMonthSummary
  days: CalendarDayItem[]
  plan_bands: CalendarPlanBand[]
}

export interface CalendarPlanInfo {
  version_id: number | null
  plan_name: string | null
  short_name: string | null
  version_no: number | null
  mode_tag: string | null
}

export interface CalendarPeriodInfo {
  id: number | null
  range: string | null
  status: string | null
}

export interface CalendarDayFlagInfo {
  bad_weather: boolean
  high_temp: boolean
  promo: boolean
  is_holiday: boolean
  remark: string | null
}

export interface CalendarHitDetail {
  subject: string
  amount: MoneyValue
}

export interface CalendarDayOrder {
  id: number
  order_no: string
  distance_km: MoneyValue
  weight_jin: MoneyValue
  order_time: string
  deliver_time: string | null
  status: string
  amount: MoneyValue
  details: CalendarHitDetail[]
}

export interface CalendarDailyItem {
  subject: string
  name: string | null
  amount: MoneyValue
}

export interface CalendarAdjustmentItem {
  id: number
  subject: string
  direction: string
  amount: MoneyValue
  remark: string
}

export interface CalendarDayTotals {
  order_count: number
  formula_amount: MoneyValue
  manual_bonus: MoneyValue
  manual_penalty: MoneyValue
  net: MoneyValue
}

export interface CalendarDayDetail {
  date: string
  plan: CalendarPlanInfo | null
  period: CalendarPeriodInfo | null
  day_flag: CalendarDayFlagInfo | null
  day_status: string
  orders: CalendarDayOrder[]
  daily_items: CalendarDailyItem[]
  adjustments: CalendarAdjustmentItem[]
  totals: CalendarDayTotals
}

export interface MeAdjustmentItem {
  id: number
  biz_date: string
  subject_name: string
  direction: string
  amount: MoneyValue
  remark: string
}

export interface MePlanItem {
  name: string
  subject_name: string
}

export interface MePlanBinding {
  plan_version_id: number
  plan_name: string
  short_name: string
  color: string
  version_no: number
  mode_tag: string
  binding_type: string
  start_date: string
  end_date: string | null
  is_current: boolean
  items: MePlanItem[]
}

export interface MePlan {
  bindings: MePlanBinding[]
}

export interface NoticeDetail {
  id: number
  title: string
  content: string
  site_id: number | null
  publisher_id: number
  publish_time: string | null
  status: string
  status_label?: string
  created_time: string
  updated_time: string | null
}

export interface AdvanceLimit {
  limit: MoneyValue
  used_pending_amount: MoneyValue
  available: MoneyValue
}

export interface AdvanceTimelineItem {
  operate_time: string
  operator_name: string
  action: string
  reason: string | null
  description: string | null
}

export interface AdvanceDetail {
  id: number
  rider_id: number
  site_id: number
  amount: MoneyValue
  reason: string
  status: string
  status_label?: string
  approver_id: number | null
  approve_time: string | null
  approve_remark: string | null
  paid_by: number | null
  paid_time: string | null
  deducted_amount: MoneyValue
  remaining_amount: MoneyValue
  deduct_status: string
  deduct_status_label?: string
  submit_time: string | null
  cancel_time: string | null
  rider_job_no: string | null
  rider_name: string | null
  site_name: string | null
  approver_name: string | null
  paid_by_name: string | null
  timeline: AdvanceTimelineItem[]
  created_time: string | null
  updated_time: string | null
}

export interface CreateAdvancePayload {
  amount: number
  reason: string
}

export interface ResetPasswordPayload {
  old_password: string
  new_password: string
  confirm_password: string
}
