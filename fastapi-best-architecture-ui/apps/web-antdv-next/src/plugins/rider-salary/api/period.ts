import type { PageResult } from '../types/common';
import type {
  CalcPrecheckResult,
  CalculatePeriodParam,
  CalculatePeriodResult,
  GeneratePeriodParam,
  GeneratePeriodResult,
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

export async function calcPrecheckApi(pk: number) {
  return requestClient.get<CalcPrecheckResult>(`${BASE}/${pk}/calc-precheck`);
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

export async function lockPeriodApi(pk: number, reason: string) {
  return requestClient.post(`${BASE}/${pk}/lock`, { reason });
}

export async function markPaidPeriodApi(pk: number, reason?: string) {
  return requestClient.post(`${BASE}/${pk}/mark-paid`, { reason });
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
