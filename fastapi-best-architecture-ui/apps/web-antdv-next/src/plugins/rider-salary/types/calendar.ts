import type { MoneyValue } from './common';

export interface CalendarPeriodChip {
  id: number;
  range: string;
  status: string;
}

export interface CalendarMonthSummary {
  advance_deduction: MoneyValue;
  bonus: MoneyValue;
  deduction_total: MoneyValue;
  gross: MoneyValue;
  net: MoneyValue;
  order_count: number;
  penalty: MoneyValue;
  periods: CalendarPeriodChip[];
  stale: boolean;
  valid_order_count: number;
}

export interface CalendarDayItem {
  date: string;
  day_status: string;
  is_locked: boolean;
  net_adjust: MoneyValue;
  order_count: number;
  period_id?: null | number;
  period_status?: null | string;
  plan_color?: null | string;
  plan_short_name?: null | string;
  plan_version_id?: null | number;
  subjects: string[];
  valid_order_count: number;
}

export interface CalendarPlanBand {
  color?: null | string;
  end: string;
  plan_version_id?: null | number;
  short_name?: null | string;
  start: string;
}

export interface CalendarMonth {
  days: CalendarDayItem[];
  month: string;
  plan_bands: CalendarPlanBand[];
  summary: CalendarMonthSummary;
}

export interface CalendarPlanInfo {
  mode_tag?: null | string;
  plan_name?: null | string;
  short_name?: null | string;
  version_id?: null | number;
  version_no?: null | number;
}

export interface CalendarPeriodInfo {
  id?: null | number;
  range?: null | string;
  status?: null | string;
}


export interface CalendarHitDetail {
  amount: MoneyValue;
  calc_trace?: null | Record<string, unknown>;
  subject: string;
}

export interface CalendarDayOrder {
  amount?: MoneyValue;
  deliver_time?: null | string;
  details: CalendarHitDetail[];
  distance_km: MoneyValue;
  id: number;
  order_no: string;
  order_time: string;
  status: string;
  weight_jin: MoneyValue;
}

export interface CalendarDailyItem {
  amount: MoneyValue;
  calc_trace?: null | Record<string, unknown>;
  name?: null | string;
  subject: string;
}

export interface CalendarAdjustmentItem {
  amount: MoneyValue;
  direction: string;
  id: number;
  remark: string;
  subject: string;
}

export interface CalendarDayTotals {
  formula_amount: MoneyValue;
  manual_bonus: MoneyValue;
  manual_penalty: MoneyValue;
  net: MoneyValue;
  order_count: number;
}

export interface CalendarDayDetail {
  adjustments: CalendarAdjustmentItem[];
  daily_items: CalendarDailyItem[];
  date: string;
  is_holiday?: boolean;
  day_status: string;
  has_daily_cache?: boolean;
  orders: CalendarDayOrder[];
  period?: CalendarPeriodInfo | null;
  plan?: CalendarPlanInfo | null;
  totals: CalendarDayTotals;
}
