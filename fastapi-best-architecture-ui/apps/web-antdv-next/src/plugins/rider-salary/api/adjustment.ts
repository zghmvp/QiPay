import type {
  AdjustmentForm,
  AdjustmentQuery,
  AdjustmentResult,
  BatchAdjustmentItem,
} from '../types/adjustment';
import type { PageResult } from '../types/common';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/adjustments';

export async function getAdjustmentListApi(params: AdjustmentQuery) {
  return requestClient.get<PageResult<AdjustmentResult>>(BASE, { params });
}

export async function getAdjustmentApi(pk: number) {
  return requestClient.get<AdjustmentResult>(`${BASE}/${pk}`);
}

export async function createAdjustmentApi(data: AdjustmentForm) {
  return requestClient.post<AdjustmentResult>(BASE, data);
}

export async function createAdjustmentBatchApi(items: BatchAdjustmentItem[]) {
  return requestClient.post<AdjustmentResult[]>(`${BASE}/batch`, { items });
}

export async function updateAdjustmentApi(
  pk: number,
  data: Partial<AdjustmentForm> & { reason: string },
) {
  return requestClient.put(`${BASE}/${pk}`, data);
}

export async function deleteAdjustmentApi(pk: number, reason: string) {
  return requestClient.delete(`${BASE}/${pk}`, { data: { reason } });
}
