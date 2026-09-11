import type {
  AdvanceActionParam,
  AdvanceQuery,
  AdvanceReasonParam,
  AdvanceResult,
} from '../types/advance';
import type { PageResult } from '../types/common';

import { requestClient } from '#/api/request';

import { downloadNamedBlob } from '../utils/download';

const BASE = '/api/v1/rider-salary/advances';

export async function getAdvanceListApi(params: AdvanceQuery) {
  return requestClient.get<PageResult<AdvanceResult>>(BASE, { params });
}

export async function getAdvanceApi(pk: number) {
  return requestClient.get<AdvanceResult>(`${BASE}/${pk}`);
}

export async function approveAdvanceApi(pk: number, data?: AdvanceActionParam) {
  return requestClient.post(`${BASE}/${pk}/approve`, data ?? {});
}

export async function rejectAdvanceApi(pk: number, data: AdvanceReasonParam) {
  return requestClient.post(`${BASE}/${pk}/reject`, data);
}

export async function markPaidAdvanceApi(
  pk: number,
  data?: AdvanceActionParam,
) {
  return requestClient.post(`${BASE}/${pk}/mark-paid`, data ?? {});
}

export async function cancelAdvanceApi(pk: number, data: AdvanceReasonParam) {
  return requestClient.post(`${BASE}/${pk}/cancel`, data);
}

export async function exportAdvancesApi(params?: Omit<AdvanceQuery, 'page' | 'size'>) {
  return downloadNamedBlob(`${BASE}/export`, '预支明细.xlsx', { params });
}
