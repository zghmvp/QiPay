import type { PlanBindingForm } from '../../types/rider';

export interface BatchRiderLabel {
  job_no: string;
  name: string;
}

export interface IssuedPasswordLine {
  initial_password: string;
  name: string;
  username: string;
}

/** 勾选行去重，丢掉没有 ID 的行。 */
export function selectedRiderIds(rows: { id?: null | number }[]): number[] {
  const seen = new Set<number>();
  const ids: number[] = [];
  for (const row of rows) {
    const id = row?.id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids;
}

/** 批量绑定请求体。不带密码字段。 */
export function batchBindingBody(
  riderIds: number[],
  form: PlanBindingForm,
): {
  binding_type: string;
  end_date: null | string;
  plan_version_id: number;
  remark: null | string;
  rider_ids: number[];
  start_date: string;
} {
  const remark = form.remark?.trim();
  return {
    binding_type: form.binding_type,
    end_date: form.end_date || null,
    plan_version_id: form.plan_version_id,
    remark: remark ? remark : null,
    rider_ids: riderIds,
    start_date: form.start_date,
  };
}

/** 批量开户或重置。只传骑手和原因，不传统一密码。 */
export function batchAccountBody(riderIds: number[], reason?: null | string) {
  const text = reason?.trim();
  return {
    reason: text ? text : null,
    rider_ids: riderIds,
  };
}

/** 抽屉里展示的骑手摘要。人多时只列前面几位。 */
export function batchRiderSummary(riders: BatchRiderLabel[], limit = 8): string {
  const head = riders
    .slice(0, limit)
    .map((item) => `${item.job_no} ${item.name}`)
    .join('、');
  if (riders.length > limit) return `${head} 等 ${riders.length} 人`;
  return head;
}

/** 复制到剪贴板的密码表。关闭弹窗后无法再从系统取回。 */
export function formatIssuedPasswords(items: IssuedPasswordLine[]): string {
  const lines = ['工号\t姓名\t初始密码'];
  for (const item of items) {
    lines.push(`${item.username}\t${item.name}\t${item.initial_password}`);
  }
  return lines.join('\n');
}
