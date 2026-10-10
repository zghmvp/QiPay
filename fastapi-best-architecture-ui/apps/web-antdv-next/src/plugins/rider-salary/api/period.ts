import type { PageResult } from '../types/common';
import type {
  CalcJobDetail,
  CalculatePeriodParam,
  CalculatePeriodResult,
  CarryForwardParam,
  CarryForwardResult,
  GeneratePeriodParam,
  GeneratePeriodResult,
  LockCheckResult,
  MarkPaidPeriodResult,
  PeriodQuery,
  PeriodResult,
  PeriodWithPayrolls,
  ReversePeriodResult,
} from '../types/period';

import { requestClient } from '#/api/request';

import { downloadNamedBlob } from '../utils/download';

const BASE = '/api/v1/rider-salary/periods';

export async function getPeriodListApi(params: PeriodQuery) {
  return requestClient.get<PageResult<PeriodResult>>(BASE, { params });
}

export async function getPeriodApi(pk: number) {
  return requestClient.get<PeriodWithPayrolls>(`${BASE}/${pk}`);
}

export async function generatePeriodsApi(data: GeneratePeriodParam) {
  return requestClient.post<GeneratePeriodResult>(`${BASE}/generate`, data);
}

export async function calculatePeriodApi(
  pk: number,
  data?: CalculatePeriodParam,
) {
  return requestClient.post<CalculatePeriodResult>(
    `${BASE}/${pk}/calculate`,
    data ?? {},
  );
}

export async function getCalcJobApi(jobId: number) {
  return requestClient.get<CalcJobDetail>(`${BASE}/calc-jobs/${jobId}`);
}

export async function lockCheckPeriodApi(pk: number) {
  return requestClient.get<LockCheckResult>(`${BASE}/${pk}/lock-check`);
}

export async function carryForwardPeriodApi(
  pk: number,
  data?: CarryForwardParam,
) {
  return requestClient.post<CarryForwardResult>(
    `${BASE}/${pk}/carry-forward`,
    data ?? {},
  );
}

export async function lockPeriodApi(pk: number, reason: string) {
  return requestClient.post(`${BASE}/${pk}/lock`, { reason });
}

export async function markPaidPeriodApi(pk: number, reason?: string) {
  return requestClient.post<MarkPaidPeriodResult>(`${BASE}/${pk}/mark-paid`, {
    reason,
  });
}

export async function lockPeriodWithExpectedStatusApi(
  pk: number,
  reason: string,
  expectedStatus: string,
) {
  return requestClient.post(`${BASE}/${pk}/lock`, {
    expected_status: expectedStatus,
    reason,
  });
}

export async function markPaidPeriodWithExpectedStatusApi(
  pk: number,
  reason: string | undefined,
  expectedStatus: string,
) {
  return requestClient.post<MarkPaidPeriodResult>(`${BASE}/${pk}/mark-paid`, {
    expected_status: expectedStatus,
    reason,
  });
}

export async function reversePeriodApi(pk: number, reason: string) {
  return requestClient.post<ReversePeriodResult>(`${BASE}/${pk}/reverse`, {
    reason,
  });
}

export async function deletePeriodApi(pk: number) {
  return requestClient.delete(`${BASE}/${pk}`);
}

export async function exportPeriodApi(pk: number) {
  return downloadNamedBlob(`${BASE}/${pk}/export`, `周期薪资-${pk}.xlsx`);
}
