import type { PageResult } from '../types/common';
import type {
  PayrollDetailItem,
  PayrollDetailQuery,
  PayrollGroupedDetail,
  PayrollQuery,
  PayrollSummary,
} from '../types/payroll';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/payrolls';

export async function getPayrollListApi(params: PayrollQuery) {
  return requestClient.get<PageResult<PayrollSummary>>(BASE, { params });
}

export async function getPayrollApi(pk: number) {
  return requestClient.get<PayrollGroupedDetail>(`${BASE}/${pk}`);
}

export async function getPayrollDetailsApi(
  pk: number,
  params?: PayrollDetailQuery,
) {
  return requestClient.get<PageResult<PayrollDetailItem>>(
    `${BASE}/${pk}/details`,
    { params },
  );
}
