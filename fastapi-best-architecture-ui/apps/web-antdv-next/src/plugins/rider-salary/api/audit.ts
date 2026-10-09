import type { AuditLogQuery, AuditLogResult } from '../types/audit';
import type { PageResult } from '../types/common';

import { requestClient } from '#/api/request';

import { downloadNamedBlob } from '../utils/download';

export async function getAuditLogListApi(params: AuditLogQuery) {
  return requestClient.get<PageResult<AuditLogResult>>(
    '/api/v1/rider-salary/audit-logs',
    { params },
  );
}

export async function exportAuditLogsApi(
  params?: Omit<AuditLogQuery, 'page' | 'size'>,
) {
  return downloadNamedBlob(
    '/api/v1/rider-salary/audit-logs/export',
    '操作日志.xlsx',
    { params },
  );
}
