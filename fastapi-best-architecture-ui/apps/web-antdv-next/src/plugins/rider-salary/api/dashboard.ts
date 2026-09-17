import type {
  BatchRecalcStaleParam,
  BatchRecalcStalePreview,
  BatchRecalcStaleResult,
  DashboardSummary,
  RecalcJobDetail,
} from '../types/dashboard';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/dashboard';
const JOB_BASE = '/api/v1/rider-salary/recalc-jobs';

export async function getDashboardSummaryApi(params: {
  month?: string;
  site_id?: number;
}) {
  return requestClient.get<DashboardSummary>(`${BASE}/summary`, { params });
}

export async function previewStaleBatchRecalcApi(data: BatchRecalcStaleParam) {
  return requestClient.post<BatchRecalcStalePreview>(
    `${BASE}/stale-batch/preview`,
    data,
  );
}

export async function submitStaleBatchRecalcApi(data: BatchRecalcStaleParam) {
  return requestClient.post<BatchRecalcStaleResult>(
    `${BASE}/stale-batch`,
    data,
  );
}

export async function getRecalcJobApi(pk: number) {
  return requestClient.get<RecalcJobDetail>(`${JOB_BASE}/${pk}`);
}

export async function retryRecalcJobApi(pk: number) {
  return requestClient.post<RecalcJobDetail>(`${JOB_BASE}/${pk}/retry`);
}
