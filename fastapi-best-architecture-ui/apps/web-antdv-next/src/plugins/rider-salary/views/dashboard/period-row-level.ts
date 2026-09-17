/** 站点级周期：rider_id 缺省或 0，不得用某个骑手名冒充。 */
export function isSiteLevelPeriodRow(
  record: Record<string, unknown>,
): boolean {
  const riderId = Number(record.rider_id ?? 0);
  return !Number.isFinite(riderId) || riderId <= 0;
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value ?? '').trim();
    if (text) return text;
  }
  return '';
}

/**
 * 倒计时 / 需重算行辨识：站点级写「站点级」；骑手级写工号+姓名。
 * 不得两行只剩同一段 range。
 */
export function periodRowLevelLabel(
  record: Record<string, unknown>,
): string {
  if (isSiteLevelPeriodRow(record)) return '站点级';
  const name = firstText(record.rider_name, record.name);
  const jobNo = firstText(record.job_no, record.rider_job_no);
  if (jobNo && name) return `${jobNo} ${name}`;
  if (name) return name;
  if (jobNo) return jobNo;
  return `骑手 ${Number(record.rider_id)}`;
}

export function applyRiderNames(
  items: Record<string, unknown>[],
  names: Map<number, { job_no: string; name: string }>,
): Record<string, unknown>[] {
  return items.map((item) => {
    if (isSiteLevelPeriodRow(item)) return item;
    if (firstText(item.rider_name, item.name, item.job_no, item.rider_job_no)) {
      return item;
    }
    const hit = names.get(Number(item.rider_id));
    if (!hit) return item;
    return { ...item, job_no: hit.job_no, rider_name: hit.name };
  });
}
