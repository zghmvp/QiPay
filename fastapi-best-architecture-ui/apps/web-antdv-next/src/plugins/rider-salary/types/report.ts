import type { MoneyValue } from './common';

export interface CostSummaryRow {
  advance_deduction: MoneyValue;
  gross: MoneyValue;
  month: string;
  net: MoneyValue;
  site_code: string;
  site_id: number;
  site_name: string;
  slip_count: number;
}

export interface CostSummary {
  advance_deduction: MoneyValue;
  gross: MoneyValue;
  month?: null | string;
  net: MoneyValue;
  rows: CostSummaryRow[];
  slip_count: number;
}
