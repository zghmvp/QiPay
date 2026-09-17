import type { PageResult } from '../types/common';
import type {
  CalcPrecheckResult,
  CalcRiderPageResult,
  CalculatePeriodParam,
  CalculatePeriodResult,
  GeneratePeriodParam,
  GeneratePeriodResult,
  LockPreflightResult,
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

export async function getPeriodCalcRidersApi(
  pk: number,
  params?: { keyword?: string; page?: number; size?: number },
) {
  return requestClient.get<CalcRiderPageResult>(`${BASE}/${pk}/calc-riders`, {
    params: {
      keyword: params?.keyword || undefined,
      page: params?.page ?? 1,
      size: params?.size ?? 200,
    },
  });
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

export async function lockPreflightPeriodApi(pk: number) {
  return requestClient.get<LockPreflightResult>(`${BASE}/${pk}/lock-preflight`);
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

export async function exportPeriodApi(
  pk: number,
  params?: {
    exclude_attention?: boolean;
    exclude_attention_adjustments?: boolean;
  },
) {
  return downloadNamedBlob(`${BASE}/${pk}/export`, `周期薪资-${pk}.xlsx`, {
    params: {
      exclude_attention: Boolean(params?.exclude_attention),
      exclude_attention_adjustments: Boolean(
        params?.exclude_attention_adjustments,
      ),
    },
  });
}
