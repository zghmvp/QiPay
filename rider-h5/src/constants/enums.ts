export interface EnumOption {
  color: string
  label: string
  value: string
}

function opts(items: Array<[string, string, string]>): EnumOption[] {
  return items.map(([value, label, color]) => ({ color, label, value }))
}

export const EMPLOY_TYPE_OPTIONS = opts([
  ['part_time', '兼职', 'warning'],
  ['full_time', '全职', 'primary'],
])

export const BINDING_TYPE_OPTIONS = opts([
  ['default', '默认', 'primary'],
  ['override', '区间覆盖', 'warning'],
])

export const PLAN_MODE_TAG_OPTIONS = opts([
  ['per_order', '纯按单', 'primary'],
  ['base_plus_commission', '底薪加提成', 'success'],
  ['commission', '纯提成', 'primary'],
  ['commission_only', '纯提成', 'primary'],
  ['guarantee_plus_commission', '保底加提成', 'warning'],
  ['guaranteed_plus_commission', '保底加提成', 'warning'],
  ['custom', '自定义', 'default'],
])

export const ORDER_STATUS_OPTIONS = opts([
  ['completed', '已完成', 'success'],
  ['cancelled', '已取消', 'default'],
  ['abnormal', '配送异常', 'warning'],
  ['refunded', '已退款', 'danger'],
])

export const PERIOD_STATUS_OPTIONS = opts([
  ['open', '开放', 'success'],
  ['locked', '已锁账', 'danger'],
  ['paid', '已发薪', 'primary'],
  ['reopened', '补发中', 'warning'],
])

export const DAY_STATUS_OPTIONS = opts([
  ['has_data', '有数据', 'success'],
  ['no_orders', '无数据', 'default'],
  ['not_imported', '未导入', 'warning'],
  ['no_plan', '无方案', 'danger'],
])

export const ADVANCE_STATUS_OPTIONS = opts([
  ['draft', '草稿', 'default'],
  ['pending', '待审核', 'warning'],
  ['rejected', '已驳回', 'danger'],
  ['to_pay', '待发放', 'primary'],
  ['paid', '已发放', 'success'],
  ['cancelled', '已取消', 'default'],
])

export const DEDUCT_STATUS_OPTIONS = opts([
  ['none', '未抵扣', 'default'],
  ['partial', '部分抵扣', 'warning'],
  ['done', '已抵扣', 'success'],
])

export function enumLabel(
  options: EnumOption[],
  value: null | number | string | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—'
  const hit = options.find((item) => String(item.value) === String(value))
  return hit?.label ?? String(value)
}

export function enumColor(
  options: EnumOption[],
  value: null | number | string | undefined,
): string {
  const hit = options.find((item) => String(item.value) === String(value))
  return hit?.color ?? 'default'
}

export function vantTagType(
  color: string,
): 'default' | 'primary' | 'success' | 'warning' | 'danger' {
  if (
    color === 'primary' ||
    color === 'success' ||
    color === 'warning' ||
    color === 'danger'
  ) {
    return color
  }
  return 'default'
}
