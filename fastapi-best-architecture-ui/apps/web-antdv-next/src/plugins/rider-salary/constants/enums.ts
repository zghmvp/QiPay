export interface EnumOption {
  color: string;
  label: string;
  value: string;
}

function opts(
  items: Array<[string, string, string]>,
): EnumOption[] {
  return items.map(([value, label, color]) => ({ color, label, value }));
}

export const CYCLE_TYPE_OPTIONS = opts([
  ['half_month', '半月结', 'processing'],
  ['month', '月结', 'success'],
  ['custom', '自定义', 'warning'],
]);

export const ENABLE_STATUS_OPTIONS = opts([
  ['enable', '启用', 'success'],
  ['disable', '停用', 'default'],
]);

export const MANAGER_ROLE_OPTIONS = opts([
  ['owner', '负责人', 'blue'],
  ['deputy', '副负责人', 'cyan'],
]);

export const EMPLOY_TYPE_OPTIONS = opts([
  ['part_time', '兼职', 'processing'],
  ['full_time', '全职', 'purple'],
]);

export const RIDER_STATUS_OPTIONS = opts([
  ['on_job', '在职', 'success'],
  ['resigned', '离职', 'default'],
]);

export const BINDING_TYPE_OPTIONS = opts([
  ['default', '默认', 'blue'],
  ['override', '区间覆盖', 'orange'],
]);

export const SUBJECT_DIRECTION_OPTIONS = opts([
  ['bonus', '奖', 'success'],
  ['penalty', '惩', 'error'],
]);

export const FEE_MODE_OPTIONS = opts([
  ['fixed', '定额', 'gold'],
  ['formula', '按公式', 'processing'],
]);

export const ENTRY_GRANULARITY_OPTIONS = opts([
  ['daily', '按日', 'cyan'],
  ['period', '按周期', 'purple'],
  ['both', '按日或按周期', 'geekblue'],
]);

export const PLAN_VERSION_STATUS_OPTIONS = opts([
  ['draft', '草稿', 'default'],
  ['active', '启用', 'success'],
  ['disabled', '停用', 'warning'],
  ['voided', '已作废', 'error'],
]);

export const PLAN_MODE_TAG_OPTIONS = opts([
  ['per_order', '纯按单', 'blue'],
  ['base_plus_commission', '底薪加提成', 'cyan'],
  ['commission', '纯提成', 'geekblue'],
  ['guarantee_plus_commission', '保底加提成', 'purple'],
  ['custom', '自定义', 'default'],
]);

export const CALC_STAGE_OPTIONS = opts([
  ['per_order', '逐单', 'blue'],
  ['daily', '按日', 'cyan'],
  ['period', '按周期', 'purple'],
]);

export const ORDER_STATUS_OPTIONS = opts([
  ['completed', '已完成', 'success'],
  ['cancelled', '已取消', 'default'],
  ['abnormal', '配送异常', 'warning'],
  ['refunded', '已退款', 'error'],
]);

export const ORDER_SOURCE_OPTIONS = opts([
  ['import', '导入', 'processing'],
  ['manual', '补录', 'gold'],
]);

export const IMPORT_BATCH_STATUS_OPTIONS = opts([
  ['processing', '处理中', 'processing'],
  ['success', '成功', 'success'],
  ['partial_failed', '部分失败', 'warning'],
  ['failed', '失败', 'error'],
]);

export const PERIOD_STATUS_OPTIONS = opts([
  ['open', '开放', 'blue'],
  ['locked', '已锁账', 'orange'],
  ['paid', '已发薪', 'green'],
  ['reopened', '补发中', 'purple'],
]);

export const PAYROLL_KIND_OPTIONS = opts([
  ['normal', '正常', 'success'],
  ['reversal', '反冲', 'error'],
  ['supplement', '补发', 'processing'],
]);

export const PAYROLL_STATUS_OPTIONS = opts([
  ['draft', '草稿', 'default'],
  ['finalized', '已定稿', 'processing'],
  ['paid', '已发薪', 'success'],
  ['voided', '已作废', 'error'],
]);

export const DETAIL_SOURCE_OPTIONS = opts([
  ['formula', '公式', 'processing'],
  ['manual', '手工', 'gold'],
  ['advance', '预支抵扣', 'orange'],
  ['reversal', '反冲', 'error'],
]);

export const DAY_STATUS_OPTIONS = opts([
  ['has_data', '有数据', 'success'],
  ['no_orders', '无数据', 'default'],
  ['not_imported', '未导入', 'warning'],
  ['no_plan', '无方案', 'orange'],
]);

export const ADVANCE_STATUS_OPTIONS = opts([
  ['draft', '草稿', 'default'],
  ['pending', '待审核', 'processing'],
  ['rejected', '已驳回', 'error'],
  ['to_pay', '待发放', 'gold'],
  ['paid', '已发放', 'success'],
  ['cancelled', '已取消', 'default'],
]);

export const DEDUCT_STATUS_OPTIONS = opts([
  ['none', '未抵扣', 'default'],
  ['partial', '部分抵扣', 'warning'],
  ['done', '已抵扣', 'success'],
]);

export const NOTICE_STATUS_OPTIONS = opts([
  ['draft', '草稿', 'default'],
  ['published', '已发布', 'success'],
  ['offline', '已下线', 'warning'],
]);

export const ACCOUNT_STATUS_OPTIONS: EnumOption[] = [
  { color: 'default', label: '未开通', value: 'none' },
  { color: 'success', label: '启用', value: '1' },
  { color: 'error', label: '停用', value: '0' },
];

export const AUDIT_MODULE_OPTIONS: EnumOption[] = [
  { color: 'blue', label: '站点管理', value: '站点管理' },
  { color: 'cyan', label: '骑手管理', value: '骑手管理' },
  { color: 'geekblue', label: '科目管理', value: '科目管理' },
  { color: 'gold', label: '奖惩录入', value: '奖惩录入' },
  { color: 'orange', label: '日标记', value: '日标记' },
  { color: 'purple', label: '站点公告', value: '站点公告' },
  { color: 'processing', label: '薪资方案', value: '薪资方案' },
  { color: 'green', label: '订单明细', value: '订单明细' },
  { color: 'magenta', label: '结算周期', value: '结算周期' },
  { color: 'volcano', label: '薪资结果', value: '薪资结果' },
];

export function enumLabel(
  options: EnumOption[],
  value: null | number | string | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—';
  const hit = options.find((item) => String(item.value) === String(value));
  return hit?.label ?? String(value);
}

export function enumColor(
  options: EnumOption[],
  value: null | number | string | undefined,
): string {
  const hit = options.find((item) => String(item.value) === String(value));
  return hit?.color ?? 'default';
}

export function enumTagOptions(options: EnumOption[]) {
  return options.map((item) => ({
    color: item.color,
    label: item.label,
    value: item.value,
  }));
}
