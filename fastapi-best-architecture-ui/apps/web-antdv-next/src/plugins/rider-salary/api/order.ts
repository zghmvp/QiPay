import type { PageResult } from '../types/common';
import type {
  ImportBatchQuery,
  ImportBatchResult,
  ImportResult,
  OrderForm,
  OrderQuery,
  OrderResult,
} from '../types/order';

import { requestClient } from '#/api/request';

import { downloadNamedBlob } from '../utils/download';

const BASE = '/api/v1/rider-salary/orders';
const BATCH = '/api/v1/rider-salary/import-batches';

export async function getOrderListApi(params: OrderQuery) {
  return requestClient.get<PageResult<OrderResult>>(BASE, { params });
}

export async function getOrderApi(pk: number) {
  return requestClient.get<OrderResult>(`${BASE}/${pk}`);
}

export async function createOrderApi(data: OrderForm) {
  return requestClient.post<OrderResult>(BASE, data);
}

export async function updateOrderApi(
  pk: number,
  data: Partial<OrderForm> & { reason: string },
) {
  return requestClient.put<OrderResult>(`${BASE}/${pk}`, data);
}

export async function deleteOrderApi(pk: number, reason: string) {
  return requestClient.delete(`${BASE}/${pk}`, { params: { reason } });
}

export async function importOrdersApi(data: {
  auto_recalc: boolean;
  file: File;
  site_id: number;
  skip_errors: boolean;
}) {
  const formData = new FormData();
  formData.append('file', data.file);
  formData.append('site_id', String(data.site_id));
  formData.append('skip_errors', data.skip_errors ? 'true' : 'false');
  formData.append('auto_recalc', data.auto_recalc ? 'true' : 'false');
  return requestClient.post<ImportResult>(`${BASE}/import`, formData, {
    timeout: 180_000,
  });
}

export async function downloadImportTemplateApi() {
  return downloadNamedBlob(`${BASE}/import-template`, '订单导入模板.xlsx');
}

export async function getImportBatchListApi(params: ImportBatchQuery) {
  return requestClient.get<PageResult<ImportBatchResult>>(BATCH, { params });
}

export async function getImportBatchApi(pk: number) {
  return requestClient.get<ImportBatchResult>(`${BATCH}/${pk}`);
}

export async function downloadErrorReportApi(pk: number) {
  return downloadNamedBlob(
    `${BATCH}/${pk}/error-report`,
    `导入错误报告-${pk}.xlsx`,
  );
}
