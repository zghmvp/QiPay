type SchemaItem = { defaultValue?: unknown; fieldName?: string };

/** 从路由 query.status 取出预筛值。空串和数组不消费。 */
export function statusFromQuery(status: unknown): string | undefined {
  if (typeof status !== 'string') return undefined;
  const value = status.trim();
  return value || undefined;
}

/** 把 status 写进查询表单的默认值，其它字段不动。 */
export function withStatusDefault<T extends SchemaItem>(
  schema: T[],
  status: string | undefined,
): T[] {
  if (!status) return schema;
  return schema.map((item) =>
    item.fieldName === 'status' ? { ...item, defaultValue: status } : item,
  );
}
