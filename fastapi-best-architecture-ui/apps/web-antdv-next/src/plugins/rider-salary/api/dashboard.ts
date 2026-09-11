import type { DashboardSummary } from '../types/dashboard';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/dashboard';

export async function getDashboardSummaryApi(params: {
  month?: string;
  site_id?: number;
}) {
  return requestClient.get<DashboardSummary>(`${BASE}/summary`, { params });
}
