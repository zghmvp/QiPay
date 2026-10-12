import type { EmployHistoryForm, PlanBindingForm } from '../../types/rider';

/** 方案绑定的写权限。没有这个码时，新增、编辑、解除都不显示。 */
export const BINDING_WRITE_PERM = 'rs:rider:binding';

/** 用工历史的写权限。没有这个码时，新增、编辑、删除都不显示。 */
export const EMPLOY_WRITE_PERM = 'rs:rider:employ';

export interface PlanVersionOption {
  label: string;
  value: number;
}

export interface BindingActionRow {
  end_date?: null | string;
  plan_short_name?: null | string;
  plan_version_id: number;
  start_date: string;
}

export interface EmployActionRow {
  employ_type: string;
  employ_type_label?: null | string;
  end_date?: null | string;
  start_date: string;
}

/** 没有写权限时不显示编辑和删除。 */
export function showHistoryActions(hasWritePerm: boolean): boolean {
  return hasWritePerm;
}

/** 把空结束日显示成「长期」或「至今」。 */
export function formatAffectedSpan(
  startDate: string,
  endDate: null | string | undefined,
  openLabel: string,
): string {
  const endText = endDate?.trim() ? endDate.trim() : openLabel;
  return `${startDate} ~ ${endText}`;
}

const RECALC_CONSEQUENCE = '该区间内未锁账的薪资结果将被标记为需重算';

/** 解除绑定前的确认文案：带方案名、受影响区间和重算后果。 */
export function bindingRemoveContent(row: BindingActionRow): string {
  const name = row.plan_short_name?.trim() || `版本 ${row.plan_version_id}`;
  const span = formatAffectedSpan(row.start_date, row.end_date, '长期');
  return `确认解除「${name}」？受影响区间：${span}。${RECALC_CONSEQUENCE}。`;
}

/** 删除用工历史前的确认文案：带类型、受影响区间和重算后果。 */
export function employRemoveContent(row: EmployActionRow): string {
  const label = row.employ_type_label?.trim() || row.employ_type;
  const span = formatAffectedSpan(row.start_date, row.end_date, '至今');
  return `确认删除「${label}」用工历史？受影响区间：${span}。${RECALC_CONSEQUENCE}。`;
}

function blankToNull(value: null | string | undefined): null | string {
  if (value == null) return null;
  const text = String(value).trim();
  return text ? text : null;
}

/**
 * 编辑绑定始终提交完整区间。
 * 结束日留空会传 null，后端据此改成长期；漏传结束日会把原结束日清掉。
 */
export function toBindingUpdate(form: PlanBindingForm): PlanBindingForm {
  return {
    binding_type: form.binding_type,
    end_date: blankToNull(form.end_date),
    plan_version_id: Number(form.plan_version_id),
    remark: blankToNull(form.remark),
    start_date: form.start_date,
  };
}

/** 编辑用工历史始终提交完整区间，结束日留空表示至今。 */
export function toEmployUpdate(form: EmployHistoryForm): EmployHistoryForm {
  return {
    employ_type: form.employ_type,
    end_date: blankToNull(form.end_date),
    remark: blankToNull(form.remark),
    start_date: form.start_date,
  };
}

/**
 * 编辑时把当前绑定的版本留在下拉里。
 * 启用列表没有它时仍能看到原版本，避免一打开就把版本改丢。
 */
export function mergePlanVersionOptions(
  active: PlanVersionOption[],
  current?: Pick<BindingActionRow, 'plan_short_name' | 'plan_version_id'>,
): PlanVersionOption[] {
  if (!current) return active;
  if (active.some((item) => item.value === current.plan_version_id)) {
    return active;
  }
  const name = current.plan_short_name?.trim();
  return [
    {
      label: name
        ? `${name}（当前绑定）`
        : `版本 ${current.plan_version_id}（当前绑定）`,
      value: current.plan_version_id,
    },
    ...active,
  ];
}
