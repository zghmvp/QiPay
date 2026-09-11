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
