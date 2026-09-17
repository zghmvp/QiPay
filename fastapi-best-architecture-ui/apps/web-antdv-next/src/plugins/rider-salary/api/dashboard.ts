import type {
  BatchRecalcStaleParam,
  BatchRecalcStalePreview,
  BatchRecalcStaleResult,
  DashboardSummary,
  LatestRecalcJobResult,
  RecalcJobDetail,
} from '../types/dashboard';

import { requestClient } from '#/api/request';

import {
  readLastRecalcJob,
  rememberRecalcJob,
} from '../utils/last-recalc-job';

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

export async function getLatestRecalcJobApi(siteId: number) {
  return requestClient.get<LatestRecalcJobResult>(`${JOB_BASE}/latest`, {
    params: { site_id: siteId },
  });
}

/** 优先 GET /recalc-jobs/latest（200 + job 可空）；接口失败时才回退 localStorage。 */
export async function fetchLatestSiteRecalcJob(siteId: number) {
  try {
    const res = await getLatestRecalcJobApi(siteId);
    if (res?.job) {
      rememberRecalcJob(siteId, res.job.id);
      return res.job;
    }
    return null;
  } catch {
    const stored = readLastRecalcJob(siteId);
    if (!stored) return null;
    try {
      return await getRecalcJobApi(stored.jobId);
    } catch {
      return null;
    }
  }
}

export async function retryRecalcJobApi(pk: number) {
  return requestClient.post<RecalcJobDetail>(`${JOB_BASE}/${pk}/retry`);
}
