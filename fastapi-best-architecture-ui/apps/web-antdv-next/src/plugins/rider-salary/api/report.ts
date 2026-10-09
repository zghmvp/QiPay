import type { CostSummary } from '../types/report';

import { requestClient } from '#/api/request';

export async function getCostSummaryApi(params?: {
  month?: string;
  site_id?: number;
}) {
  return requestClient.get<CostSummary>(
    '/api/v1/rider-salary/reports/costs',
    { params },
  );
}
