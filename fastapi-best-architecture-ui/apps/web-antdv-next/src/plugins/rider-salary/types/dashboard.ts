import type { MoneyValue } from './common';

export interface DashboardCards {
  estimated_gross: MoneyValue;
  month_order_count: number;
  month_valid_order_count: number;
  on_job_riders: number;
  pending_advances: number;
  to_pay_advances: number;
}

export interface DashboardAttentionBlock {
  count: number;
  items: Record<string, unknown>[];
  key: string;
  link: string;
  title: string;
}

export interface DashboardTrendPoint {
  date: string;
  formula_amount: MoneyValue;
  order_count: number;
}

export interface DashboardRiderRank {
  job_no: string;
  name: string;
  order_count: number;
  rider_id: number;
}

export interface DashboardTopRiders {
  bottom: DashboardRiderRank[];
  top: DashboardRiderRank[];
}

export interface DashboardSummary {
  attention: DashboardAttentionBlock[];
  cards: DashboardCards;
  month: string;
  top_riders: DashboardTopRiders;
  trend: DashboardTrendPoint[];
}

export interface BatchRecalcStaleParam {
  month: string;
  site_id: number;
}

export interface BatchRecalcStalePreview {
  month: string;
  period_count: number;
  period_ranges: string[];
  site_id: number;
  site_name: string;
  stale_rider_count: number;
}

export interface BatchRecalcStaleResult {
  job_id: number;
  message: string;
  period_count: number;
  queued: boolean;
  rider_count: number;
  site_name: string;
}

export interface RecalcJobDetail {
  done_periods: number;
  failed_rider_count?: number;
  finished_time?: null | string;
  id: number;
  message?: null | string;
  month?: null | string;
  operator_id: number;
  payload?: null | {
    failed?: Array<{
      errors?: string[];
      job_no?: null | string;
      period_id?: number;
      rider_id?: number;
    }>;
    failed_period_ids?: number[];
    failed_rider_count?: number;
    period_ids?: number[];
  };
  rider_count: number;
  site_id: number;
  source: string;
  source_id?: null | number;
  source_label?: string;
  started_time?: null | string;
  status: string;
  status_label?: string;
  total_periods: number;
}

export interface LatestRecalcJobResult {
  job: RecalcJobDetail | null;
  site_id: number;
}
