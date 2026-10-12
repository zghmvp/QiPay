export interface BatchRowError {
  reason: string;
  row: number;
}

function asRecord(value: unknown): null | Record<string, unknown> {
  if (value && typeof value === 'object') return value as Record<string, unknown>;
  return null;
}

/** 从接口错误里取出统一响应体。全局拦截器抛出的是 axios 错误。 */
export function readErrorPayload(
  error: unknown,
): null | Record<string, unknown> {
  const root = asRecord(error);
  if (!root) return null;
  const response = asRecord(root.response);
  const fromResponse = asRecord(response?.data);
  if (fromResponse && ('data' in fromResponse || 'msg' in fromResponse)) {
    return fromResponse;
  }
  if ('data' in root || 'msg' in root) return root;
  return null;
}

/** 批量奖惩的全部行错误。每条含提交序号和中文原因。 */
export function parseBatchRowErrors(error: unknown): BatchRowError[] {
  const data = asRecord(readErrorPayload(error)?.data);
  const raw = data?.errors;
  if (!Array.isArray(raw)) return [];
  const rows: BatchRowError[] = [];
  for (const item of raw) {
    const row = asRecord(item);
    const index = row?.row;
    const reason = row?.reason;
    const valid =
      typeof index === 'number' &&
      Number.isInteger(index) &&
      index > 0 &&
      typeof reason === 'string' &&
      reason.length > 0;
    if (valid) rows.push({ reason, row: index });
  }
  return rows;
}
