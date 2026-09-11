import type { AuditLogQuery, AuditLogResult } from '../types/audit';
import type { PageResult } from '../types/common';

import { requestClient } from '#/api/request';

export async function getAuditLogListApi(params: AuditLogQuery) {
  return requestClient.get<PageResult<AuditLogResult>>(
    '/api/v1/rider-salary/audit-logs',
    { params },
  );
}
